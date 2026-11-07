"""Stable/beta channel policy and release gates use one version ordering."""

import importlib
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts.release_version import (
    is_prerelease,
    previous_release_tag,
    select_previous_tag,
    validate_version,
    version_from_tag,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("version", ["2.0.1", "2.1.0b1", "2.1.0b12", "2.1.0rc1"])
def test_release_channels(version):
    assert validate_version(version) == version
    assert version_from_tag(f"v{version}") == version
    assert is_prerelease(f"v{version}") is ("b" in version or "rc" in version)


@pytest.mark.parametrize("version", [
    "main", "01.2.3", "2.1.0b0", "2.1.0b01", "2.1.0rc0", "2.1.0-beta.1",
    "2.1.0a1", "2.1.0.dev1", "2.1.0+local", "2.1.0\n", "../../main",
    "2.1.0;command", "2.1.0b\u0661",
])
def test_noncanonical_versions_are_rejected(version):
    with pytest.raises(ValueError, match="expected"):
        validate_version(version)
    with pytest.raises(ValueError):
        is_prerelease(f"v{version}")


def test_tag_prefix_is_required():
    with pytest.raises(ValueError, match="start with v"):
        is_prerelease("2.1.0b1")


@pytest.mark.parametrize(("current", "previous"), [
    ("v2.0.0", None), ("v2.1.0b1", "v2.0.0"), ("v2.1.0b2", "v2.1.0b1"),
    ("v2.1.0b10", "v2.1.0b2"), ("v2.1.0rc1", "v2.1.0b10"),
    ("v2.1.0", "v2.1.0rc1"), ("v2.1.1", "v2.1.0"),
])
def test_agent_baseline_includes_betas_and_excludes_current_or_newer(current, previous):
    tags = ["v2.1.0", "v2.1.0b2", "v2.0.0", "v3.0.0", "v2.1.0b10",
            "v2.1.0b1", "v2.1.0rc1", "v2.1.0-invalid", "main"]
    assert select_previous_tag(tags, current) == previous


def test_previous_release_requires_reachable_tags_and_reports_git_failure(monkeypatch):
    def tags(args, **kwargs):
        assert args[-3:] == ["tag", "--merged", "HEAD"]
        return "v2.0.0\nv2.1.0b1\n"

    monkeypatch.setattr(subprocess, "check_output", tags)
    assert previous_release_tag("v2.1.0b2", ROOT) == "v2.1.0b1"

    def failed(*args, **kwargs):
        raise subprocess.CalledProcessError(128, "git")

    monkeypatch.setattr(subprocess, "check_output", failed)
    with pytest.raises(subprocess.CalledProcessError):
        previous_release_tag("v2.1.0b2", ROOT)


@pytest.mark.parametrize("version", ["2.1.0", "2.1.0b1", "2.1.0rc1"])
def test_beta_tag_keeps_manifest_notes_and_date_gates(tmp_path, monkeypatch, version):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    checker = importlib.import_module("check_release_tag")
    tag = f"v{version}"
    manifest = tmp_path / "custom_components/bticino_c300x/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"version": version}))
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(f"## {tag} - 2026-11-06\n")
    notes = tmp_path / f".github/release-notes/{tag}.md"
    notes.parent.mkdir(parents=True)
    notes.write_text(f"# {tag}\n\n## 2026-11-06\n")
    assert checker.validate_release_tag(tag, tmp_path) == []
    manifest.write_text(json.dumps({"version": "2.0.0"}))
    assert any("does not match" in error for error in checker.validate_release_tag(tag, tmp_path))
    changelog.write_text(f"## {tag} - Unreleased\n")
    notes.unlink()
    failures = checker.validate_release_tag(tag, tmp_path)
    assert any("must be dated" in error for error in failures)
    assert any("missing release notes" in error for error in failures)
    assert checker.validate_attestation_context(
        tag, workflow_ref=f"refs/tags/{tag}", workflow_commit="a" * 40,
        checkout_commit="a" * 40,
    ) == []


def test_beta_branch_has_normal_validation_browser_and_security_checks():
    for name in ("validate", "browser", "codeql"):
        workflow = yaml.safe_load((ROOT / f".github/workflows/{name}.yml").read_text())
        assert set(workflow[True]["push"]["branches"]) == {"main", "beta"}


def test_beta_publication_keeps_main_gate_assets_and_attestations():
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    assert workflow["concurrency"]["cancel-in-progress"] is False
    publish = workflow["jobs"]["publish"]
    assert set(publish["needs"]) == {"validate", "hacs", "hassfest", "main-validation", "browser"}
    steps = {step.get("name"): step for step in publish["steps"]}
    command = steps["Publish GitHub Release assets"]["run"]
    assert "scripts/publish_release.py" in command
    assert "--clobber" not in command
    assert 'scripts/release_version.py "$RELEASE_TAG"' in steps["Resolve reusable native agent"]["run"]
    assert "Validate SPDX SBOM" in steps
    assert "Verify generated attestations" in steps


@pytest.mark.parametrize("version", ["2.1.0b1", "2.1.0rc1"])
def test_repository_metadata_accepts_prereleases(tmp_path, monkeypatch, version):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    checker = importlib.import_module("check_repo")
    current = checker.CURRENT_RELEASE_VERSION
    current_line = ".".join(current.split(".")[:2]) + ".x"
    for relative in ("custom_components/bticino_c300x/manifest.json", "README.md",
                     "CHANGELOG.md", "hacs.json", "SUPPORT.md", "SECURITY.md",
                     "PRIVACY.md", "LICENSE", "NOTICE"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((ROOT / relative).read_text().replace(current, version).replace(current_line, "2.1.x"))
    notes = tmp_path / f".github/release-notes/v{version}.md"
    notes.parent.mkdir(parents=True)
    notes.write_text(f"# v{version}\n")
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    monkeypatch.setattr(checker, "CURRENT_RELEASE_VERSION", version)
    assert checker.check_release_metadata() == []
