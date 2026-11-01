from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_dependency_updates import check_dependency_updates  # noqa: E402


@pytest.fixture
def policy_repo(tmp_path: Path) -> Path:
    for name in (
        "project-versions.json",
        ".github/dependabot.yml",
        ".github/workflows/validate.yml",
        ".github/workflows/release.yml",
        "requirements-dev.txt",
        "requirements-dev-min-ha.txt",
        "requirements/ha-min/requirements.txt",
        "requirements/ha-current/requirements.txt",
    ):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    return tmp_path


def _rewrite_yaml(path: Path, mutate) -> None:
    data = yaml.safe_load(path.read_text())
    mutate(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def test_repository_policy_passes() -> None:
    assert check_dependency_updates(ROOT) == []


def test_policy_does_not_depend_on_comments_or_yaml_format(policy_repo: Path) -> None:
    for path in (policy_repo / ".github").rglob("*.yml"):
        _rewrite_yaml(path, lambda _: None)
    assert check_dependency_updates(policy_repo) == []


@pytest.mark.parametrize("directory", ["ha-min", "ha-current"])
def test_ha_target_must_be_monitored(policy_repo: Path, directory: str) -> None:
    path = policy_repo / ".github/dependabot.yml"
    _rewrite_yaml(
        path,
        lambda config: config.update(
            updates=[
                entry
                for entry in config["updates"]
                if entry["directory"] != f"/requirements/{directory}"
            ]
        ),
    )
    assert check_dependency_updates(policy_repo)


@pytest.mark.parametrize(
    "option,value",
    [
        ("ignore", [{"dependency-name": "homeassistant", "versions": [">=0"]}]),
        ("exclude-paths", ["requirements.txt"]),
        ("target-branch", "unmonitored-branch"),
        ("allow", [{"dependency-name": "unrelated-package"}]),
        ("insecure-external-code-execution", "allow"),
        ("open-pull-requests-limit", 1),
        ("open-pull-requests-limit", False),
    ],
)
def test_ha_security_entry_rejects_coverage_gaps_and_routine_updates(
    policy_repo: Path,
    option: str,
    value,
) -> None:
    _rewrite_yaml(
        policy_repo / ".github/dependabot.yml",
        lambda config: next(
            entry
            for entry in config["updates"]
            if entry["directory"] == "/requirements/ha-min"
        ).update({option: value}),
    )
    assert check_dependency_updates(policy_repo)


def test_comments_cannot_satisfy_missing_ignore_policy(policy_repo: Path) -> None:
    path = policy_repo / ".github/dependabot.yml"
    _rewrite_yaml(
        path,
        lambda config: next(
            entry
            for entry in config["updates"]
            if entry["package-ecosystem"] == "pip" and entry["directory"] == "/"
        ).pop("ignore"),
    )
    path.write_text(
        path.read_text() + '\n# dependency-name: "paramiko"\n# ">=4"\n# ">=0"\n'
    )
    assert any(
        "incorrect ignore" in failure
        for failure in check_dependency_updates(policy_repo)
    )


@pytest.mark.parametrize(
    "contents",
    [
        "",
        "# homeassistant=={version}\n",
        "homeassistant==0.0.1\n",
        "homeassistant>={version}\n",
        "homeassistant=={version}\nhomeassistant=={version}\n",
        'homeassistant=={version}; python_version < "3"\n',
        "homeassistant @ https://example.com/homeassistant.whl\n",
        "homeassistant=={version}\nother-package==1.0.0\n",
    ],
)
def test_ha_manifest_must_match_release_metadata(
    policy_repo: Path, contents: str
) -> None:
    version = json.loads((policy_repo / "project-versions.json").read_text())[
        "min_homeassistant"
    ]
    (policy_repo / "requirements/ha-min/requirements.txt").write_text(
        contents.format(version=version)
    )
    assert check_dependency_updates(policy_repo)


def test_missing_ha_manifest_fails_closed(policy_repo: Path) -> None:
    (policy_repo / "requirements/ha-min/requirements.txt").unlink()
    assert check_dependency_updates(policy_repo)


@pytest.mark.parametrize("name", ["validate.yml", "release.yml"])
def test_ci_must_install_the_monitored_manifest(policy_repo: Path, name: str) -> None:
    def mutate(workflow):
        steps = workflow["jobs"]["validate"]["steps"]
        next(
            step
            for step in steps
            if step.get("name") == "Install Python validation tools"
        )["run"] = 'python -m pip install "homeassistant==2026.5.0"'

    _rewrite_yaml(policy_repo / ".github/workflows" / name, mutate)
    assert any(
        "must install" in failure for failure in check_dependency_updates(policy_repo)
    )


@pytest.mark.parametrize("name", ["validate.yml", "release.yml"])
def test_ci_must_pair_each_target_with_its_tool_set(
    policy_repo: Path, name: str
) -> None:
    _rewrite_yaml(
        policy_repo / ".github/workflows" / name,
        lambda workflow: workflow["jobs"]["validate"]["strategy"]["matrix"]["include"][
            0
        ].update({"requirements-lock": "requirements-dev.txt"}),
    )
    assert any(
        "must validate" in failure for failure in check_dependency_updates(policy_repo)
    )


def test_pip_compile_pair_cannot_return(policy_repo: Path) -> None:
    shutil.copyfile(
        policy_repo / "requirements-dev.txt", policy_repo / "requirements-dev.in"
    )
    assert any(
        "pip-compile" in failure for failure in check_dependency_updates(policy_repo)
    )


@pytest.mark.parametrize(
    "name", ["requirements-dev.txt", "requirements-dev-min-ha.txt"]
)
@pytest.mark.parametrize("addition", ["aiohttp==3.14.1\n", "pytest==9.1.1\n"])
def test_tool_pins_reject_transitive_or_duplicate_additions(
    policy_repo: Path,
    name: str,
    addition: str,
) -> None:
    path = policy_repo / name
    path.write_text(path.read_text() + addition)
    assert any(
        "direct validation tools" in failure
        for failure in check_dependency_updates(policy_repo)
    )


@pytest.mark.parametrize(
    "pin",
    [
        "pytest>=9.1.1",
        "pytest==9.*",
        'pytest==9.1.1; python_version < "3"',
        "pytest @ https://example.com/pytest.whl",
    ],
)
def test_tool_pins_must_be_exact_and_unconditional(policy_repo: Path, pin: str) -> None:
    path = policy_repo / "requirements-dev.txt"
    source = path.read_text()
    old_pin = next(line for line in source.splitlines() if line.startswith("pytest=="))
    path.write_text(source.replace(old_pin, pin))
    assert any(
        "exact package pins" in failure
        for failure in check_dependency_updates(policy_repo)
    )


@pytest.mark.parametrize(
    "contents",
    [
        "version: 2\nupdates: [",
        "version: 2\nupdates: invalid",
        "version: 2\nupdates: [null]",
        "version: 2\nupdates: [{}]",
        "!!python/object/apply:builtins.len [[1, 2]]",
    ],
)
def test_invalid_or_unsafe_yaml_fails_closed(policy_repo: Path, contents: str) -> None:
    (policy_repo / ".github/dependabot.yml").write_text(contents)
    assert check_dependency_updates(policy_repo)


@pytest.mark.parametrize("ecosystem", ["github-actions", "pip"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("schedule", {"interval": "weekly"}),
        ("open-pull-requests-limit", 5),
        (
            "groups",
            {"all-updates": {"applies-to": "security-updates", "patterns": ["*"]}},
        ),
    ],
)
def test_routine_updates_keep_quarterly_policy(
    policy_repo: Path,
    ecosystem: str,
    field: str,
    value,
) -> None:
    _rewrite_yaml(
        policy_repo / ".github/dependabot.yml",
        lambda config: next(
            entry
            for entry in config["updates"]
            if entry["directory"] == "/" and entry["package-ecosystem"] == ecosystem
        ).update({field: value}),
    )
    assert check_dependency_updates(policy_repo)
