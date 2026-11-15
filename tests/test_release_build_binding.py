"""Package consistency must not stand in for independent executable selection."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_release_contents as checker  # noqa: E402
from stage_device_agent_bundle import BundleStageError, stage_bundle  # noqa: E402


@pytest.fixture
def release_archive(tmp_path, monkeypatch):
    # A separate tracked checkout keeps these unit tests independent of unstaged
    # work in the shared tree. The real checkout consistency test stays unchanged.
    root = tmp_path / "checkout"
    component = root / "custom_components/bticino_c300x"
    component.mkdir(parents=True)
    manifest = component / "manifest.json"
    manifest.write_text(json.dumps({"version": "2.3.0"}))
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    monkeypatch.setattr(checker, "ROOT", root)
    monkeypatch.setattr(checker, "PACKAGE_METADATA", ())
    old_binary = tmp_path / "old-agent"
    old_binary.write_bytes(b"old executable")
    package = tmp_path / "package"
    package.mkdir()
    (package / "manifest.json").write_bytes(manifest.read_bytes())
    # Repackage the OLD executable with CURRENT bundle metadata and checksums.
    stage_bundle(package, version="2.3.0", skip_build=True, agent_binary=old_binary)
    archive = tmp_path / "release.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        for path in package.rglob("*"):
            if path.is_file():
                zipped.write(path, path.relative_to(package))
    return archive, old_binary


def test_relabelled_old_binary_needs_independent_build_binding(release_archive, tmp_path):
    archive, old_binary = release_archive
    with zipfile.ZipFile(archive) as zipped:
        bundle = json.loads(zipped.read("device_agent/bundle.json"))
    binary_entry = next(entry for entry in bundle["files"]
                        if entry["path"] == "device_agent/armhf/c300x-agent-native")
    assert binary_entry["sha256"] == hashlib.sha256(old_binary.read_bytes()).hexdigest()
    assert bundle["integration_version"] == "2.3.0"
    # This mode makes only a package-consistency claim, never a build-origin claim.
    checker.validate_release_contents(archive)
    current_build = tmp_path / "current-build"
    current_build.write_bytes(b"current executable")
    with pytest.raises(ValueError, match="independently supplied build output"):
        checker.validate_release_contents(archive, agent_binary=current_build)


def test_independently_selected_matching_binary_passes(release_archive):
    archive, binary = release_archive
    checker.validate_release_contents(archive, agent_binary=binary)


def test_missing_independent_build_does_not_fall_back_to_archive(release_archive, tmp_path):
    archive, _binary = release_archive
    with pytest.raises(BundleStageError, match="Missing ARMHF agent binary"):
        checker.validate_release_contents(archive, agent_binary=tmp_path / "missing")


def test_cli_uses_independent_build_argument(release_archive, tmp_path, monkeypatch):
    archive, _binary = release_archive
    current = tmp_path / "current"
    current.write_bytes(b"current build")
    monkeypatch.setattr(sys, "argv", ["check_release_contents.py", str(archive),
                                     "--agent-binary", str(current)])
    with pytest.raises(ValueError, match="independently supplied build output"):
        checker.main()
