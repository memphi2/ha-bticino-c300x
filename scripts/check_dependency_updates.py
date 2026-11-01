#!/usr/bin/env python3
"""Validate Dependabot policy and the HA manifests actually used by CI."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from check_reporting import report_failures
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
HA_TARGETS = {
    "min-ha": ("ha-min", "requirements-dev-min-ha.txt", "min_homeassistant"),
    "current-ha": ("ha-current", "requirements-dev.txt", "current_homeassistant"),
}
TOOL_NAMES = {
    "av",
    "mypy",
    "numpy",
    "packaging",
    "paramiko",
    "pyturbojpeg",
    "pytest",
    "pytest-cov",
    "pyyaml",
    "ruff",
    "spdx-tools",
    "voluptuous-serialize",
}
ROOT_EXCLUDES = [
    "requirements-dev-min-ha.txt",
    "requirements/ha-current/**",
    "requirements/ha-min/**",
]
INSTALL_COMMAND = (
    'python -m pip install -r "${{ matrix.requirements-ha }}" '
    '-r "${{ matrix.requirements-lock }}"'
)


def _read_requirements(path: Path) -> list[Requirement]:
    return [
        Requirement(line.strip())
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _check(root: Path) -> list[str]:
    failures: list[str] = []
    versions = json.loads((root / "project-versions.json").read_text(encoding="utf-8"))
    config = yaml.safe_load(
        (root / ".github/dependabot.yml").read_text(encoding="utf-8")
    )
    if not isinstance(config, dict) or config.get("version") != 2:
        return ["Dependabot must use configuration version 2"]
    updates = config.get("updates")
    if not isinstance(updates, list) or not all(
        isinstance(item, dict) for item in updates
    ):
        return ["Dependabot updates must be a list of mappings"]

    expected = {
        ("github-actions", "/"): {
            "open-pull-requests-limit": 1,
            "groups": {
                "github-actions": {
                    "applies-to": "version-updates",
                    "patterns": ["*"],
                }
            },
        },
        ("pip", "/"): {
            "open-pull-requests-limit": 1,
            "exclude-paths": ROOT_EXCLUDES,
            "groups": {
                "python-patch-minor": {
                    "applies-to": "version-updates",
                    "patterns": ["*"],
                    "update-types": ["minor", "patch"],
                }
            },
            "ignore": [
                {
                    "dependency-name": "*",
                    "update-types": ["version-update:semver-major"],
                },
                {"dependency-name": "paramiko", "versions": [">=4"]},
            ],
        },
        **{
            ("pip", f"/requirements/{directory}"): {
                "open-pull-requests-limit": 0,
            }
            for directory, _, _ in HA_TARGETS.values()
        },
    }
    actual_keys = [
        (item.get("package-ecosystem"), item.get("directory")) for item in updates
    ]
    if sorted(actual_keys) != sorted(expected):
        return [
            "Dependabot must monitor Actions, direct tools and both HA targets exactly once"
        ]
    for update in updates:
        key = (update["package-ecosystem"], update["directory"])
        for name, value in expected[key].items():
            if update.get(name) != value:
                failures.append(f"Dependabot {key}: incorrect {name}")
        if type(update.get("open-pull-requests-limit")) is not int:
            failures.append(f"Dependabot {key}: PR limit must be an integer")
        interval = "quarterly"
        if update.get("schedule", {}).get("interval") != interval:
            failures.append(
                f"Dependabot {key}: expected {interval} version-update schedule"
            )
        # These options can silently narrow coverage or enable package code execution.
        allowed = {
            "package-ecosystem",
            "directory",
            "schedule",
            "open-pull-requests-limit",
            "commit-message",
            *expected[key],
        }
        if set(update) - allowed:
            failures.append(
                f"Dependabot {key}: unexpected update options: {sorted(set(update) - allowed)}"
            )

    if (root / "requirements-dev.in").exists():
        failures.append(
            "requirements-dev.in must not turn direct tool pins into a pip-compile lock"
        )
    for name in ("requirements-dev.txt", "requirements-dev-min-ha.txt"):
        requirements = _read_requirements(root / name)
        names = [canonicalize_name(requirement.name) for requirement in requirements]
        if set(names) != TOOL_NAMES or len(names) != len(TOOL_NAMES):
            failures.append(
                f"{name} must contain only the direct validation tools, without duplicate or transitive pins"
            )
        if any(
            requirement.url
            or requirement.marker
            or requirement.extras
            or len(requirement.specifier) != 1
            or next(iter(requirement.specifier)).operator != "=="
            or "*" in str(requirement.specifier)
            for requirement in requirements
        ):
            failures.append(f"{name} must contain unconditional exact package pins")

    expected_matrix = []
    for name, (directory, tools, version_key) in HA_TARGETS.items():
        path = f"requirements/{directory}/requirements.txt"
        requirements = _read_requirements(root / path)
        if requirements != [Requirement(f"homeassistant=={versions[version_key]}")]:
            failures.append(
                f"{path} must pin only Home Assistant {versions[version_key]} from project-versions.json"
            )
        expected_matrix.append(
            {
                "name": name,
                "python-version": versions["python"],
                "requirements-ha": path,
                "requirements-lock": tools,
            }
        )
    for name in ("validate.yml", "release.yml"):
        workflow = yaml.safe_load(
            (root / ".github/workflows" / name).read_text(encoding="utf-8")
        )
        job = workflow["jobs"]["validate"]
        matrix = job["strategy"]["matrix"]
        if matrix != {"include": expected_matrix}:
            failures.append(
                f"{name} must validate both HA manifests with their matching tools and Python"
            )
        install = [
            step
            for step in job["steps"]
            if step.get("name") == "Install Python validation tools"
        ]
        expected_run = f"{INSTALL_COMMAND}\npython -m pip check"
        if len(install) != 1 or install[0].get("run", "").strip() != expected_run:
            failures.append(
                f"{name} must install the HA manifest and tool pins together, then run pip check"
            )
    return failures


def check_dependency_updates(root: Path = ROOT) -> list[str]:
    """Fail closed on missing, malformed or inconsistent update configuration."""
    try:
        return _check(root)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        yaml.YAMLError,
    ) as err:
        return [f"Invalid dependency update configuration: {err}"]


if __name__ == "__main__":
    sys.exit(
        report_failures(check_dependency_updates(), "Dependency update policy passed")
    )
