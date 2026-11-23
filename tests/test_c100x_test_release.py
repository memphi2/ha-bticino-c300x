"""C100X-only local test delivery; no network or device actions."""

import asyncio
import importlib
import json
import os
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_agent_update import FakeHass, FakeUpdateApi
from test_native_agent_update_legacy_bootstrap import _compile_updater

from custom_components.bticino_c300x import agent_update, device_installer
from custom_components.bticino_c300x.factory_login import factory_ssh_login

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("model", ["C300X", "C100X", "", None])
@pytest.mark.parametrize("only", [True, False, "true", 1, None, {}])
def test_model_isolation_is_strict(model, only):
    bundle = {"c100x_compatible": True, "c100x_only": only}
    expected = isinstance(only, bool) and (not only or model == "C100X")
    assert agent_update.bundle_supports_device({"model": model}, bundle) == expected


@pytest.mark.parametrize("model", ["C300X", "", None])
def test_wrong_or_unknown_device_rejected_before_upload(monkeypatch, model):
    monkeypatch.setattr(agent_update, "async_load_packaged_bundle_metadata", AsyncMock(return_value={
        "version": "test", "bundle_hash": "sha256:test", "files": [],
        "c100x_compatible": True, "c100x_only": True,
    }))
    api = FakeUpdateApi()
    api.async_validate_setup = AsyncMock(return_value={"model": model})
    with pytest.raises(RuntimeError, match="device_model_incompatible"):
        asyncio.run(agent_update.async_apply_packaged_agent_update(FakeHass(), api))
    assert api.calls == []


@pytest.mark.parametrize("kind", ["qt4", "qt5"])
def test_c300x_ssh_refused_before_first_write(tmp_path, monkeypatch, kind):
    manifest = tmp_path / "bundle.json"
    manifest.write_text(json.dumps({"c100x_only": True, "c100x_compatible": True}))
    bundle = device_installer._ResolvedBundle((
        device_installer._PayloadFile(manifest, "/agent/bundle.json", "600"),
    ), tmp_path / "unused")
    calls = []
    client = SimpleNamespace(run=lambda cmd: calls.append(cmd), close=lambda: calls.append("closed"))
    monkeypatch.setattr(device_installer, "_connect_device_client", lambda _: client)
    monkeypatch.setattr(device_installer, "_read_remote_config_sync", lambda *_: {})
    monkeypatch.setattr(device_installer, "_device_display_kind", lambda _: kind)
    request = device_installer.C300XDeviceInstallRequest(
        host="unused.invalid", ssh_username="unused", ssh_password="unused", remote_dir="/agent",
    )
    with pytest.raises(device_installer.C300XDeviceInstallError, match="device_model_incompatible"):
        device_installer._install_device_agent_sync(request, bundle, b"{}")
    assert calls == ["closed"]


def test_explicit_c100x_gui_request_is_not_silently_ignored(tmp_path, monkeypatch):
    calls = []
    client = SimpleNamespace(run=lambda cmd: calls.append(cmd), close=lambda: calls.append("closed"))
    monkeypatch.setattr(device_installer, "_connect_device_client", lambda _: client)
    monkeypatch.setattr(device_installer, "_read_remote_config_sync", lambda *_: {})
    monkeypatch.setattr(device_installer, "_verify_c100x_bundle_sync", lambda *_: "qt5_ondisk")
    monkeypatch.setattr(device_installer, "_device_display_kind", lambda _: "qt5_ondisk")
    request = device_installer.C300XDeviceInstallRequest(
        host="unused.invalid", ssh_username="unused", ssh_password="unused", apply_gui_patch=True,
    )
    with pytest.raises(device_installer.C300XDeviceInstallError, match="device_install_verify_failed"):
        device_installer._install_device_agent_sync(
            request, device_installer._ResolvedBundle((), tmp_path / "unused"), b"{}")
    assert calls == ["closed"]


def test_native_c300x_rejects_c100x_bundle_but_c100x_accepts(tmp_path, monkeypatch):
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
    assert document["c100x_only"] is True
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
    result = subprocess.run([str(native), str(agent), str(manifest), "1"],
                            env={**env, "C100X_TEST_MODEL": "1"},
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert installed.read_bytes() == binary.read_bytes()


def test_publication_blocked_before_any_external_command(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    publisher = importlib.import_module("publish_release")
    monkeypatch.setattr(publisher, "ROOT", ROOT)
    monkeypatch.setattr(publisher, "run", lambda *_: pytest.fail("external command"))
    with pytest.raises(ValueError, match="C100X publication blocked"):
        publisher.publish("owner/repo", "v2.8.2", ROOT / ".release")


def test_builder_rejects_stable_asset_name_before_build(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    builder = importlib.import_module("build_hacs_release")
    monkeypatch.setattr(builder, "ROOT", ROOT)
    monkeypatch.setattr(builder, "_run", lambda *_a, **_k: pytest.fail("build invoked"))
    monkeypatch.setattr("sys.argv", ["builder", "--output", "/tmp/ha-bticino-c300x.zip"])
    with pytest.raises(SystemExit) as error:
        builder.main()
    assert error.value.code == 2


def test_legacy_installer_is_blocked_without_contact():
    result = subprocess.run(["bash", str(ROOT / "scripts/install_c300x_device.sh"), "--agent"],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert "legacy installer has no model guard" in result.stderr


def test_test_instructions_ship_with_the_local_package(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    builder = importlib.import_module("build_hacs_release")
    monkeypatch.setattr(builder, "PACKAGE_ROOT", tmp_path)
    builder._copy_package_metadata()
    for name in ("test-release", "experimental", "display-parity", "field-report", "audio-analysis"):
        relative = f"docs/c100x-{name}.md"
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
        assert zipped.read("docs/c100x-test-release.md") == (ROOT / "docs/c100x-test-release.md").read_bytes()
        assert zipped.read("docs/c100x-audio-analysis.md") == (ROOT / "docs/c100x-audio-analysis.md").read_bytes()
        manifest = json.loads(zipped.read("device_agent/bundle.json"))
        assert manifest["c100x_only"] is True
        for item in manifest["files"]:
            assert zipped.read(item["path"])
        defaults = [factory_ssh_login(model)[1].encode().lower() for model in ("C100X", "C300X")]
        matches = [name for name in zipped.namelist() if not name.endswith("/")
                   and any(value in zipped.read(name).lower() for value in defaults)]
        assert not matches, f"Plaintext factory credential in archive paths: {matches}"
