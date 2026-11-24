"""C100X package guards exercise real metadata and temporary-directory updates."""

import asyncio
import json
import os
import subprocess
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_agent_update import FakeHass, FakeUpdateApi
from test_native_agent_update_legacy_bootstrap import _compile_updater

from custom_components.bticino_c300x import agent_update, device_installer, repairs

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("flag", [None, False, "true", 1, {}, []])
def test_known_c100x_never_offers_incompatible_bundle_repair(flag):
    bundle = {"version": "same", "bundle_hash": "sha256:same", "c100x_compatible": flag}
    state = agent_update.compare_agent_bundle({
        "model": "C100X", "version": "same",
        "agent": {"bundle_hash": "sha256:same", "self_update_supported": True},
    }, bundle)
    assert state.reason == "device_model_incompatible"
    assert state.update_required and not state.repair_fixable
    assert not state.self_update_repair_supported
    assert "blocked" in state.repair_placeholders["update_path"]
    entry = SimpleNamespace(runtime_data=SimpleNamespace(agent_update_state=state))
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_get_entry=lambda _: entry))
    flow = repairs.DeviceAgentUpdateRepairFlow(hass, "synthetic")
    flow.async_abort = lambda **kwargs: kwargs
    assert asyncio.run(flow.async_step_confirm({}))["reason"] == "device_model_incompatible"
    assert asyncio.run(flow.async_step_ssh_install({}))["reason"] == "device_model_incompatible"


def test_api_preflight_rejects_before_any_upload(monkeypatch):
    monkeypatch.setattr(agent_update, "async_load_packaged_bundle_metadata", AsyncMock(return_value={
        "version": "same", "bundle_hash": "sha256:synthetic", "files": [],
    }))
    api = FakeUpdateApi()
    api.async_validate_setup = AsyncMock(return_value={"model": "C100X"})
    with pytest.raises(RuntimeError, match="device_model_incompatible"):
        asyncio.run(agent_update.async_apply_packaged_agent_update(FakeHass(), api))
    assert api.calls == []


@pytest.mark.parametrize("variant", ["missing", "invalid", "unmarked", "wrong-binary", "compatible"])
def test_ssh_guard_before_first_write_and_successful_retry(tmp_path, monkeypatch, variant):
    source = tmp_path / "bundle.json"
    binary = tmp_path / "binary"
    binary.write_bytes(b"synthetic never executed")
    remote_dir = "/synthetic-agent"
    manifest = {
        "c100x_only": True,
        "c100x_compatible": variant not in {"unmarked", "missing"},
        "files": [{"path": "device_agent/armhf/c300x-agent-native",
                   "sha256": sha256(binary.read_bytes()).hexdigest()}],
    }
    source.write_text("not-json" if variant == "invalid" else json.dumps(manifest))
    if variant == "wrong-binary":
        binary.write_bytes(b"another binary")
    payloads = [device_installer._PayloadFile(binary, f"{remote_dir}/c300x-agent-native", "700")]
    if variant != "missing":
        payloads.append(device_installer._PayloadFile(source, f"{remote_dir}/bundle.json", "600"))
    bundle = device_installer._ResolvedBundle(tuple(payloads), tmp_path / "unused-init")
    commands = []

    # Allow only the read-only stock-hook probe, not an arbitrary shell conditional.
    hook = device_installer.REMOTE_FIREWALL_PATH
    hook_probe = (
        f"p={hook.rpartition('/')[0]}; "
        'while [ "$p" != / ]; do '
        'if [ -L "$p" ] || { [ -e "$p" ] && { [ ! -d "$p" ] || [ ! -x "$p" ]; }; }; '
        'then printf unsupported; exit 0; fi; p=${p%/*}; p=${p:-/}; done; '
        f"if [ -L {hook} ]; then printf unsupported; "
        f"elif [ -f {hook} ] && [ -r {hook} ] && [ -x {hook} ]; then :; "
        f"elif [ ! -e {hook} ]; then printf absent; else printf unsupported; fi"
    )

    def first_write(command):
        commands.append(command)
        if command == hook_probe:
            return ""
        raise RuntimeError("reached first write")

    client = SimpleNamespace(run=first_write, close=lambda: commands.append("closed"))
    monkeypatch.setattr(device_installer, "_connect_device_client", lambda _: client)
    monkeypatch.setattr(device_installer, "_read_remote_config_sync", lambda *_: {})
    monkeypatch.setattr(device_installer, "_device_display_kind", lambda _: "qt5_ondisk")
    request = device_installer.C300XDeviceInstallRequest(
        host="unused.invalid", ssh_username="unused", ssh_password="unused", remote_dir=remote_dir,
    )
    if variant != "compatible":
        with pytest.raises(device_installer.C300XDeviceInstallError, match="device_model_incompatible"):
            device_installer._install_device_agent_sync(request, bundle, b"{}")
        assert commands == ["closed"]
    else:
        with pytest.raises(RuntimeError, match="reached first write"):
            device_installer._install_device_agent_sync(request, bundle, b"{}")
        assert commands == [hook_probe, f"mkdir -p {remote_dir}", "closed"]


@pytest.mark.parametrize("sanitize", [False, True])
def test_c100x_native_apply_rejects_unmarked_then_accepts_verified_package(tmp_path, monkeypatch, sanitize):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import stage_device_agent_bundle as stager

    native = _compile_updater(tmp_path, False, sanitize)
    agent = tmp_path / "agent"
    stage = agent / ".update"
    binary = tmp_path / "synthetic-binary"
    binary.write_bytes(b"synthetic payload, never executed")
    stager.stage_bundle(stage, version="test", skip_build=True, agent_binary=binary)
    manifest_path = stage / "device_agent/bundle.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["c100x_compatible"] is True
    marked_hash = manifest["bundle_hash"]
    monkeypatch.setattr(stager, "C100X_COMPATIBLE", False)
    stager.stage_bundle(stage, version="test", skip_build=True, agent_binary=binary)
    assert json.loads(manifest_path.read_text())["bundle_hash"] != marked_hash
    installed = agent / "c300x-agent-native"
    installed.write_bytes(b"original")

    def apply(expected):
        result = subprocess.run(
            [str(native), str(agent), str(manifest_path), str(int(expected))],
            env={**os.environ, "C100X_TEST_MODEL": "1"},
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, result.stderr

    # Both an explicit exclusion and a legacy package without the declaration fail.
    apply(False)
    unmarked = {key: value for key, value in manifest.items() if key != "c100x_compatible"}
    manifest_path.write_text(json.dumps(unmarked))
    apply(False)
    assert installed.read_bytes() == b"original"
    assert not (agent / "bundle.json").exists()
    assert not (agent / "init-script").exists()
    assert not list(agent.rglob("*.update-backup"))
    manifest_path.write_text(json.dumps(manifest))
    apply(True)
    assert installed.read_bytes() == binary.read_bytes()
    assert json.loads((agent / "bundle.json").read_text())["c100x_compatible"] is True
    apply(True)
    assert not list(agent.rglob("*.update-backup"))


@pytest.mark.parametrize("model", ["C300X", "C100X"])
def test_c300x_entry_is_told_to_use_the_regular_package(monkeypatch, model):
    from custom_components.bticino_c300x import repair_issues

    bundle = {"version": "new", "bundle_hash": "sha256:new", "c100x_only": True,
              "c100x_compatible": model == "C300X"}
    state = agent_update.compare_agent_bundle({
        "model": model, "version": "old",
        "agent": {"bundle_hash": "sha256:old", "self_update_supported": True},
    }, bundle)
    assert state.reason == "device_model_incompatible"
    advice = state.repair_placeholders["update_path"]
    issues = []
    monkeypatch.setattr(repair_issues.ir, "async_create_issue", lambda **kw: issues.append(kw))
    entry = SimpleNamespace(entry_id="e", title="Station", runtime_data=SimpleNamespace(
        agent_update_state=state, qml_patch_status={},
    ))
    repair_issues._sync_device_agent_update_issue(None, entry)
    issue, = issues
    assert issue["is_fixable"] is False
    if model == "C100X":
        assert advice == "blocked: install a C100X-compatible integration package"
        assert issue["translation_key"] == "device_agent_update_required"
        return
    assert advice == "blocked: install the regular release package"
    assert issue["translation_key"] == "device_agent_update_regular_package"
    for name in ("strings.json", "translations/en.json", "translations/de.json",
                 "translations/it.json", "translations/fr.json"):
        texts = json.loads((ROOT / "custom_components/bticino_c300x" / name).read_text())
        text = texts["issues"]["device_agent_update_regular_package"]["description"]
        assert "{entry_title}" in text and "C100X" in text
