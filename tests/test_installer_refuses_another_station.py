"""A reinstall for an entry writes nothing on another station.

The address of an entry's station can lead to another station later, for
example when DHCP hands it on. Before the installer writes anything for an
existing entry, it reads over its SSH session the facts the agent names its
station after (native_agent/src/mdns.c) and compares them with the entry.
The agent itself is not needed: a broken or missing agent is what a
reinstall repairs. Only a proven mismatch stops the install.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from test_agent_reinstall import _entry, _reauth_flow, _reinstall
from test_agent_update_repairs import (
    DeviceAgentUpdateRepairFlow,
    FakeAgentUpdateState,
    FakeEntry,
    FakeHass,
    FakePatchApi,
    FakeRuntimeData,
)
from test_installer_refuses_a_foreign_host import _Host, _host, package  # noqa: F401

from custom_components.bticino_c300x import device_installer as installer
from custom_components.bticino_c300x import repairs
from custom_components.bticino_c300x.station_identity import (
    WRONG_STATION,
    StationNames,
    read_station_names,
    station_is_another,
)

ROOT = Path(__file__).resolve().parents[1]
TEXTS = ROOT / "custom_components/bticino_c300x"
ENTRY_STATION = "c300x-aabbccddeeff"
OWN = "mac AA:BB:CC:DD:EE:FF\nhost C3X-aabbccddeeff\n"
OTHER = "mac 00:03:50:11:22:33\nhost C3X-000350112233\n"


class _Station(_Host):
    """The read-only host of the foreign-host tests, answering the identity read."""

    def __init__(self, remote_dir: str, names: str) -> None:
        super().__init__(remote_dir)
        self.names = names

    def run(self, command: str, input_data: bytes | None = None) -> str:
        if "/sys/class/net/" in command:
            self.commands.append(command)
            return self.names
        return super().run(command, input_data)


def _station(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, names: str) -> _Station:
    _host(tmp_path, monkeypatch, station=True)
    station = _Station(str(tmp_path / "remote-agent"), names)
    monkeypatch.setattr(installer, "_connect_device_client", lambda _request: station)
    return station


def _install(tmp_path: Path, station_id: str) -> None:
    asyncio.run(installer.async_install_device_agent(
        installer.C300XDeviceInstallRequest(
            host="unused.invalid", ssh_username="unused", ssh_password="unused",
            remote_dir=str(tmp_path / "remote-agent"), apply_firewall_patch=False,
            c100x_confirmed=True, station_id=station_id,
        ),
        api_token="a" * 32, maintenance_token="m" * 32,
    ))


@pytest.mark.usefixtures("package")
def test_another_station_gets_nothing(tmp_path, monkeypatch):
    station = _station(tmp_path, monkeypatch, OTHER)
    with pytest.raises(installer.C300XDeviceInstallError, match=WRONG_STATION):
        _install(tmp_path, ENTRY_STATION)
    assert station.writes == [] and station.closed
    assert "/sys/class/net/" in station.commands[-1]
    assert not (tmp_path / "remote-agent").exists()


@pytest.mark.usefixtures("package")
@pytest.mark.parametrize("names", [
    pytest.param(OWN, id="same-station"),
    # Its facts cannot be read: nothing is proven, the reinstall goes ahead.
    pytest.param("", id="unreadable"),
    pytest.param("host \n", id="no-names"),
])
def test_the_entry_s_station_is_installed_without_its_agent(tmp_path, monkeypatch, names):
    # No configuration and no agent on the station: only SSH answers.
    station = _station(tmp_path, monkeypatch, names)
    with pytest.raises(RuntimeError, match="reached a write"):
        _install(tmp_path, ENTRY_STATION)
    assert station.writes == [f"mkdir -p {tmp_path / 'remote-agent'}"]


@pytest.mark.usefixtures("package")
def test_a_new_setup_reads_no_station_names(tmp_path, monkeypatch):
    station = _station(tmp_path, monkeypatch, OTHER)
    with pytest.raises(RuntimeError, match="reached a write"):
        _install(tmp_path, "")
    assert not any("/sys/class/net/" in command for command in station.commands)


@pytest.mark.parametrize("entry_id,names,another", [
    ("c300x-aabbccddeeff", StationNames(frozenset({"c300x-aabbccddeeff", "c300x-001122334455"}), "c300x-h"), False),
    ("C300X-AA:BB:CC:DD:EE:FF", StationNames(frozenset({"c300x-aabbccddeeff"}), None), False),
    ("c300x-aabbccddeeff", StationNames(frozenset({"c300x-001122334455"}), "c300x-h"), True),
    # Named after a MAC address, but the station showed none: not proven.
    ("c300x-aabbccddeeff", StationNames(frozenset(), "c300x-h"), False),
    # Named after the host name, as the agent does without a MAC address.
    ("c300x-door", StationNames(frozenset(), "c300x-door"), False),
    ("c300x-door", StationNames(frozenset(), "c300x-gate"), True),
    ("c300x-door", StationNames(frozenset(), None), False),
    # Entries without a station name prove nothing.
    ("bticino_c300x:192.0.2.10:8091", StationNames(frozenset({"c300x-001122334455"}), "c300x-h"), False),
    ("bticino_c300x", StationNames(frozenset({"c300x-001122334455"}), "c300x-h"), False),
    ("c300x-agent", StationNames(frozenset({"c300x-001122334455"}), "c300x-h"), False),
    ("", StationNames(frozenset({"c300x-001122334455"}), "c300x-h"), False),
])
def test_only_a_proven_mismatch_counts(entry_id, names, another):
    assert station_is_another(entry_id, names) is another


def test_the_names_are_read_as_the_agent_derives_them():
    answer = ("mac 00:00:00:00:00:00\nmac aa:BB:cc:dd:ee:ff\nmac 01:02\nmac \n"
              "host door.local\x01x\n")
    names = read_station_names(lambda _command: answer)
    assert names == StationNames(frozenset({"c300x-aabbccddeeff"}), "c300x-door-local-x")
    assert read_station_names(lambda _command: "host " + "h" * 80 + "\n").host == "c300x-" + "h" * 47


@pytest.mark.parametrize("shell", ["sh", "bash"])
def test_the_ssh_read_finds_the_name_the_agent_gives_this_host(tmp_path, shell):
    if shutil.which("cc") is None or shutil.which(shell) is None:
        pytest.skip(f"needs cc and {shell}")
    src = ROOT / "native_agent" / "src"
    binary = tmp_path / "device-id"
    subprocess.run(
        ["cc", "-std=c11", "-D_DEFAULT_SOURCE", "-I", str(src), "-x", "c", "-",
         str(src / "string_util.c"), str(src / "device_detect.c"), str(src / "time_util.c"),
         "-o", str(binary)],
        input='#include "mdns.c"\nint main(void)\n{\n    char id[64];\n'
              '    c300x_mdns_device_id(id, sizeof(id));\n    return puts(id) < 0;\n}\n',
        text=True, check=True, capture_output=True, timeout=30,
    )
    agent_id = subprocess.check_output([binary], text=True, timeout=5).strip()
    names = read_station_names(
        lambda command: subprocess.run([shell, "-c", command], check=True, capture_output=True,
                                       text=True, timeout=10).stdout,
    )
    assert agent_id in names.macs | {names.host}
    assert not station_is_another(agent_id, names)


def test_the_reauth_reinstall_leaves_another_station_alone(monkeypatch):
    existing = _entry()
    existing.unique_id = ENTRY_STATION
    flow = _reauth_flow(existing)
    result, _ = _reinstall(
        monkeypatch, flow, AsyncMock(side_effect=installer.C300XDeviceInstallError(WRONG_STATION)),
    )
    assert result == flow.async_abort(reason="reauth_wrong_device")
    flow.async_update_and_abort.assert_not_called()
    flow.hass.config_entries.async_schedule_reload.assert_not_called()


def test_the_ssh_repair_names_the_entry_s_station_and_shows_the_refusal(monkeypatch):
    entry = FakeEntry(
        runtime_data=FakeRuntimeData(FakePatchApi()),
        data={"agent_host": "192.0.2.60", "agent_token": "t", "maintenance_token": "m"},
        unique_id=ENTRY_STATION,
    )
    entry.runtime_data.agent_update_state = FakeAgentUpdateState()
    flow = DeviceAgentUpdateRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]
    install = AsyncMock(side_effect=installer.C300XDeviceInstallError(WRONG_STATION))
    monkeypatch.setattr(repairs, "async_install_device_agent", install)
    monkeypatch.setattr(repairs, "async_ensure_installer_dependencies", AsyncMock())
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]
    result = asyncio.run(flow.async_step_ssh_install({}))
    assert install.await_args.args[0].station_id == ENTRY_STATION
    assert result["step_id"] == "ssh_install"
    assert result["errors"] == {"base": WRONG_STATION}


@pytest.mark.parametrize("name", ["strings.json", "translations/en.json", "translations/de.json",
                                  "translations/fr.json", "translations/it.json", "translations/es.json"])
def test_every_language_names_the_refusal(name):
    texts = json.loads((TEXTS / name).read_text(encoding="utf-8"))
    assert texts["issues"]["device_agent_update_required"]["fix_flow"]["error"][WRONG_STATION]
    assert texts["config"]["abort"]["reauth_wrong_device"]
