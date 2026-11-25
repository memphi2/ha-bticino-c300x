"""A C300X agent takes a package without the Classe 100X display adapter."""

import json
import os
import subprocess
from pathlib import Path

import pytest
from test_native_agent_update_legacy_bootstrap import _compile_updater

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("sanitize", [False, True])
def test_a_c300x_takes_a_package_without_the_c100x_adapter(tmp_path, monkeypatch, sanitize):
    """Every release before the joint package lacks the adapter; a C300X can still go back to one."""

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
    adapter = "device_agent/qml/c100x_bundle.sh"
    assert any(item["path"] == adapter for item in manifest["files"])
    manifest["files"] = [item for item in manifest["files"] if item["path"] != adapter]
    manifest_path.write_text(json.dumps(manifest))
    (stage / adapter).unlink()
    installed = agent / "c300x-agent-native"
    installed.write_bytes(b"original")

    def apply(expected, model_env):
        result = subprocess.run(
            [str(native), str(agent), str(manifest_path), str(int(expected))],
            env={**{k: v for k, v in os.environ.items() if k != "C100X_TEST_MODEL"}, **model_env},
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, result.stderr

    # A C100X needs its adapter and refuses the package untouched.
    apply(False, {"C100X_TEST_MODEL": "1"})
    assert installed.read_bytes() == b"original"
    # A listed adapter that is missing is a broken package on every model.
    broken = {**manifest, "files": [*manifest["files"], {"path": adapter, "sha256": "0" * 64}]}
    manifest_path.write_text(json.dumps(broken))
    apply(False, {})
    assert installed.read_bytes() == b"original"
    manifest_path.write_text(json.dumps(manifest))
    apply(True, {})
    assert installed.read_bytes() == binary.read_bytes()
    assert not (agent / "qml/c100x_bundle.sh").exists()
    apply(True, {})


def _stage(stager, stage, binary, monkeypatch, payload: bytes | None = None):
    if payload is not None:
        def build(target, **_kwargs):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            return target

        monkeypatch.setattr(stager, "build_c100x_bundle", build)
    stager.stage_bundle(stage, version="test", skip_build=True, agent_binary=binary)
    return json.loads((stage / "device_agent/bundle.json").read_text())


@pytest.mark.parametrize("sanitize", [False, True])
def test_a_changed_adapter_is_no_display_change_and_stays_off_a_c300x(tmp_path, monkeypatch, sanitize):
    """A new C100X adapter alone must not make a C300X re-patch and restart its display."""

    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import stage_device_agent_bundle as stager

    native = _compile_updater(tmp_path, False, sanitize)
    binary = tmp_path / "synthetic-binary"
    binary.write_bytes(b"synthetic payload, never executed")
    adapter = "device_agent/qml/c100x_bundle.sh"

    def apply(agent, model_env):
        result = subprocess.run(
            [str(native), str(agent), str(agent / ".update/device_agent/bundle.json"), "1"],
            env={**{k: v for k, v in os.environ.items() if k != "C100X_TEST_MODEL"}, **model_env},
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    for model_env in ({}, {"C100X_TEST_MODEL": "1"}):
        agent = tmp_path / ("c100x" if model_env else "c300x")
        first = _stage(stager, agent / ".update", binary, monkeypatch, b"#!/bin/sh\n# adapter one\n")
        assert apply(agent, model_env)["changed_files"] > 0
        second = _stage(stager, agent / ".update", binary, monkeypatch, b"#!/bin/sh\n# adapter two\n")
        # The adapter is in the package and in its hash, but in no group.
        assert first["bundle_hash"] != second["bundle_hash"]
        for group in ("qml_patch_hash", "script_hash", "runtime_hash"):
            assert first[group] == second[group], group
        assert any(item["path"] == adapter for item in second["files"])
        changed = apply(agent, model_env)
        # runtime_changed is not read here: the harness is not the staged binary.
        assert (changed["qml_patch_changed"], changed["script_changed"]) == (False, False)
        installed = agent / "qml/c100x_bundle.sh"
        if model_env:
            assert installed.read_bytes() == b"#!/bin/sh\n# adapter two\n"
            assert changed["changed_files"] == 2
        else:
            # A Classe 300X never gets the file; only the manifest is new.
            assert not installed.exists()
            assert (changed["changed_files"], changed["manifest_changed"]) == (1, True)
        assert apply(agent, model_env)["changed_files"] == 0
        assert not list(agent.rglob("*.update-backup"))


@pytest.mark.parametrize("kind", ["qt4_ondisk", "qt5_rcc", "qt5_ondisk"])
def test_the_ssh_installer_uploads_the_adapter_to_a_c100x_only(tmp_path, monkeypatch, kind):
    from types import SimpleNamespace

    from custom_components.bticino_c300x import device_installer as installer

    remote = "/agent"
    sources = {}
    for name in ("c300x-agent-native", "qml/c100x_bundle.sh", "qml/HomeAssistant.qml"):
        sources[name] = tmp_path / name.replace("/", "_")
        sources[name].write_bytes(b"x")
    bundle = installer._ResolvedBundle(
        tuple(installer._PayloadFile(path, f"{remote}/{name}", "700") for name, path in sources.items()),
        tmp_path / "unused-init",
    )
    uploaded = []
    client = SimpleNamespace(run=lambda _c: "", close=lambda: None,
                             put_file=lambda _s, target, _m: uploaded.append(target) or True)
    monkeypatch.setattr(installer, "_connect_device_client", lambda _r: client)
    monkeypatch.setattr(installer, "_admit_station_sync", lambda *_a: kind)
    monkeypatch.setattr(installer, "_read_remote_config_sync", lambda *_a: {})
    monkeypatch.setattr(installer, "_write_remote_file_sync", lambda *_a, **_k: False)
    monkeypatch.setattr(installer, "_install_startup_script_sync", lambda *_a: [])
    monkeypatch.setattr(installer, "_verify_startup_sync", lambda *_a: None)
    monkeypatch.setattr(installer, "_apply_qml_patch_sync", lambda *_a: True)
    monkeypatch.setattr(installer, "_remove_obsolete_display_source_sync", lambda *_a: None)
    request = installer.C300XDeviceInstallRequest(
        host="unused", ssh_username="unused", ssh_password="unused", remote_dir=remote,
        apply_gui_patch=False, apply_firewall_patch=False, c100x_confirmed=True,
    )
    installer._install_device_agent_sync(request, bundle, b"{}")
    assert f"{remote}/qml/HomeAssistant.qml" in uploaded and f"{remote}/c300x-agent-native" in uploaded
    assert (f"{remote}/qml/c100x_bundle.sh" in uploaded) is (kind == "qt5_ondisk")
