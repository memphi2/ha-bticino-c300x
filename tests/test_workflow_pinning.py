"""Keep remote workflow pins strict while allowing same-commit local calls."""

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_repo  # noqa: E402


@pytest.mark.parametrize(
    ("reference", "valid"),
    [
        ("./.github/workflows/browser.yml", True),
        ("./.github/workflows/browser.yaml", True),
        ("./.github/workflows/missing.yml", False),
        ("./.github/workflows/../browser.yml", False),
        ("./.github/actions/build", False),
        ("./.github/workflows/browser.yml@" + "a" * 40, False),
        ("actions/checkout", False),
        ("actions/checkout@v6", False),
        ("example/repo/.github/workflows/browser.yml@main", False),
        ("actions/checkout@" + "a" * 40, True),
        ("example/repo/.github/workflows/browser.yml@" + "a" * 40, True),
    ],
)
def test_workflow_references_keep_immutable_sources(
    tmp_path, monkeypatch, reference, valid
):
    workflows = tmp_path / ".github/workflows"
    workflows.mkdir(parents=True)
    permissions = {"permissions": {"contents": "read"}}
    for suffix in ("yml", "yaml"):
        (workflows / f"browser.{suffix}").write_text(yaml.safe_dump(permissions))
    (workflows / "caller.yml").write_text(
        yaml.safe_dump(
            {
                **permissions,
                "jobs": {"browser": {"uses": reference}},
            }
        )
    )
    monkeypatch.setattr(check_repo, "ROOT", tmp_path)

    findings = check_repo.check_github_automation()

    assert bool(findings) is not valid, findings


def test_local_yaml_workflow_does_not_bypass_remote_pin_checks(tmp_path, monkeypatch):
    workflows = tmp_path / ".github/workflows"
    workflows.mkdir(parents=True)
    (workflows / "browser.yaml").write_text(
        yaml.safe_dump(
            {
                "permissions": {"contents": "read"},
                "jobs": {
                    "nested": {"uses": "example/repo/.github/workflows/test.yml@main"}
                },
            }
        )
    )
    monkeypatch.setattr(check_repo, "ROOT", tmp_path)

    findings = check_repo.check_github_automation()

    assert len(findings) == 1
    assert "full commit SHA" in findings[0]
