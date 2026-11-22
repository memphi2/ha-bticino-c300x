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
    "asyncssh",
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
    'python -m pip install "homeassistant==$HA_VERSION" -r "${{ matrix.requirements-ha }}" '
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
        ("npm", "/tests/browser"): {
            "open-pull-requests-limit": 1,
            "groups": {"browser-test-tools": {
                "applies-to": "version-updates", "patterns": ["*"],
            }},
        },
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
            "Dependabot must monitor Actions, browser tools, direct Python tools and both HA targets exactly once"
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
        expected_ha = (
            f"homeassistant>={versions['min_homeassistant']}"
            if name == "current-ha"
            else f"homeassistant=={versions[version_key]}"
        )
        if requirements != [Requirement(expected_ha)]:
            failures.append(
                f"{path} must contain only {expected_ha} for the configured validation policy"
            )
        expected_matrix.append(
            {
                "name": name,
                "python-version": versions["python"],
                "requirements-ha": path,
                "requirements-lock": tools,
            }
        )
    for name in ("validate.yml",):
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
        if (
            len(install) != 1
            or install[0].get("run", "").strip() != expected_run
            or install[0].get("env") != {"HA_VERSION": "${{ steps.ha-version.outputs.version }}"}
        ):
            failures.append(
                f"{name} must install the HA manifest and tool pins together, then run pip check"
            )
        resolvers = [step for step in job["steps"] if step.get("id") == "ha-version"]
        if len(resolvers) != 1 or resolvers[0].get("run") != (
            'python scripts/resolve_ha_version.py "${{ matrix.name }}"'
        ):
            failures.append(f"{name} must resolve the exact stable HA version before installation")
    release = yaml.safe_load((root / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    jobs = release["jobs"]
    gate = jobs["main-validation"]
    publish = jobs["publish"]
    if (
        set(jobs) != {"main-validation", "publish"}
        or publish.get("needs") != ["main-validation"]
        or any("if" in job or job.get("continue-on-error", False) for job in (gate, publish))
    ):
        failures.append("release must require canonical branch validation without a duplicate HA matrix")
    for job, ref in (
        (gate, "${{ github.sha }}"),
        (publish, "${{ needs.main-validation.outputs.commit }}"),
    ):
        checkouts = [step for step in job["steps"] if step.get("uses", "").startswith("actions/checkout@")]
        if (
            len(checkouts) != 1 or job["steps"][0] != checkouts[0]
            or checkouts[0].get("with", {}).get("ref") != ref
            or "if" in checkouts[0] or checkouts[0].get("continue-on-error", False)
        ):
            failures.append("release checkouts must pin the run SHA and verified commit before executing code")
    if gate.get("outputs") != {
        "commit": "${{ steps.verified-main.outputs.commit }}",
        "evidence-digest": "${{ steps.verified-main.outputs.evidence-digest }}",
    }:
        failures.append("release gate must expose the verified commit and evidence digest")
    verifier = [step for step in gate["steps"] if step.get("id") == "verified-main"]
    if (
        len(verifier) != 1
        or verifier[0].get("run", "").strip() != (
            'python scripts/verify_main_validation.py --tag "$RELEASE_TAG" \\\n'
            '  --wait-seconds 900 --output .release/validation-evidence.json'
        )
        or "if" in verifier[0] or verifier[0].get("continue-on-error", False)
    ):
        failures.append("release must verify canonical exact-SHA validation evidence")
    publish_steps = publish["steps"]
    for name, output in (
        ("Verify canonical validation evidence", ".release/validation-evidence.json"),
        ("Recheck canonical evidence before publication", ".release/rechecked-validation-evidence.json"),
    ):
        checks = [step for step in publish_steps if step.get("name") == name]
        if (
            len(checks) != 1
            or checks[0].get("run", "").strip() != (
                'test -n "$EVIDENCE_DIGEST"\n'
                'python scripts/verify_main_validation.py --tag "$RELEASE_TAG" \\\n'
                f'  --expect-digest "$EVIDENCE_DIGEST" --output {output}'
            )
            or checks[0].get("env") != {
                "GH_TOKEN": "${{ github.token }}",
                "RELEASE_TAG": "${{ steps.release-tag.outputs.tag }}",
                "EVIDENCE_DIGEST": "${{ needs.main-validation.outputs.evidence-digest }}",
            }
            or "if" in checks[0] or checks[0].get("continue-on-error", False)
        ):
            failures.append(f"release must require digest-pinned evidence: {name}")
    names = [step.get("name") for step in publish_steps]
    ordered = (
        "Verify canonical validation evidence", "Build HACS release zip",
        "Generate release metadata", "Verify generated attestations",
        "Recheck canonical evidence before publication", "Publish GitHub Release assets",
    )
    if (
        any(names.count(name) != 1 for name in ordered)
        or [names.index(name) for name in ordered] != sorted(names.index(name) for name in ordered)
        or names[-2:] != list(ordered[-2:])
    ):
        failures.append("release must recheck evidence before building and immediately before publishing")
    metadata = [step for step in publish["steps"] if step.get("name") == "Generate release metadata"]
    if len(metadata) != 1 or metadata[0].get("env") != {
        "C300X_VALIDATION_EVIDENCE": ".release/validation-evidence.json",
        "C300X_VALIDATION_EVIDENCE_SHA256": "${{ needs.main-validation.outputs.evidence-digest }}",
    }:
        failures.append("release metadata must consume digest-pinned canonical HA evidence")
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
