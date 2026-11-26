"""The station keeps its agent; Home Assistant or the integration is set up again.

End to end on every station profile (C300X 1.7.19 and 2.0.2 with the Qt 4
display, 3.0.6 with the Qt 5 overlay, C100X 1.5.8 with its confirmation): the
real flows, the real installer and HA's own duplicate checks, against a
station reached over stand-in HTTP and SSH transports (station_e2e).

Each case checks the entries HA ends with, what the station received and
that no key went to an address that did not prove it is the station.
"""

from __future__ import annotations

import asyncio
import secrets
from typing import Any

import pytest
import station_e2e
import station_flow_harness
from homeassistant.data_entry_flow import AbortFlow
from station_e2e import FIRMWARES, PAGES, PATCHED_PAGES, Account, Network, Station

from custom_components.bticino_c300x.config_flow import BticinoC300XConfigFlow
from custom_components.bticino_c300x.config_flow_c100x import CONF_C100X_EXPERIMENTAL
from custom_components.bticino_c300x.const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_BOOTSTRAP_SSH_KEY,
    CONF_BOOTSTRAP_SSH_PASSWORD,
    CONF_BOOTSTRAP_SSH_USERNAME,
    CONF_DISPLAY_FOLLOWUP_PENDING,
    CONF_MAINTENANCE_TOKEN,
    CONF_REINSTALL_AGENT,
    DOMAIN,
)
from custom_components.bticino_c300x.factory_login import factory_ssh_login

IP = "192.0.2.10"
PORT = 8091
DEVICE = "c300x-0003504a1b2c"
UNIQUE_ID = "c300x0003504a1b2c"
KEYS = (secrets.token_urlsafe(32), secrets.token_urlsafe(32))
SSH_KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n-----END OPENSSH PRIVATE KEY-----"
LOGINS = ["factory", "typed_password", "typed_key", "not_root"]


@pytest.fixture
def network(monkeypatch, tmp_path) -> Network:
    return Network(monkeypatch, station_e2e.bundle(tmp_path / "package"))


def _station(network: Network, tmp_path, firmware: str, *names: str, login: str = "factory",
             ip: str = IP, device_id: str = DEVICE) -> Station:
    """A station with a running agent whose keys HA may or may not have."""

    station = network.add(Station.with_agent(tmp_path, firmware, ip=ip, device_id=device_id, keys=KEYS), *names)
    if login != "factory":
        # Rooted with a login of its own: the factory login is refused.
        station.accounts = {"root": Account("rooted-pw", keys=(SSH_KEY.strip(),))}
        station.accounts["bticino2"] = Account("second-pw", uid=1000)
    return station


def _typed_login(login: str) -> dict[str, Any]:
    return {
        "typed_password": {CONF_BOOTSTRAP_SSH_USERNAME: "root", CONF_BOOTSTRAP_SSH_PASSWORD: "rooted-pw"},
        "typed_key": {CONF_BOOTSTRAP_SSH_USERNAME: "root", CONF_BOOTSTRAP_SSH_KEY: SSH_KEY},
        "not_root": {CONF_BOOTSTRAP_SSH_USERNAME: "bticino2", CONF_BOOTSTRAP_SSH_PASSWORD: "second-pw"},
    }[login]


class HA:
    """Home Assistant's entries and flow manager, as far as the flows reach them."""

    def __init__(self, entries: list[Any] | None = None) -> None:
        self.hass = station_flow_harness.hass(entries)
        self.registry = self.hass.config_entries
        # What the station's files were when a step asked before any write.
        self.before_confirmation: list[dict[str, Any]] = []
        self.station: Station | None = None

    @property
    def entries(self) -> list[Any]:
        return self.registry.entries

    def flow(self, *, source: str = "user", entry_id: str | None = None) -> BticinoC300XConfigFlow:
        return station_flow_harness.attach(BticinoC300XConfigFlow(), self.hass, source=source, entry_id=entry_id)

    async def step(self, flow: Any, step_id: str, user_input: dict[str, Any] | None = None) -> dict[str, Any]:
        """One step, as the flow manager runs it: an AbortFlow ends the flow."""

        try:
            result = await getattr(flow, f"async_step_{step_id}")(user_input)
        except AbortFlow as err:
            return {"type": "abort", "reason": err.reason}
        if result["type"] == "create_entry":
            self._create(flow, result)
        return result

    def _create(self, flow: Any, result: dict[str, Any]) -> None:
        unique_id = flow.context.get("unique_id")
        # HA keeps one entry per unique id; the flow must have aborted before.
        assert self.registry.async_entry_for_domain_unique_id(DOMAIN, unique_id) is None
        self.entries.append(station_flow_harness.entry(
            f"entry-{len(self.entries) + 1}", unique_id, result["data"],
            title=result["title"], options=result["options"],
        ))

    async def wizard(self, flow: Any, result: dict[str, Any]) -> dict[str, Any]:
        """Answer the setup's feature steps with their defaults and confirm a Classe 100X."""

        while result["type"] == "form":
            step_id = result["step_id"]
            if step_id == "c100x_experimental":
                if self.station is not None:
                    self.before_confirmation.append(self.station.files())
                user_input: dict[str, Any] = {CONF_C100X_EXPERIMENTAL: True}
            elif step_id.startswith("user_"):
                user_input = result["data_schema"]({})
            else:
                return result
            result = await self.step(flow, step_id, user_input)
        return result

    async def setup(self, host: str = IP, *, keys: tuple[str, str] | None = None) -> tuple[Any, dict[str, Any]]:
        """Add the integration; with ``keys`` typed in, else with the reinstall ticked."""

        flow = self.flow()
        result = await self.step(flow, "user", {"name": "Door", CONF_AGENT_HOST: host, CONF_AGENT_PORT: PORT})
        if result["type"] != "form":
            return flow, result
        assert result["step_id"] == "agent_auth"
        # The agent asks for a key: the reinstall is offered.
        assert CONF_REINSTALL_AGENT in result["data_schema"].schema
        answer = {CONF_REINSTALL_AGENT: True} if keys is None else {
            CONF_AGENT_TOKEN: keys[0], CONF_MAINTENANCE_TOKEN: keys[1],
        }
        return flow, await self.wizard(flow, await self.step(flow, "agent_auth", answer))

    async def reauth(self, entry: Any) -> tuple[Any, dict[str, Any]]:
        flow = self.flow(source="reauth", entry_id=entry.entry_id)
        result = await self.step(flow, "reauth", dict(entry.data))
        assert result["step_id"] == "reauth_confirm"
        return flow, await self.step(flow, "reauth_confirm", {CONF_REINSTALL_AGENT: True})


def _saved_entry(unique_id: str, host: str, *, title: str = "Door") -> Any:
    """An entry whose keys no longer match the station's (they were lost)."""

    return station_flow_harness.entry(f"entry-{host}", unique_id, {
        CONF_AGENT_HOST: host, CONF_AGENT_PORT: PORT, CONF_AGENT_TOKEN: "lost-" + "a" * 40,
        CONF_MAINTENANCE_TOKEN: "lost-" + "m" * 40, "shared_secret": "kept",
    }, title=title, options={CONF_AGENT_TOKEN: "lost-shadow"})


def _assert_entry_holds_the_station_keys(entry: Any, station: Station, host: str = IP) -> None:
    keys = station.held_keys()
    assert entry.unique_id == UNIQUE_ID
    assert (entry.data[CONF_AGENT_HOST], entry.data[CONF_AGENT_PORT]) == (host, PORT)
    assert (entry.data[CONF_AGENT_TOKEN], entry.data[CONF_MAINTENANCE_TOKEN]) == keys
    # No option hides the stored keys.
    assert CONF_AGENT_TOKEN not in entry.options and CONF_MAINTENANCE_TOKEN not in entry.options
    # The running agent signs in with exactly these keys.
    loaded = station.loaded()
    assert loaded is not None
    assert (loaded["api"]["token"], loaded["maintenance"]["adminToken"]) == keys


def _assert_keys_only_to(network: Network, *hosts: str) -> None:
    """Every request that carried a key went to one of ``hosts``."""

    assert {item.host for item in network.requests if item.token or item.maintenance} <= set(hosts)
    # A proof request carries the nonce only.
    assert all(not (item.token or item.maintenance) for item in network.requests
               if item.path == "/api/v1/identity/proof")


def _assert_reinstalled(station: Station, *, old_keys: tuple[str, str] = KEYS) -> None:
    """New keys written by the stopped agent's replacement; the display pages kept."""

    assert station.held_keys() != old_keys and old_keys[0] not in station.held_keys()
    init = station.log("init")
    # The old agent was stopped by the bundled init script before its keys
    # were replaced, and the new one started.
    assert init[init.index("stop"):] == ["stop", "restart", "status"]
    # What the station set up itself stays.
    assert station.config()["mqtt"] == {"enabled": True, "host": "broker.lan"}
    _assert_display_kept(station)


def _assert_display_kept(station: Station) -> None:
    # No display re-patch: only the core step runs, on a C300X; the C100X has none.
    expected = [] if station.profile["kind"] == "qt5_ondisk" else ["core-apply"]
    assert set(station.log("display")) <= set(expected)
    assert station.path(PAGES).read_bytes() == PATCHED_PAGES


def _nothing_written(station: Station, files: dict[str, Any]) -> None:
    assert station.files() == files
    assert station.held_keys() == KEYS and station.loaded() is not None
    assert station.log("init") == ["start"] and station.log("display") == []


def _check_confirmation(ha: HA, station: Station, files: dict[str, Any]) -> None:
    """A Classe 100X is confirmed before anything is written; a Classe 300X is not asked."""

    if station.profile["model"] == "C100X":
        assert ha.before_confirmation and all(seen == files for seen in ha.before_confirmation)
    else:
        assert ha.before_confirmation == []


# 1. Fresh HA, the user has the keys: no SSH at all.


@pytest.mark.parametrize("firmware", FIRMWARES)
def test_fresh_ha_with_the_keys_creates_the_entry_without_ssh(network, tmp_path, firmware):
    station = _station(network, tmp_path, firmware)
    files = station.files()
    ha = HA()
    ha.station = station
    _flow, result = asyncio.run(ha.setup(keys=KEYS))
    assert result["type"] == "create_entry"
    assert len(ha.entries) == 1
    _assert_entry_holds_the_station_keys(ha.entries[0], station)
    assert network.ssh_hosts == [] and station.commands == [] and station.logins == []
    _nothing_written(station, files)
    _check_confirmation(ha, station, files)
    _assert_keys_only_to(network, IP)


# 2. Fresh HA, the keys are lost: the reinstall writes new ones.


async def _setup_with_reinstall(ha: HA, login: str) -> dict[str, Any]:
    flow, result = await ha.setup()
    if login != "factory":
        assert result["step_id"] == "bootstrap_install"
        assert result["errors"] == {"base": "ssh_login_refused"}
        result = await ha.wizard(flow, await ha.step(flow, "bootstrap_install", _typed_login(login)))
    return result


@pytest.mark.parametrize("login", LOGINS)
@pytest.mark.parametrize("firmware", FIRMWARES)
def test_fresh_ha_without_the_keys_reinstalls_and_creates_the_entry(network, tmp_path, firmware, login):
    station = _station(network, tmp_path, firmware, login=login)
    files = station.files()
    ha = HA()
    ha.station = station
    result = asyncio.run(_setup_with_reinstall(ha, login))
    if login == "not_root":
        assert result["step_id"] == "bootstrap_install"
        assert result["errors"] == {"base": "ssh_user_not_root"}
        assert ha.entries == []
        _nothing_written(station, files)
        # The login read its user id and nothing else.
        assert [command for command in station.commands if command != "id -u"] == []
        _assert_keys_only_to(network, IP)
        return
    assert result["type"] == "create_entry"
    assert len(ha.entries) == 1
    entry = ha.entries[0]
    _assert_entry_holds_the_station_keys(entry, station)
    _assert_reinstalled(station)
    # The install ran its steps; no display step is owed.
    assert CONF_DISPLAY_FOLLOWUP_PENDING not in entry.data
    _check_confirmation(ha, station, files)
    _assert_keys_only_to(network, IP)
    method = {"typed_key": "key"}.get(login, "password")
    assert station.logins[-1] == ({"factory": factory_ssh_login(station.profile["model"])[0]}.get(login, "root"),
                                  method, True)


@pytest.mark.parametrize("firmware", FIRMWARES)
def test_fresh_ha_without_the_keys_reinstalls_a_station_added_by_its_name(network, tmp_path, firmware):
    station = _station(network, tmp_path, firmware, "door.local")
    ha = HA()
    ha.station = station
    _flow, result = asyncio.run(ha.setup("door.local"))
    assert result["type"] == "create_entry"
    assert len(ha.entries) == 1
    _assert_entry_holds_the_station_keys(ha.entries[0], station, "door.local")
    _assert_reinstalled(station)
    assert set(network.ssh_hosts) == {"door.local"}
    _assert_keys_only_to(network, "door.local")


@pytest.mark.parametrize("firmware", FIRMWARES)
def test_adding_a_station_whose_entry_has_its_address_stops_before_any_install(network, tmp_path, firmware):
    """The entry is there: its keys come back through its reauth, not a second setup."""

    station = _station(network, tmp_path, firmware)
    files = station.files()
    entry = _saved_entry(UNIQUE_ID, IP)
    before = (dict(entry.data), dict(entry.options))
    ha = HA([entry])
    _flow, result = asyncio.run(ha.setup())
    assert (result["type"], result["reason"]) == ("abort", "already_configured")
    assert ha.entries == [entry] and (entry.data, entry.options) == before
    assert network.ssh_hosts == [] and network.requests == []
    _nothing_written(station, files)


# 3. HA still has the entry, the keys are lost: reauth reinstalls them.


@pytest.mark.parametrize("login", LOGINS)
@pytest.mark.parametrize("firmware", FIRMWARES)
def test_reauth_reinstall_gives_the_same_entry_the_new_keys(network, tmp_path, firmware, login):
    station = _station(network, tmp_path, firmware, login=login)
    files = station.files()
    entry = _saved_entry(UNIQUE_ID, IP)
    ha = HA([entry])

    async def run() -> dict[str, Any]:
        flow, result = await ha.reauth(entry)
        if login != "factory":
            assert result["step_id"] == "reauth_reinstall"
            assert result["errors"] == {"base": "ssh_login_refused"}
            result = await ha.step(flow, "reauth_reinstall", _typed_login(login))
        return result

    result = asyncio.run(run())
    assert ha.entries == [entry]
    if login == "not_root":
        assert result["errors"] == {"base": "ssh_user_not_root"}
        assert entry.data[CONF_AGENT_TOKEN].startswith("lost-") and ha.registry.reloaded == []
        _nothing_written(station, files)
        return
    assert (result["type"], result["reason"]) == ("abort", "reauth_successful")
    _assert_entry_holds_the_station_keys(entry, station)
    assert entry.data["shared_secret"] == "kept"
    assert ha.registry.reloaded == [entry.entry_id]
    _assert_reinstalled(station)
    assert CONF_DISPLAY_FOLLOWUP_PENDING not in entry.data
    _assert_keys_only_to(network, IP)


# 4. The integration is added again while an entry of an older release
#    (an address-based unique id) still points at the station.


@pytest.mark.parametrize("keys_known", [False, True])
@pytest.mark.parametrize("firmware", FIRMWARES)
def test_a_legacy_entry_of_the_station_is_proven_and_gets_the_keys(network, tmp_path, firmware, keys_known):
    station = _station(network, tmp_path, firmware, "door.local")
    files = station.files()
    legacy = _saved_entry(f"{DOMAIN}:door.local:{PORT}", "door.local")
    ha = HA([legacy])
    ha.station = station
    _flow, result = asyncio.run(ha.setup(keys=KEYS if keys_known else None))
    reason = "station_entry_updated" if keys_known else "reinstall_entry_updated"
    assert (result["type"], result["reason"]) == ("abort", reason)
    assert result["description_placeholders"]["name"] == "Door"
    assert ha.entries == [legacy]
    _assert_entry_holds_the_station_keys(legacy, station)
    assert legacy.data["shared_secret"] == "kept"
    assert ha.registry.reloaded == [legacy.entry_id]
    if keys_known:
        # The typed keys work: nothing on the station changes.
        assert station.held_keys() == KEYS and network.ssh_hosts == []
        _nothing_written(station, files)
    else:
        _assert_reinstalled(station)
    # The saved name was resolved to the station's IPv4 address, which proved
    # the identity; no request ever went to the name, none with a key to it.
    proofs = [item for item in network.requests if item.path == "/api/v1/identity/proof"]
    assert [(item.host, item.port) for item in proofs] == [(IP, PORT)]
    assert [item for item in network.requests if item.host == "door.local"] == []
    _assert_keys_only_to(network, IP)


@pytest.mark.parametrize("firmware", FIRMWARES)
def test_a_legacy_entry_proven_with_the_access_key_alone_keeps_its_maintenance_key(network, tmp_path, firmware):
    station = _station(network, tmp_path, firmware, "door.local")
    legacy = _saved_entry(f"{DOMAIN}:door.local:{PORT}", "door.local")
    kept = legacy.data[CONF_MAINTENANCE_TOKEN]
    ha = HA([legacy])
    ha.station = station
    _flow, result = asyncio.run(ha.setup(keys=(KEYS[0], "")))
    assert (result["type"], result["reason"]) == ("abort", "station_entry_updated")
    assert ha.entries == [legacy] and legacy.unique_id == UNIQUE_ID
    assert (legacy.data[CONF_AGENT_HOST], legacy.data[CONF_AGENT_TOKEN]) == (IP, KEYS[0])
    assert legacy.data[CONF_MAINTENANCE_TOKEN] == kept
    assert network.ssh_hosts == [] and station.held_keys() == KEYS
    _assert_keys_only_to(network, IP)


@pytest.mark.parametrize("keys_known", [False, True])
@pytest.mark.parametrize("other", ["nothing", "another_station", "ipv6", "unknown_name"])
@pytest.mark.parametrize("firmware", FIRMWARES)
def test_an_unproven_legacy_entry_is_left_alone_and_a_new_entry_created(network, tmp_path, firmware, other,
                                                                        keys_known):
    station = _station(network, tmp_path, firmware)
    host = {"ipv6": "fd00::5", "unknown_name": "gone.local"}.get(other, "door-old.local")
    network.names["door-old.local"] = "192.0.2.99"
    if other == "another_station":
        _station(network, tmp_path, "2.0.2", ip="192.0.2.99", device_id="c300x-0003504affff")
    legacy = _saved_entry(f"{DOMAIN}:{host}:{PORT}", host, title="Other")
    before = (dict(legacy.data), dict(legacy.options), legacy.unique_id)
    ha = HA([legacy])
    ha.station = station
    _flow, result = asyncio.run(ha.setup(keys=KEYS if keys_known else None))
    assert result["type"] == "create_entry"
    assert len(ha.entries) == 2 and ha.entries[0] is legacy
    assert (legacy.data, legacy.options, legacy.unique_id) == before
    _assert_entry_holds_the_station_keys(ha.entries[1], station)
    if keys_known:
        assert station.held_keys() == KEYS and network.ssh_hosts == []
    else:
        _assert_reinstalled(station)
    assert ha.registry.reloaded == []
    # Only the nonce went to the other address.
    _assert_keys_only_to(network, IP)
    proofs = [(item.host, item.port) for item in network.requests if item.path == "/api/v1/identity/proof"]
    assert proofs == ([("192.0.2.99", PORT)] if host == "door-old.local" else [])


# 5. A failure after the new keys were written: HA keeps them, the agent
#    runs again, the retry ends on the same entry.


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("firmware", FIRMWARES)
def test_a_setup_whose_restart_failed_keeps_the_keys_and_its_retry_ends_cleanly(network, tmp_path, firmware,
                                                                              existing):
    station = _station(network, tmp_path, firmware, "door.local")
    entries = [_saved_entry(UNIQUE_ID, "door.local")] if existing else []
    ha = HA(entries)
    ha.station = station
    station.fail_next("restart")

    async def run() -> None:
        flow, result = await ha.setup()
        assert result["step_id"] == "bootstrap_install"
        assert result["errors"] == {"base": "device_install_failed"}
        written = station.held_keys()
        assert written != KEYS
        # The agent runs again, with the keys of this install.
        assert station.log("init")[-1] == "start"
        assert station.loaded()["api"]["token"] == written[0]
        if existing:
            # The station's entry has them at once.
            _assert_entry_holds_the_station_keys(entries[0], station, IP)
            assert ha.registry.reloaded == [entries[0].entry_id]
        result = await ha.wizard(flow, await ha.step(flow, "bootstrap_install", {}))
        # The retry wrote no other keys.
        assert station.held_keys() == written
        if existing:
            assert (result["type"], result["reason"]) == ("abort", "reinstall_entry_updated")
        else:
            assert result["type"] == "create_entry"

    asyncio.run(run())
    assert len(ha.entries) == 1
    _assert_entry_holds_the_station_keys(ha.entries[0], station)
    # Stopped once, for the first install; the retry replaced no keys.
    assert station.log("init") == ["start", "stop", "restart", "start", "restart", "status"]
    _assert_display_kept(station)
    _assert_keys_only_to(network, IP)


@pytest.mark.parametrize("firmware", FIRMWARES)
def test_a_reauth_whose_restart_failed_keeps_the_keys_and_its_retry_ends_cleanly(network, tmp_path, firmware):
    station = _station(network, tmp_path, firmware)
    entry = _saved_entry(UNIQUE_ID, IP)
    ha = HA([entry])
    station.fail_next("restart")

    async def run() -> None:
        flow, result = await ha.reauth(entry)
        assert result["step_id"] == "reauth_reinstall"
        assert result["errors"] == {"base": "device_install_failed"}
        # The entry has the keys the station holds now, and the agent runs with them.
        _assert_entry_holds_the_station_keys(entry, station)
        assert station.log("init")[-1] == "start"
        assert ha.registry.reloaded == [entry.entry_id]
        result = await ha.step(flow, "reauth_reinstall", {})
        assert (result["type"], result["reason"]) == ("abort", "reauth_successful")

    asyncio.run(run())
    assert ha.entries == [entry]
    _assert_entry_holds_the_station_keys(entry, station)
    assert station.log("init")[-2:] == ["restart", "status"]
    _assert_display_kept(station)
    _assert_keys_only_to(network, IP)


# The display step of the install fails: on the Qt 5 overlay of 3.0.6 it is
# owed and recorded for the core Repair, on the Qt 4 display it fails the
# install (its retry runs it again), the C100X has none.


@pytest.mark.parametrize("firmware", FIRMWARES)
def test_a_failed_display_step_is_recorded_per_display_kind(network, tmp_path, firmware):
    station = _station(network, tmp_path, firmware)
    station.fail_next("display")
    kind = station.profile["kind"]
    ha = HA()
    ha.station = station

    async def run() -> dict[str, Any]:
        flow, result = await ha.setup()
        if kind == "qt4_ondisk":
            assert result["errors"] == {"base": "device_install_verify_failed"}
            result = await ha.wizard(flow, await ha.step(flow, "bootstrap_install", {}))
        return result

    result = asyncio.run(run())
    assert result["type"] == "create_entry"
    entry = ha.entries[0]
    _assert_entry_holds_the_station_keys(entry, station)
    if kind == "qt5_rcc":
        assert entry.data[CONF_DISPLAY_FOLLOWUP_PENDING] is False
    else:
        assert CONF_DISPLAY_FOLLOWUP_PENDING not in entry.data
    _assert_display_kept(station)
    _assert_keys_only_to(network, IP)
