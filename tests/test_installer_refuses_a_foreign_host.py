"""The SSH installer writes only to a BTicino station.

An SSH login alone proves nothing: a NAS or a Raspberry Pi takes one too. Every
station of every firmware has the vendor's folder /home/bticino; a host
without it gets neither the agent nor the init script, whatever the setup,
reinstall or Repair path that called the installer.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from test_agent_reinstall import _entry, _reauth_flow, _reinstall, _setup_flow
from test_agent_update_repairs import (
    DeviceAgentUpdateRepairFlow,
    FakeAgentUpdateState,
    FakeEntry,
    FakeHass,
    FakePatchApi,
    FakeRuntimeData,
)

from custom_components.bticino_c300x import config_flow, device_profile, repairs
from custom_components.bticino_c300x import device_installer as installer
from custom_components.bticino_c300x.const import CONF_REINSTALL_AGENT

ROOT = Path(__file__).resolve().parents[1]
TEXTS = ROOT / "custom_components/bticino_c300x"
REFUSED = "not_a_bticino_station"
FIRMWARE_WORK = Path(os.environ.get("C300X_FIRMWARE_WORK", ROOT.parent / "c300x-fwpatch/work"))


class _Host:
    """Runs the installer's read-only commands in a local shell; anything else is a write."""

    def __init__(self, remote_dir: str) -> None:
        self.remote_dir = remote_dir
        self.commands: list[str] = []
        self.writes: list[str] = []
        self.closed = False

    def run(self, command: str, input_data: bytes | None = None) -> str:
        self.commands.append(command)
        reads = (
            command.startswith(f"if [ -e {self.remote_dir}/config.json ]"),
            command.startswith("test -d "),
            "webserver_type" in command,
        )
        if input_data is not None or not any(reads):
            self.writes.append(command)
            raise RuntimeError("reached a write")
        return subprocess.run(["sh", "-c", command], check=True, capture_output=True, text=True, timeout=10).stdout

    def put_file(self, source: Path, remote_path: str, mode: str | None = None) -> bool:
        self.writes.append(remote_path)
        raise RuntimeError("reached a write")

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    from stage_device_agent_bundle import stage_bundle

    component = tmp_path / "component"
    binary = tmp_path / "agent"
    binary.write_bytes(b"offline payload; never executed")
    stage_bundle(component, version="test", skip_build=True, agent_binary=binary)
    monkeypatch.setattr(installer, "COMPONENT_DIR", component)
    return component


def _host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, station: bool) -> _Host:
    """A host with or without the vendor's folder; no model file, no Qt 5, no C100X program."""

    home = tmp_path / "home-bticino"
    if station:
        home.mkdir()
    monkeypatch.setattr(device_profile, "_STATION_HOME", str(home))
    monkeypatch.setattr(device_profile, "_QT5_DISPLAY_MARKER", str(tmp_path / "libQt5Core.so.5"))
    monkeypatch.setattr(device_profile, "_C100X_DISPLAY_MARKER", str(tmp_path / "BtClass100"))
    monkeypatch.setattr(device_profile, "_MODEL_FILE", str(tmp_path / "dbfiles_ws.xml"))
    host = _Host(str(tmp_path / "remote-agent"))
    monkeypatch.setattr(installer, "_connect_device_client", lambda _request: host)
    return host


def _request(tmp_path: Path, *, confirmed: bool) -> installer.C300XDeviceInstallRequest:
    return installer.C300XDeviceInstallRequest(
        host="unused.invalid", ssh_username="unused", ssh_password="unused",
        remote_dir=str(tmp_path / "remote-agent"), apply_firewall_patch=False, c100x_confirmed=confirmed,
    )


def _install(tmp_path: Path, *, confirmed: bool) -> Any:
    return asyncio.run(installer.async_install_device_agent(
        _request(tmp_path, confirmed=confirmed), api_token="a" * 32, maintenance_token="m" * 32,
    ))


@pytest.mark.parametrize("confirmed", [False, True])
def test_a_host_without_the_vendor_folder_gets_nothing(package, tmp_path, monkeypatch, confirmed):
    host = _host(tmp_path, monkeypatch, station=False)
    with pytest.raises(installer.C300XDeviceInstallError, match=REFUSED):
        _install(tmp_path, confirmed=confirmed)
    assert host.writes == [] and host.closed
    assert host.commands[-1] == f"test -d {tmp_path / 'home-bticino'} && echo station || echo other"
    assert not (tmp_path / "remote-agent").exists()


@pytest.mark.parametrize("confirmed", [False, True])
def test_a_station_without_a_model_file_still_installs(package, tmp_path, monkeypatch, confirmed):
    host = _host(tmp_path, monkeypatch, station=True)
    with pytest.raises(RuntimeError, match="reached a write"):
        _install(tmp_path, confirmed=confirmed)
    # Admitted as the Classe 300X it always was: the first write follows the probes.
    assert host.writes == [f"mkdir -p {tmp_path / 'remote-agent'}"]
    assert len(host.commands) == 4


def test_an_unread_answer_admits_no_host():
    for answer in ("", "other\n", "stations\n"):
        assert not device_profile.is_bticino_station(lambda _command, answer=answer: answer, shlex.quote)
    assert device_profile.is_bticino_station(lambda _command: "station\n", shlex.quote)


def test_every_station_firmware_has_the_vendor_folder(tmp_path):
    for firmware in ("1.7.19", "2.0.2", "3.0.6", "c100x-1.5.8"):
        root = FIRMWARE_WORK / f"rootfs-{firmware}"
        if not root.is_dir():
            pytest.skip("Private firmware files unavailable")

        def run(command: str, root: Path = root) -> str:
            command = command.replace("'/home/bticino'", shlex.quote(f"{root}/home/bticino"))
            return subprocess.run(["sh", "-c", command], capture_output=True, text=True, check=True).stdout

        assert device_profile.is_bticino_station(run, lambda text: f"'{text}'"), firmware
    assert device_profile.is_bticino_station(
        lambda command: subprocess.run(["sh", "-c", command], capture_output=True, text=True, check=True).stdout,
        lambda _text: shlex.quote(str(tmp_path / "absent")),
    ) is False


def test_setup_shows_the_refusal(monkeypatch):
    flow = _setup_flow(True)
    monkeypatch.setattr(config_flow, "async_ensure_installer_dependencies", AsyncMock())
    monkeypatch.setattr(config_flow, "async_install_device_agent",
                        AsyncMock(side_effect=installer.C300XDeviceInstallError(REFUSED)))
    result = asyncio.run(flow.async_step_agent_auth({CONF_REINSTALL_AGENT: True}))
    assert result["step_id"] == "bootstrap_install"
    assert result["errors"] == {"base": REFUSED}


def test_the_reauth_reinstall_shows_the_refusal(monkeypatch):
    flow = _reauth_flow(_entry())
    result, _ = _reinstall(monkeypatch, flow, AsyncMock(side_effect=installer.C300XDeviceInstallError(REFUSED)))
    assert result["step_id"] == "reauth_reinstall"
    assert result["errors"] == {"base": REFUSED}
    flow.async_update_and_abort.assert_not_called()


def test_the_ssh_repair_shows_the_refusal(monkeypatch):
    entry = FakeEntry(
        runtime_data=FakeRuntimeData(FakePatchApi()),
        data={"agent_host": "192.0.2.60", "agent_token": "t", "maintenance_token": "m"},
    )
    entry.runtime_data.agent_update_state = FakeAgentUpdateState()
    flow = DeviceAgentUpdateRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]
    monkeypatch.setattr(repairs, "async_install_device_agent",
                        AsyncMock(side_effect=installer.C300XDeviceInstallError(REFUSED)))
    monkeypatch.setattr(repairs, "async_ensure_installer_dependencies", AsyncMock())
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]
    result = asyncio.run(flow.async_step_ssh_install({}))
    assert result["step_id"] == "ssh_install"
    assert result["errors"] == {"base": REFUSED}


@pytest.mark.parametrize("name", ["strings.json", "translations/en.json", "translations/de.json",
                                  "translations/fr.json", "translations/it.json", "translations/es.json"])
def test_every_language_names_the_refusal(name):
    texts = json.loads((TEXTS / name).read_text(encoding="utf-8"))
    repair = texts["issues"]["device_agent_update_required"]["fix_flow"]["error"]
    assert texts["config"]["error"][REFUSED] == repair[REFUSED]
    assert "BTicino" in repair[REFUSED] and "{" not in repair[REFUSED]


def test_the_refusal_needs_no_ssh_session_of_its_own():
    # One cheap read in the session the installer already holds.
    command = []
    device_profile.is_bticino_station(lambda text: command.append(text) or "station", shlex.quote)
    assert command == ["test -d /home/bticino && echo station || echo other"]
