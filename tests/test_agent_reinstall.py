"""Lost agent keys: the SSH installer writes the agent again with new ones."""

import asyncio
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.bticino_c300x import (
    config_flow,
    config_flow_auth,
    config_flow_reinstall,
    device_installer,
)
from custom_components.bticino_c300x.config_flow import BticinoC300XConfigFlow
from custom_components.bticino_c300x.const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_BOOTSTRAP_SSH_PASSWORD,
    CONF_BOOTSTRAP_SSH_USERNAME,
    CONF_DEVICE_ACTIVATION_MODE,
    CONF_DISPLAY_FOLLOWUP_PENDING,
    CONF_MAINTENANCE_TOKEN,
    CONF_REINSTALL_AGENT,
)
from custom_components.bticino_c300x.device_installer import (
    DEFAULT_REMOTE_DIR,
    C300XDeviceInstallError,
    C300XDeviceInstallRequest,
)
from tests.test_agent_init_script import _alive, _device_init, _reap_all, _wait_started

ROOT = Path(__file__).resolve().parents[1]
TEXTS = ROOT / "custom_components/bticino_c300x"


def _setup_flow(needs_token: bool) -> BticinoC300XConfigFlow:
    flow = BticinoC300XConfigFlow()
    flow.hass = SimpleNamespace()
    flow.context = {"source": "user"}
    flow._setup_connection = {"name": "Door", CONF_AGENT_HOST: "a.local", CONF_AGENT_PORT: 8091}
    flow._setup_agent_needs_token = needs_token
    flow._async_abort_if_manual_setup_duplicate = AsyncMock()
    flow._async_adopt_agent_unique_id = AsyncMock()
    return flow


def _fields(result) -> dict[str, object]:
    return {str(key): key for key in result["data_schema"].schema}


def test_an_agent_that_asks_for_a_key_offers_the_reinstall():
    form = asyncio.run(_setup_flow(True).async_step_agent_auth())
    fields = _fields(form)
    assert form["step_id"] == "agent_auth"
    assert list(fields) == [CONF_AGENT_TOKEN, CONF_MAINTENANCE_TOKEN, CONF_REINSTALL_AGENT]
    # A form with a required empty field cannot be sent from the dialog.
    assert form["data_schema"]({CONF_REINSTALL_AGENT: True})[CONF_REINSTALL_AGENT] is True
    assert form["data_schema"]({})[CONF_REINSTALL_AGENT] is False


def test_an_agent_without_a_key_shows_the_form_as_before():
    form = asyncio.run(_setup_flow(False).async_step_agent_auth())
    assert list(_fields(form)) == [CONF_AGENT_TOKEN, CONF_MAINTENANCE_TOKEN]


def test_the_access_key_is_still_asked_for_without_the_reinstall(monkeypatch):
    flow = _setup_flow(True)
    validate = AsyncMock()
    monkeypatch.setattr(config_flow_auth, "async_validate_connection", validate)
    result = asyncio.run(flow.async_step_agent_auth({CONF_AGENT_TOKEN: "", CONF_REINSTALL_AGENT: False}))
    assert result["step_id"] == "agent_auth"
    assert result["errors"] == {CONF_AGENT_TOKEN: "required"}
    validate.assert_not_called()


def test_setup_without_the_keys_installs_the_agent_with_new_ones(monkeypatch):
    flow = _setup_flow(True)
    installer = AsyncMock(return_value=SimpleNamespace(display_pending=False, display_kind="qt4_ondisk"))
    probe = AsyncMock(return_value="reachable")
    monkeypatch.setattr(config_flow, "async_ensure_installer_dependencies", AsyncMock())
    monkeypatch.setattr(config_flow, "async_install_device_agent", installer)
    monkeypatch.setattr(config_flow, "_async_probe_agent", probe)
    monkeypatch.setattr(config_flow, "async_migrate_legacy_mqtt_for_connection", AsyncMock())
    result = asyncio.run(flow.async_step_agent_auth({CONF_AGENT_TOKEN: "", CONF_REINSTALL_AGENT: True}))
    assert result["step_id"] == "user_features"
    request = installer.await_args.args[0]
    keys = installer.await_args.kwargs
    # The factory login first; nothing typed, nothing stored.
    assert request.factory_login is True and request.host == "a.local"
    assert len(keys["api_token"]) >= 32 and keys["api_token"] != keys["maintenance_token"]
    assert flow._setup_connection[CONF_AGENT_TOKEN] == keys["api_token"]
    assert flow._setup_connection[CONF_MAINTENANCE_TOKEN] == keys["maintenance_token"]
    assert probe.await_args.kwargs["api_token"] == keys["api_token"]
    assert CONF_REINSTALL_AGENT not in flow._setup_connection


def test_setup_reinstall_asks_for_the_ssh_login_once_the_factory_login_is_refused(monkeypatch):
    flow = _setup_flow(True)
    installer = AsyncMock(side_effect=C300XDeviceInstallError("ssh_login_refused"))
    monkeypatch.setattr(config_flow, "async_ensure_installer_dependencies", AsyncMock())
    monkeypatch.setattr(config_flow, "async_install_device_agent", installer)
    result = asyncio.run(flow.async_step_agent_auth({CONF_REINSTALL_AGENT: True}))
    assert result["step_id"] == "bootstrap_install"
    assert result["errors"] == {"base": "ssh_login_refused"}
    assert CONF_AGENT_TOKEN not in flow._setup_connection


def test_setup_reinstall_of_a_classe_100x_asks_for_its_confirmation_first(monkeypatch):
    flow = _setup_flow(True)
    installer = AsyncMock(side_effect=C300XDeviceInstallError("c100x_confirmation_required"))
    monkeypatch.setattr(config_flow, "async_ensure_installer_dependencies", AsyncMock())
    monkeypatch.setattr(config_flow, "async_install_device_agent", installer)
    result = asyncio.run(flow.async_step_agent_auth({CONF_REINSTALL_AGENT: True}))
    assert result["step_id"] == "c100x_experimental"
    assert installer.await_args.args[0].c100x_confirmed is False


def _entry(**data):
    return SimpleNamespace(
        data={CONF_AGENT_HOST: "c300x.local", CONF_AGENT_PORT: 8091, CONF_AGENT_TOKEN: "lost",
              CONF_MAINTENANCE_TOKEN: "lost-too", "shared_secret": "keep", **data},
        options={CONF_AGENT_TOKEN: "shadow", CONF_DEVICE_ACTIVATION_MODE: "manual"},
        unique_id="bticino_c300x:c300x.local:8091", entry_id="entry", title="Door",
        update_listeners=[], runtime_data=None,
    )


def _reauth_flow(existing):
    flow = BticinoC300XConfigFlow()
    flow.context = {"source": "reauth", "entry_id": "entry"}
    flow._get_reauth_entry = lambda: existing
    flow.hass = SimpleNamespace(config_entries=SimpleNamespace(async_schedule_reload=Mock()))
    flow.async_update_and_abort = Mock(return_value={"type": "abort", "reason": "reauth_successful"})
    return flow


def _reinstall(monkeypatch, flow, installer, user_input=None, first=True):
    monkeypatch.setattr(config_flow_reinstall, "async_ensure_installer_dependencies", AsyncMock())
    monkeypatch.setattr(config_flow_reinstall, "async_install_device_agent", installer)
    validate = AsyncMock(return_value=({}, {}))
    monkeypatch.setattr(config_flow_auth, "async_validate_connection", validate)
    if first:
        return asyncio.run(flow.async_step_reauth_confirm({CONF_REINSTALL_AGENT: True})), validate
    return asyncio.run(flow.async_step_reauth_reinstall(user_input)), validate


def test_reauth_offers_the_reinstall():
    existing = _entry()
    form = asyncio.run(_reauth_flow(existing).async_step_reauth_confirm())
    assert list(_fields(form)) == [CONF_AGENT_TOKEN, CONF_MAINTENANCE_TOKEN, CONF_REINSTALL_AGENT]


def test_reauth_reinstall_stores_the_new_keys_in_the_entry(monkeypatch):
    existing = _entry()
    flow = _reauth_flow(existing)
    installer = AsyncMock(return_value=SimpleNamespace(display_pending=False))
    result, _ = _reinstall(monkeypatch, flow, installer)
    assert result["reason"] == "reauth_successful"
    request, keys = installer.await_args.args[0], installer.await_args.kwargs
    assert request.host == "c300x.local" and request.agent_port == 8091
    assert request.factory_login is True and request.c100x_confirmed is True
    assert request.device_activation_mode == "manual" and request.apply_gui_patch is False
    assert "lost" not in (keys["api_token"], keys["maintenance_token"])
    saved = flow.async_update_and_abort.call_args.kwargs
    assert saved["data_updates"] == {
        CONF_AGENT_TOKEN: keys["api_token"], CONF_MAINTENANCE_TOKEN: keys["maintenance_token"],
    }
    assert saved["options"] == {CONF_DEVICE_ACTIVATION_MODE: "manual"}
    flow.hass.config_entries.async_schedule_reload.assert_called_once_with("entry")


def test_reauth_reinstall_records_a_display_step_the_install_owes(monkeypatch):
    flow = _reauth_flow(_entry())
    result, _ = _reinstall(monkeypatch, flow, AsyncMock(return_value=SimpleNamespace(display_pending=True)))
    assert result["reason"] == "reauth_successful"
    assert flow.async_update_and_abort.call_args.kwargs["data_updates"][CONF_DISPLAY_FOLLOWUP_PENDING] is False


def test_reauth_reinstall_asks_for_the_ssh_login_once_the_factory_login_is_refused(monkeypatch):
    flow = _reauth_flow(_entry())
    installer = AsyncMock(side_effect=C300XDeviceInstallError("ssh_login_refused"))
    result, _ = _reinstall(monkeypatch, flow, installer)
    assert result["step_id"] == "reauth_reinstall"
    assert result["errors"] == {"base": "ssh_login_refused"}
    assert result["description_placeholders"]["name"] == "Door"
    flow.async_update_and_abort.assert_not_called()
    installer.side_effect = None
    installer.return_value = SimpleNamespace(display_pending=False)
    typed = {CONF_BOOTSTRAP_SSH_USERNAME: "ssh-user", CONF_BOOTSTRAP_SSH_PASSWORD: "ssh-secret"}
    result, _ = _reinstall(monkeypatch, flow, installer, user_input=typed, first=False)
    assert result["reason"] == "reauth_successful"
    request = installer.await_args.args[0]
    assert (request.ssh_username, request.ssh_password, request.factory_login) == ("ssh-user", "ssh-secret", False)
    assert "ssh-secret" not in str(flow.async_update_and_abort.call_args)


def test_reauth_reinstall_asks_the_station_nothing_after_the_install(monkeypatch):
    flow = _reauth_flow(_entry())
    installer = AsyncMock(return_value=SimpleNamespace(display_pending=False))
    result, validate = _reinstall(monkeypatch, flow, installer)
    assert result["reason"] == "reauth_successful"
    validate.assert_not_called()


def test_reauth_reinstall_saves_no_keys_for_an_entry_moved_meanwhile(monkeypatch):
    existing = _entry()
    flow = _reauth_flow(existing)

    async def install(*_args, **_kwargs):
        existing.data = {**existing.data, CONF_AGENT_HOST: "elsewhere.local"}
        return SimpleNamespace(display_pending=False)

    result, _ = _reinstall(monkeypatch, flow, AsyncMock(side_effect=install))
    assert result["reason"] == "reauth_wrong_device"
    flow.async_update_and_abort.assert_not_called()


def test_reauth_with_keys_is_as_before(monkeypatch):
    flow = _reauth_flow(_entry())
    installer = AsyncMock()
    monkeypatch.setattr(config_flow_reinstall, "async_install_device_agent", installer)
    monkeypatch.setattr(config_flow_auth, "async_validate_connection", AsyncMock(return_value=({}, {})))
    result = asyncio.run(flow.async_step_reauth_confirm({CONF_AGENT_TOKEN: "new", CONF_REINSTALL_AGENT: False}))
    assert result["reason"] == "reauth_successful"
    assert flow.async_update_and_abort.call_args.kwargs["data_updates"][CONF_AGENT_TOKEN] == "new"
    installer.assert_not_called()


@pytest.mark.parametrize("language", ["en", "de", "fr", "it", "es"])
def test_the_reinstall_texts_exist(language):
    steps = json.loads((TEXTS / f"translations/{language}.json").read_text())["config"]["step"]
    for step in ("agent_auth", "reauth_confirm"):
        assert steps[step]["data"][CONF_REINSTALL_AGENT]
        assert steps[step]["data_description"][CONF_REINSTALL_AGENT]
    assert steps["reauth_reinstall"]["data"].keys() == {CONF_BOOTSTRAP_SSH_USERNAME, CONF_BOOTSTRAP_SSH_PASSWORD}
    assert "{name}" in steps["reauth_reinstall"]["description"]


# The installer.


class _Station:
    """The station as the installer sees it; records the order of its steps."""

    last: _Station

    def __init__(self, existing: dict | None, fail: str = "") -> None:
        self.existing = existing
        self.steps: list[str] = []
        self.config: bytes | None = None
        self.fail = fail
        _Station.last = self

    def run(self, command: str, input_data: bytes | None = None) -> str:
        output = self._run(command, input_data)
        if self.steps and self.steps[-1] == self.fail:
            self.fail = ""
            raise C300XDeviceInstallError("device_install_failed")
        return output

    def _run(self, command: str, input_data: bytes | None) -> str:
        if command.startswith("if [ -e "):
            return "M" if self.existing is None else "F" + json.dumps(self.existing)
        if command.startswith("sh -s stop"):
            # The bundled init script stops the agent, not the one on the station.
            assert input_data and input_data.startswith(b"#!/bin/sh")
            self.steps.append("stop")
            assert "killall" not in command and "pkill" not in command and "bt_" not in command
        elif command.endswith(" restart"):
            self.steps.append("restart")
        elif command.endswith(" start; fi"):
            self.steps.append("start")
        elif input_data and b'"adminToken"' in input_data:
            self.steps.append("config")
            self.config = input_data
        elif "qml_patch.sh " in command:
            return json.dumps({"ok": True, "core_patched": True, "gui_running": True, "patched": False})
        return ""

    def put_file(self, source: Path, remote_path: str, mode: str | None = None) -> bool:
        return True

    def close(self) -> None:
        pass


def _install(monkeypatch, tmp_path, existing, api="new-access", maintenance="new-maintenance", fail=""):
    station = _Station(existing, fail)
    init_script = tmp_path / "c300x-native-agent"
    init_script.write_text(f'#!/bin/sh\nDEFAULT_AGENT_DIR="{DEFAULT_REMOTE_DIR}"\n', encoding="utf-8")
    monkeypatch.setattr(device_installer, "_admit_station_sync", lambda *_: "qt4_ondisk")
    monkeypatch.setattr(device_installer, "_connect_device_client", lambda _r: station)
    monkeypatch.setattr(device_installer, "_verify_startup_sync", lambda _c: None)
    config = device_installer._device_config_json(
        api_token=api, maintenance_token=maintenance, agent_port=8091,
    ).encode()
    device_installer._install_device_agent_sync(
        C300XDeviceInstallRequest(
            host="c300x.local", ssh_username="root", ssh_password="secret", apply_firewall_patch=False,
        ),
        device_installer._ResolvedBundle((), init_script), config,
    )
    return station


def _installed(api: str, maintenance: str) -> dict:
    return {
        "api": {"token": api, "noAuth": False},
        "maintenance": {"adminToken": maintenance},
        "mqtt": {"enabled": True, "host": "broker.lan"},
    }


@pytest.mark.parametrize("old", [("old-access", "old-maintenance"), ("new-access", "old-maintenance"),
                                 ("old-access", "new-maintenance")])
def test_an_agent_with_other_keys_is_stopped_before_its_keys_are_replaced(monkeypatch, tmp_path, old):
    station = _install(monkeypatch, tmp_path, _installed(*old))
    assert station.steps == ["stop", "config", "restart"]
    written = json.loads(station.config)
    assert written["api"]["token"] == "new-access"
    assert written["maintenance"]["adminToken"] == "new-maintenance"
    assert "old-" not in station.config.decode()
    # What the station set up itself stays.
    assert written["mqtt"] == {"enabled": True, "host": "broker.lan"}


@pytest.mark.parametrize("existing", [None, _installed("new-access", "new-maintenance")])
def test_an_install_that_replaces_no_keys_runs_as_before(monkeypatch, tmp_path, existing):
    station = _install(monkeypatch, tmp_path, existing)
    assert station.steps == ["config", "restart"]


@pytest.mark.parametrize("failing", ["stop", "config", "restart"])
def test_an_install_that_fails_after_the_stop_starts_the_agent_again(monkeypatch, tmp_path, failing):
    with pytest.raises(C300XDeviceInstallError):
        _install(monkeypatch, tmp_path, _installed("old-access", "old-maintenance"), fail=failing)
    station = _Station.last
    # Whatever configuration the station holds now, an agent runs with it.
    assert station.steps[-1] == "start" and station.steps.count("start") == 1


def test_an_install_that_fails_before_any_stop_starts_nothing(monkeypatch, tmp_path):
    with pytest.raises(C300XDeviceInstallError):
        _install(monkeypatch, tmp_path, _installed("new-access", "new-maintenance"), fail="config")
    assert _Station.last.steps == ["config"]


class _Shell:
    def __init__(self, env: dict[str, str]) -> None:
        self.env = env

    def run(self, command: str, input_data: bytes | None = None) -> str:
        result = subprocess.run(["sh", "-c", command], input=input_data or b"", capture_output=True,
                                check=False, env=self.env, timeout=120)
        if result.returncode:
            raise C300XDeviceInstallError("device_install_failed")
        return result.stdout.decode()

    def put_file(self, source: Path, remote_path: str, mode: str | None = None) -> bool:
        raise AssertionError("no payload in these tests")

    def close(self) -> None:
        pass


def _station_shell(tmp_path: Path, log: Path, port: int) -> _Shell:
    """The station's busybox shell runs the commands, as over SSH."""
    return _Shell({**os.environ, "PATH": f"{tmp_path / 'commands'}:{os.environ['PATH']}",
                   "C300X_AGENT_DIR": str(tmp_path), "C300X_AGENT_ENV": str(tmp_path / "absent"),
                   "STUB_LOG": str(log), "STUB_PORT": str(port)})


def test_the_running_agent_is_stopped_by_the_bundled_init_script_on_the_station_busybox(tmp_path):
    run, log, pidfile, port = _device_init(tmp_path)
    config = tmp_path / "config.json"
    leftovers = [tmp_path / "config.json.tmp.Ab12Cd", tmp_path / "config.json.c300x-0011223344556677.new"]
    bystander = subprocess.Popen(["sleep", "300"])
    try:
        assert run("start").returncode == 0
        agent = _wait_started(pidfile, log)
        for leftover in leftovers:
            leftover.write_text('{"api": {"token": "old-access"}}')
        device_installer._retire_old_keys_sync(
            _station_shell(tmp_path, log, port), str(tmp_path), (tmp_path / "init").read_bytes(),
        )
        assert not _alive(agent) and not pidfile.exists()
        assert f"stopped {agent}" in log.read_text()
        assert not any(leftover.exists() for leftover in leftovers)
        # Only the agent and the unfinished copies of its configuration.
        assert config.exists() and bystander.poll() is None
    finally:
        bystander.kill()
        bystander.wait()
        _reap_all(tmp_path)


def test_an_agent_that_cannot_be_stopped_keeps_its_configuration(tmp_path):
    leftover = tmp_path / "config.json.tmp.Ab12Cd"
    leftover.write_text("{}")
    with pytest.raises(C300XDeviceInstallError):
        device_installer._retire_old_keys_sync(_Shell(dict(os.environ)), str(tmp_path), b"#!/bin/sh\nexit 1\n")
    assert leftover.exists()


def test_a_station_without_a_running_agent_only_loses_the_unfinished_copies(tmp_path):
    _run, log, _pidfile, port = _device_init(tmp_path)
    leftover = tmp_path / "config.json.tmp.Ab12Cd"
    leftover.write_text("{}")
    device_installer._retire_old_keys_sync(
        _station_shell(tmp_path, log, port), str(tmp_path), (tmp_path / "init").read_bytes(),
    )
    assert not leftover.exists() and (tmp_path / "config.json").exists()


# The init script of 2.9.0 and older stops whatever PID its PID file names.
INIT_2_9_0 = """#!/bin/sh
PATH=/sbin:/usr/sbin:/bin:/usr/bin
DEFAULT_AGENT_DIR="/home/bticino/cfg/extra/c300x-native-agent"
AGENT_ENV="${C300X_AGENT_ENV:-$DEFAULT_AGENT_DIR/c300x-agent.env}"
[ -r "$AGENT_ENV" ] && . "$AGENT_ENV"
AGENT_DIR="${C300X_AGENT_DIR:-${AGENT_DIR:-$DEFAULT_AGENT_DIR}}"
AGENT_BIN="$AGENT_DIR/c300x-agent-native"
AGENT_CONFIG="$AGENT_DIR/config.json"
AGENT_PID="$AGENT_DIR/c300x-agent-native.pid"
case "$1" in
    start)
        start-stop-daemon --start --quiet --oknodo --background \\
            --make-pidfile --pidfile "$AGENT_PID" \\
            --exec "$AGENT_BIN" -- --config "$AGENT_CONFIG"
        exit $?
        ;;
    stop)
        start-stop-daemon --stop --quiet --oknodo \\
            --pidfile "$AGENT_PID" --retry=TERM/3/KILL/2 || exit $?
        rm -f "$AGENT_PID" || exit $?
        ;;
    status)
        if [ -f "$AGENT_PID" ] && kill -0 "$(cat "$AGENT_PID")" >/dev/null 2>&1; then
            exit 0
        fi
        exit 3
        ;;
esac
exit 0
"""


def test_a_reinstall_over_an_old_init_script_never_signals_a_stale_pid(tmp_path, monkeypatch):
    import shutil

    from tests.test_agent_init_script import SCRIPT

    run, log, pidfile, port = _device_init(tmp_path, INIT_2_9_0)
    commands = tmp_path / "commands"
    bundled = tmp_path / "bundled-init"
    bundled.write_text(SCRIPT.read_text().replace(
        "[ -f /etc/init.d/functions ] && . /etc/init.d/functions", "").replace(
        "#!/bin/sh", f"#!{commands}/sh", 1).replace(
        "PATH=/sbin:/usr/sbin:/bin:/usr/bin", f"PATH={commands}:/bin:/usr/bin"))
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    (stubs / "mount").write_text("#!/bin/sh\nexit 0\n")
    (stubs / "mount").chmod(0o700)
    (tmp_path / "config.json").write_text(json.dumps(_installed("old-access", "old-maintenance")))
    env = {**os.environ, "PATH": f"{stubs}:{os.environ['PATH']}", "C300X_AGENT_DIR": str(tmp_path),
           "C300X_AGENT_ENV": str(tmp_path / "absent"), "STUB_LOG": str(log), "STUB_PORT": str(port)}
    monkeypatch.setattr(device_installer, "REMOTE_INIT_SCRIPT", str(tmp_path / "init"))
    monkeypatch.setattr(device_installer, "REMOTE_INIT_LINK", str(tmp_path / "S40c300x-native-agent"))
    monkeypatch.setattr(device_installer, "_admit_station_sync", lambda *_: "qt4_ondisk")
    monkeypatch.setattr(device_installer, "_display_actions", lambda *_: ())
    monkeypatch.setattr(device_installer, "_connect_device_client", lambda _r: _Shell(env))
    # A program with a name of its own: the agent stopped long ago, its PID is
    # someone else's now (on the station possibly a watched bt_* process).
    stand_in = tmp_path / "c300x-reinstall-bystander"
    (tmp_path / "bystander.c").write_text("#include <unistd.h>\nint main(void) { for (;;) pause(); }\n")
    subprocess.run([shutil.which("cc"), "-o", str(stand_in), str(tmp_path / "bystander.c")], check=True)
    bystander = subprocess.Popen([str(stand_in)])
    try:
        pidfile.write_text(f"{bystander.pid}\n")
        config = device_installer._device_config_json(
            api_token="new-access", maintenance_token="new-maintenance", agent_port=port,
        ).encode()
        device_installer._install_device_agent_sync(
            C300XDeviceInstallRequest(
                host="c300x.local", ssh_username="root", ssh_password="secret",
                remote_dir=str(tmp_path), apply_firewall_patch=False,
            ),
            device_installer._ResolvedBundle((), bundled), config,
        )
        assert bystander.poll() is None
        agent = _wait_started(pidfile, log)
        assert agent != bystander.pid and _alive(agent)
        assert json.loads((tmp_path / "config.json").read_text())["api"]["token"] == "new-access"
    finally:
        bystander.kill()
        bystander.wait()
        _reap_all(tmp_path)
