"""One package for the Classe 300X and the Classe 100X; no network or device actions."""

import importlib
import json
import os
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_native_agent_update_legacy_bootstrap import _compile_updater

from custom_components.bticino_c300x import agent_update, device_installer
from custom_components.bticino_c300x.factory_login import factory_ssh_login

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("info", [
    {"model": "C300X"}, {"model": ""}, {}, {"model": "C100X"}, {"model": "C300X", "display_kind": "qt5_ondisk"},
])
def test_the_joint_package_is_offered_to_every_station(info):
    """No model is told to fetch another package; the agent's own updater guards a C100X."""

    state = agent_update.compare_agent_bundle(
        {**info, "version": "old", "agent": {"bundle_hash": "sha256:old", "self_update_supported": True}},
        {"version": "new", "bundle_hash": "sha256:new", "c100x_compatible": True},
    )
    assert (state.state, state.reason) == (agent_update.UPDATE_STATE_UPDATE_AVAILABLE, "version_mismatch")
    assert state.repair_fixable and state.self_update_repair_supported
    assert not hasattr(agent_update, "bundle_supports_device")


def test_explicit_c100x_gui_request_is_not_silently_ignored(tmp_path, monkeypatch):
    calls = []
    client = SimpleNamespace(run=lambda cmd: calls.append(cmd), close=lambda: calls.append("closed"))
    monkeypatch.setattr(device_installer, "_connect_device_client", lambda _: client)
    monkeypatch.setattr(device_installer, "_read_remote_config_sync", lambda *_: {})
    monkeypatch.setattr(device_installer, "_admit_station_sync", lambda *_: "qt5_ondisk")
    monkeypatch.setattr(device_installer, "_device_display_kind", lambda _: "qt5_ondisk")
    request = device_installer.C300XDeviceInstallRequest(
        host="unused.invalid", ssh_username="unused", ssh_password="unused", apply_gui_patch=True,
    )
    with pytest.raises(device_installer.C300XDeviceInstallError, match="device_install_verify_failed"):
        device_installer._install_device_agent_sync(
            request, device_installer._ResolvedBundle((), tmp_path / "unused"), b"{}")
    assert calls == ["closed"]


def test_native_c300x_rejects_a_c100x_only_bundle_and_both_take_the_joint_one(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    stager = importlib.import_module("stage_device_agent_bundle")
    native = _compile_updater(tmp_path, False, False)
    agent = tmp_path / "agent"
    stage = agent / ".update"
    binary = tmp_path / "binary"
    binary.write_bytes(b"synthetic never executed")
    stager.stage_bundle(stage, version="test", skip_build=True, agent_binary=binary)
    manifest = stage / "device_agent/bundle.json"
    document = json.loads(manifest.read_text())
    # The joint package names no single model.
    assert "c100x_only" not in document and document["c100x_compatible"] is True
    installed = agent / "c300x-agent-native"
    installed.write_bytes(b"original")
    env = {key: value for key, value in os.environ.items() if key != "C100X_TEST_MODEL"}
    for only in (True, "true", 1, None, {}):
        manifest.write_text(json.dumps({**document, "c100x_only": only}))
        result = subprocess.run([str(native), str(agent), str(manifest), "0"],
                                env=env, capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
        assert installed.read_bytes() == b"original"
        assert not (agent / "bundle.json").exists()
    manifest.write_text(json.dumps(document))
    # The joint package: a C300X takes it, and so does a C100X.
    for model_env in ({}, {"C100X_TEST_MODEL": "1"}):
        result = subprocess.run([str(native), str(agent), str(manifest), "1"],
                                env={**env, **model_env},
                                capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
        assert installed.read_bytes() == binary.read_bytes()
    # A C100X refuses a package that does not name itself compatible.
    manifest.write_text(json.dumps({key: value for key, value in document.items() if key != "c100x_compatible"}))
    result = subprocess.run([str(native), str(agent), str(manifest), "0"],
                            env={**env, "C100X_TEST_MODEL": "1"},
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_the_release_tools_work_as_in_2_10_0(monkeypatch, tmp_path):
    """No C100X policy file blocks the publication, the asset name or the shell installer."""

    assert not (ROOT / "c100x-test-policy.json").exists()
    for script in ("publish_release.py", "build_hacs_release.py", "install_c300x_device.sh", "native_build_lock.py"):
        assert "c100x-test-policy" not in (ROOT / "scripts" / script).read_text(), script
    builder = (ROOT / "scripts/build_hacs_release.py").read_text()
    assert 'output = args.output or RELEASE_ROOT / "ha-bticino-c300x.zip"' in builder


def test_test_instructions_ship_with_the_local_package(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    builder = importlib.import_module("build_hacs_release")
    monkeypatch.setattr(builder, "PACKAGE_ROOT", tmp_path)
    builder._copy_package_metadata()
    c100x_pages = sorted((ROOT / "docs/classe-100x").glob("*.md"))
    assert [page.name for page in c100x_pages] == [
        "1-setup.md", "2-use.md", "3-display.md", "4-troubleshooting.md", "5-update-and-removal.md",
    ]
    for relative in (
        *(str(page.relative_to(ROOT)) for page in c100x_pages),
        "docs/dev/c100x-device-test.md",
        "docs/dev/c100x-display-parity.md", "docs/dev/c100x-field-report.md",
        "docs/dev/c100x-audio-analysis.md",
    ):
        assert (tmp_path / relative).read_bytes() == (ROOT / relative).read_bytes()


def test_complete_archive_contains_current_card_and_device_assets(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    builder = importlib.import_module("build_hacs_release")
    stager = importlib.import_module("stage_device_agent_bundle")
    frontend = importlib.import_module("update_frontend_hashes")
    binary = tmp_path / "synthetic-agent"
    binary.write_bytes(b"offline packaging fixture, never executed")
    monkeypatch.setattr(builder, "PACKAGE_ROOT", tmp_path / "package")
    monkeypatch.setattr(builder, "stage_bundle", lambda path, **kwargs: stager.stage_bundle(
        path, **kwargs, agent_binary=binary,
    ))
    builder._prepare_package("test")
    archive = tmp_path / "c100x-test.zip"
    builder._write_zip(archive)
    with zipfile.ZipFile(archive) as zipped:
        for name in frontend.FRONTEND_MODULES:
            assert zipped.read(f"frontend/{name}") == (frontend.FRONTEND_DIR / name).read_bytes()
        assert not frontend.update_frontend_import_hashes(frontend.frontend_bundle_hash(), check=True)
        for name in ("__init__.py", "manifest.json", "frontend.py", "device_installer.py"):
            assert zipped.read(name) == (builder.COMPONENT_SRC / name).read_bytes()
        assert zipped.read("device_agent/armhf/c300x-agent-native") == binary.read_bytes()
        assert zipped.read("device_agent/qml/c100x_bundle.sh")
        for page in ("1-setup.md", "5-update-and-removal.md"):
            assert zipped.read(f"docs/classe-100x/{page}") == (ROOT / "docs/classe-100x" / page).read_bytes()
        assert zipped.read("docs/dev/c100x-device-test.md") == (ROOT / "docs/dev/c100x-device-test.md").read_bytes()
        assert "docs/c100x-experimental.md" not in zipped.namelist()
        assert "docs/c100x-test-release.md" not in zipped.namelist()
        assert zipped.read("docs/dev/c100x-audio-analysis.md") == (ROOT / "docs/dev/c100x-audio-analysis.md").read_bytes()
        manifest = json.loads(zipped.read("device_agent/bundle.json"))
        assert "c100x_only" not in manifest and manifest["c100x_compatible"] is True
        for item in manifest["files"]:
            assert zipped.read(item["path"])
        defaults = [factory_ssh_login(model)[1].encode().lower() for model in ("C100X", "C300X")]
        matches = [name for name in zipped.namelist() if not name.endswith("/")
                   and any(value in zipped.read(name).lower() for value in defaults)]
        assert not matches, f"Plaintext factory credential in archive paths: {matches}"
