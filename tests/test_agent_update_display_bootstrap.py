"""Real file-set-5 updater and active QML through the HA repair, entirely offline."""

import asyncio
import io
import json
import os
import shutil
import subprocess
import tarfile
from hashlib import sha256 as digest_sha256
from pathlib import Path

import pytest
from test_agent_update_repairs import FakeEntry, FakeHass, FakePatchApi, FakeRuntimeData
from test_native_agent_update_legacy_bootstrap import _compile_updater
from test_qml_patch_script import _write_original_gui
from test_qml_patch_transactions import snapshot

from custom_components.bticino_c300x import agent_update, repairs
from custom_components.bticino_c300x.api import C300XAgentApiError
from custom_components.bticino_c300x.device_installer import DISPLAY_FILES

ROOT = Path(__file__).resolve().parents[1]
# Pin the actual 2.6 updater/display from this branch's ancestry for fresh CI clones.
FILE_SET_5_COMMIT = "e1192c7f4abfaad508f46a9add6402a5eb530856"
NEW_FILES = ("C300XChecks.qml", "C300XSituations.qml", "C300XOptionalPages.qml")


@pytest.fixture(scope="module")
def bootstrap_inputs(tmp_path_factory):
    directory = tmp_path_factory.mktemp("display-bootstrap-inputs")
    old = _compile_updater(directory, False, False, commit=FILE_SET_5_COMMIT)
    current_dir = directory / "new"
    current_dir.mkdir()
    current = _compile_updater(current_dir, False, False)
    history = directory / "history"
    archive = subprocess.run(
        ["git", "archive", FILE_SET_5_COMMIT, "device_qml", "native_agent/scripts/qml_patch.sh"],
        cwd=ROOT, check=True, capture_output=True,
    )
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as source:
        source.extractall(history, filter="data")
    return old, current, history


class TemporaryDisplayApi(FakePatchApi):
    """Replace transport/process control only; run real uploads, updater and patch scripts."""

    def __init__(self, directory, inputs, failure):
        super().__init__()
        self.directory = directory
        self.agent = directory / "agent"
        self.gui = directory / "gui"
        self.gui.mkdir()
        _write_original_gui(self.gui)
        self.stock = snapshot(self.gui)
        self.old, self.current, history = inputs
        shutil.copytree(history / "device_qml", self.agent / "qml")
        shutil.copyfile(history / "native_agent/scripts/qml_patch.sh", self.agent / "qml_patch.sh")
        self.running_file_set = 5
        self.passes = []
        self.failure = failure
        self.reload_log = directory / "reloads"
        commands = directory / "commands"
        commands.mkdir()
        # Intercept every actual script reload, not merely the API's explicit reload.
        (commands / "killall").write_text(
            '#!/bin/sh\nset -eu\n'
            '[ "$1" = BtClass ] || exit 0\n'
            'if grep -q "C300XOptionalPages {" "$C300X_QML_GUI_DIR/HomeAssistant.qml"; then\n'
            '  for name in C300XChecks.qml C300XSituations.qml C300XOptionalPages.qml; do\n'
            '    if ! cmp -s "$C300X_QML_GUI_DIR/$name" "$C300X_QML_SOURCE_DIR/$name"; then\n'
            '      echo unsafe >> "$RELOAD_LOG"\n'
            '    fi\n'
            '  done\n'
            '  echo new >> "$RELOAD_LOG"\n'
            'else\n  echo old >> "$RELOAD_LOG"\nfi\n'
        )
        (commands / "pidof").write_text("#!/bin/sh\nexit 0\n")
        for command in commands.iterdir():
            command.chmod(0o700)
        self.env = {
            **os.environ, "PATH": str(commands) + os.pathsep + os.environ["PATH"],
            "C300X_QML_GUI_DIR": str(self.gui), "C300X_QML_SOURCE_DIR": str(self.agent / "qml"),
            "C300X_QML_BACKUP_DIR": str(directory / "backups"), "C300X_QML_NO_REMOUNT": "1",
            "C300X_QML_RELOAD_GUI": "1", "C300X_QML_GUI_RELOAD_DELAY_SECONDS": "0",
            "C300X_QML_GUI_ROOT": str(directory), "C300X_QML_GUI_WRAPPER": str(directory / "no-wrapper"),
            "C300X_QML_STAGING_DIR": str(directory / "qml-stage"), "RELOAD_LOG": str(self.reload_log),
        }
        assert self.patch("apply")["patched"] is True
        self.active = snapshot(self.gui)
        self.initial_reloads = self.reload_log.read_text()
        assert self.initial_reloads == "old\n"
        assert "C300XOptionalPages" not in (self.gui / "HomeAssistant.qml").read_text()
        self.firewall_status = self.ipv6_firewall_status = {"patched": False, "state": "original"}

    def patch(self, action):
        result = subprocess.run(
            ["sh", str(self.agent / "qml_patch.sh"), action], env=self.env,
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    async def async_prepare_agent_update(self, **_kwargs):
        shutil.rmtree(self.agent / ".update", ignore_errors=True)

    async def async_upload_agent_update_chunk(self, *, path, sha256: str, mode, offset, data, final):
        target = self.agent / ".update" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        previous = target.read_bytes() if offset else b""
        assert len(previous) == offset
        target.write_bytes(previous + data)
        target.chmod(int(mode, 8))
        if final:
            assert digest_sha256(target.read_bytes()).hexdigest() == sha256

    async def async_apply_agent_update(self, **_kwargs):
        self.passes.append(self.running_file_set)
        stage = self.agent / ".update/device_agent"
        failed = self.running_file_set == 6 and self.failure is not None
        if self.running_file_set == 6:
            # A leftover retired source must be restored on rollback, removed on success.
            (self.agent / "qml/C300XEnergyDistribution.qml").write_text("retired source")
        before = {path: value for path, value in snapshot(self.agent).items() if not path.startswith(".update/")}
        if failed and self.failure != "activation":
            operation, name = self.failure.split(":")
            target = stage / "qml" / name
            if operation == "missing":
                target.unlink()
            else:
                target.write_bytes(b"corrupt")
        command = [str(self.old if self.running_file_set == 5 else self.current),
                   str(self.agent), str(stage / "bundle.json"), str(int(not failed))]
        if failed and self.failure == "activation":
            command.append("fail-activation")
        result = await asyncio.to_thread(
            subprocess.run, command, check=True, capture_output=True, text=True, timeout=10,
        )
        summary = json.loads(result.stdout)
        # Neither installation pass is allowed to change/reload the active old GUI.
        assert snapshot(self.gui) == self.active
        assert self.reload_log.read_text() == self.initial_reloads
        if failed:
            after = {path: value for path, value in snapshot(self.agent).items() if not path.startswith(".update/")}
            assert after == before
            assert not list(self.agent.rglob("*.update-backup"))
            raise C300XAgentApiError("injected completion failure")
        if self.running_file_set == 5:
            assert all(not (self.agent / "qml" / name).exists() for name in NEW_FILES)
            assert "C300XOptionalPages" in (self.agent / "qml/HomeAssistant.qml").read_text()
        else:
            assert all((self.agent / "qml" / name).is_file() for name in NEW_FILES)
            assert not (self.agent / "qml/C300XEnergyDistribution.qml").exists()
        self.running_file_set = 6  # Simulated agent restart, not a GUI restart.
        return {**summary, "restart_scheduled": True}

    async def async_validate_setup(self):
        path = self.agent / "bundle.json"
        manifest = json.loads(path.read_text()) if path.exists() else {"agent_version": "2.6.0", "bundle_hash": "old"}
        return {"version": manifest["agent_version"], "api_version": "1", "capabilities": {},
                "agent": {"bundle_hash": manifest["bundle_hash"], "self_update_supported": True,
                          "self_update_file_set_version": self.running_file_set}}

    async def async_qml_patch_status(self):
        return self.patch("status")

    async def async_apply_qml_core_patch(self):
        assert self.passes[-1] == 6
        assert all((self.agent / "qml" / name).is_file() for name in NEW_FILES)
        return self.patch("core-apply")

    async def async_apply_qml_patch(self, **_kwargs):
        return self.patch("apply")

    async def async_reload_gui(self):
        return self.patch("reload")


@pytest.mark.parametrize("failure", [None, "activation", *(
    f"{operation}:{name}" for operation in ("missing", "corrupt") for name in NEW_FILES
)])
def test_active_display_bootstrap_completes_before_gui_reload(tmp_path, monkeypatch, bootstrap_inputs, failure):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    from stage_device_agent_bundle import LEGACY_BOOTSTRAP_CONTENT, stage_bundle

    package = tmp_path / "package"
    stage_bundle(package, version="2.7.0", skip_build=True, agent_binary=ROOT / "project-versions.json")
    manifest_path = package / "device_agent/bundle.json"
    bundle = json.loads(manifest_path.read_text())
    assert bundle["update_file_set_version"] == 6
    monkeypatch.setattr(agent_update, "COMPONENT_DIR", package)
    monkeypatch.setattr(agent_update, "BUNDLE_MANIFEST", manifest_path)
    monkeypatch.setattr(repairs, "_AGENT_UPDATE_RESTART_SETTLE_SECONDS", 0)
    monkeypatch.setattr(repairs, "async_dispatcher_send", lambda *_: None)
    monkeypatch.setattr(repairs.ir, "async_delete_issue", lambda **_kwargs: None)

    async def no_mqtt(_api):
        pass

    monkeypatch.setattr(repairs, "async_migrate_legacy_mqtt_if_available", no_mqtt)
    api = TemporaryDisplayApi(tmp_path, bootstrap_inputs, failure)
    entry = FakeEntry(runtime_data=FakeRuntimeData(api))
    hass = FakeHass(entry)
    entry.runtime_data.agent_update_state = agent_update.compare_agent_bundle(
        asyncio.run(api.async_validate_setup()), bundle,
    )
    assert entry.runtime_data.agent_update_state.payload_bootstrap_required
    flow = repairs.DeviceAgentUpdateRepairFlow(hass, entry.entry_id)
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}
    flow.async_create_entry = lambda **kwargs: {"type": "create_entry", **kwargs}
    result = asyncio.run(flow.async_step_confirm({}))
    assert api.passes == [5, 6]
    if failure:
        assert result["errors"] == {"base": "update_failed"}
        assert entry.data["agent_update_payload_pending"] is True
        assert entry.data["agent_update_qml_pending"] is True
        assert snapshot(api.gui) == api.active
        assert api.reload_log.read_text() == api.initial_reloads
        asyncio.run(repairs._async_apply_repaired_agent_setup(hass, entry, asyncio.run(api.async_validate_setup())))
        assert entry.runtime_data.agent_update_state.reason == "payload_bootstrap_pending"
        api.failure = None
        result = asyncio.run(flow.async_step_confirm({}))
        assert api.passes == [5, 6, 6]
    assert result == {"type": "create_entry", "data": {}}
    assert not entry.runtime_data.agent_update_state.update_required
    assert "agent_update_payload_pending" not in entry.data
    assert "agent_update_qml_pending" not in entry.data
    assert api.reload_log.read_text().splitlines()[-1] == "new"
    assert "unsafe" not in api.reload_log.read_text()
    assert api.patch("status")["patched"] is True
    from device_file_strip import EMBEDDED_SETTINGS, strip_device_source

    for name in EMBEDDED_SETTINGS:
        assert not (api.agent / "qml" / name).exists()
        assert not (package / "device_agent/qml" / name).exists()
        assert (api.gui / name).read_text() == strip_device_source((ROOT / "device_qml" / name).read_text())
        assert (api.gui / name).stat().st_mode & 0o777 == 0o644
    for name in DISPLAY_FILES:
        assert (api.gui / name).read_bytes() == (package / "device_agent/qml" / name).read_bytes()
        assert (api.agent / "qml" / name).read_bytes() == (package / "device_agent/qml" / name).read_bytes()
    assert not (api.agent / "qml/C300XEnergyDistribution.qml").exists()
    assert not (api.gui / "C300XEnergyDistribution.qml").exists()
    assert (package / "device_agent/qml/C300XEnergyDistribution.qml").read_bytes() == LEGACY_BOOTSTRAP_CONTENT
    assert not list(api.agent.rglob("*.update-backup"))
    assert api.patch("restore-all")["state"] == "original"
    assert snapshot(api.gui) == api.stock
