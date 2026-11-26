"""A setup that reinstalls the agent of a station HA already has keeps one entry.

Which station a setup reached is known only after the install. When it is the
station of an existing entry, that entry gets the new keys; nothing is lost.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from custom_components.bticino_c300x import config_flow, config_flow_agent
from custom_components.bticino_c300x.api_errors import C300XAgentApiAuthError
from custom_components.bticino_c300x.config_flow import BticinoC300XConfigFlow
from custom_components.bticino_c300x.config_flow_identity import (
    stable_unique_id_from_setup_data,
)
from custom_components.bticino_c300x.const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_DEVICE_ACTIVATION_MODE,
    CONF_MAINTENANCE_TOKEN,
    CONF_REINSTALL_AGENT,
)
from custom_components.bticino_c300x.device_installer import C300XDeviceInstallError

DEVICE = "c300x-0003504a1b2c"
STATION = stable_unique_id_from_setup_data({"device_id": DEVICE})
_INSTALLED = SimpleNamespace(display_pending=False, display_kind="qt4_ondisk")


def _entry(unique_id: str, host: str, title: str = "Door") -> SimpleNamespace:
    return SimpleNamespace(
        entry_id=f"entry-{host}", title=title, unique_id=unique_id, update_listeners=[],
        data={CONF_AGENT_HOST: host, CONF_AGENT_PORT: 8080, CONF_AGENT_TOKEN: "old",
              CONF_MAINTENANCE_TOKEN: "old-too", "shared_secret": "keep"},
        options={CONF_AGENT_TOKEN: "shadow", CONF_AGENT_PORT: 8080, CONF_DEVICE_ACTIVATION_MODE: "manual"},
    )


def _update(entry, *, data=None, options=None, unique_id=None):
    entry.data = data if data is not None else entry.data
    entry.options = options if options is not None else entry.options
    entry.unique_id = unique_id or entry.unique_id
    return True


def _setup(monkeypatch, entries, read_setup, installer=None):
    flow = BticinoC300XConfigFlow()
    flow.context = {"source": "user"}
    flow._setup_connection = {"name": "Door", CONF_AGENT_HOST: "station.example", CONF_AGENT_PORT: 8091}
    flow._setup_agent_needs_token = True
    flow._async_abort_if_manual_setup_duplicate = AsyncMock()

    async def adopt(*, api_token: str = "") -> None:
        flow._setup_unique_id = STATION

    flow._async_adopt_agent_unique_id = adopt
    flow._async_current_entries = lambda include_ignore=None: entries
    flow.hass = SimpleNamespace(config_entries=SimpleNamespace(
        async_update_entry=Mock(side_effect=_update), async_schedule_reload=Mock(), flow=None,
    ))
    installer = installer or AsyncMock(return_value=_INSTALLED)
    migrate = AsyncMock()
    monkeypatch.setattr(config_flow, "async_ensure_installer_dependencies", AsyncMock())
    monkeypatch.setattr(config_flow, "async_install_device_agent", installer)
    monkeypatch.setattr(config_flow, "_async_probe_agent", AsyncMock(return_value="reachable"))
    monkeypatch.setattr(config_flow, "async_migrate_legacy_mqtt_for_connection", migrate)
    monkeypatch.setattr(config_flow_agent, "async_agent_setup_data", read_setup)
    result = asyncio.run(flow.async_step_agent_auth({CONF_AGENT_TOKEN: "", CONF_REINSTALL_AGENT: True}))
    return flow, result, installer.await_args.kwargs, migrate


def _assert_entry_has_the_new_keys(flow, entry, keys) -> None:
    assert entry.data == {
        CONF_AGENT_HOST: "station.example", CONF_AGENT_PORT: 8091,
        CONF_AGENT_TOKEN: keys["api_token"], CONF_MAINTENANCE_TOKEN: keys["maintenance_token"],
        "shared_secret": "keep",
    }
    # No option hides the new values; other options stay.
    assert entry.options == {CONF_DEVICE_ACTIVATION_MODE: "manual"}
    flow.hass.config_entries.async_schedule_reload.assert_called_once_with(entry.entry_id)


def test_a_reinstall_of_a_station_with_an_entry_gives_that_entry_the_new_keys(monkeypatch):
    existing = _entry(STATION, "door-old.local")
    flow, result, keys, migrate = _setup(monkeypatch, [existing], AsyncMock())
    assert result["type"] == "abort" and result["reason"] == "reinstall_entry_updated"
    assert result["description_placeholders"]["name"] == "Door"
    _assert_entry_has_the_new_keys(flow, existing, keys)
    assert existing.unique_id == STATION
    migrate.assert_not_called()


def test_an_entry_under_its_address_counts_when_that_address_reaches_the_station(monkeypatch):
    existing = _entry("bticino_c300x:door.local:8080", "door.local")
    asked = []

    async def read_setup(_hass, connection, *, api_token=""):
        asked.append((connection[CONF_AGENT_HOST], connection[CONF_AGENT_PORT], api_token))
        return {"device_id": DEVICE}

    flow, result, keys, _ = _setup(monkeypatch, [existing], read_setup)
    assert result["reason"] == "reinstall_entry_updated"
    # Its own address, the port the agent now listens on, and the keys just written.
    assert asked == [("door.local", 8091, keys["api_token"])]
    _assert_entry_has_the_new_keys(flow, existing, keys)
    assert existing.unique_id == STATION


def test_the_entry_of_another_station_is_left_alone(monkeypatch):
    other = _entry("bticino_c300x:other.local:8080", "other.local", title="Other")
    before = (dict(other.data), dict(other.options), other.unique_id)
    flow, result, keys, migrate = _setup(
        monkeypatch, [other], AsyncMock(side_effect=C300XAgentApiAuthError()),
    )
    assert result["step_id"] == "user_features"
    assert (other.data, other.options, other.unique_id) == before
    flow.hass.config_entries.async_update_entry.assert_not_called()
    assert flow._setup_connection[CONF_AGENT_TOKEN] == keys["api_token"]
    migrate.assert_awaited_once()


def test_keys_a_failed_install_left_on_the_station_are_kept(monkeypatch):
    existing = _entry(STATION, "door-old.local")
    failure = C300XDeviceInstallError("device_install_verify_failed")
    # The configuration with the new keys was written; a later step failed.
    failure.keys_written = True
    installer = AsyncMock(side_effect=[failure, _INSTALLED])
    asked = []

    async def read_setup(_hass, connection, *, api_token=""):
        asked.append((connection[CONF_AGENT_HOST], api_token))
        return {"device_id": DEVICE}

    flow, result, keys, _ = _setup(monkeypatch, [existing], read_setup, installer)
    # The failure is shown; the entry of the station has the keys at once.
    assert result["step_id"] == "bootstrap_install"
    assert result["errors"] == {"base": "device_install_verify_failed"}
    assert asked == [("station.example", keys["api_token"])]
    _assert_entry_has_the_new_keys(flow, existing, keys)
    # The retry writes the same keys again: nothing on the station changes hands.
    result = asyncio.run(flow.async_step_bootstrap_install({}))
    assert installer.await_args.kwargs == keys
    assert result["reason"] == "reinstall_entry_updated"
    assert existing.data[CONF_AGENT_TOKEN] == keys["api_token"]


def test_keys_of_a_failed_install_that_wrote_none_are_not_reused(monkeypatch):
    installer = AsyncMock(side_effect=[C300XDeviceInstallError("ssh_login_refused"), _INSTALLED])
    read_setup = AsyncMock()
    flow, result, first, _ = _setup(monkeypatch, [], read_setup, installer)
    assert result["errors"] == {"base": "ssh_login_refused"}
    read_setup.assert_not_called()
    asyncio.run(flow.async_step_bootstrap_install({}))
    assert installer.await_args.kwargs["api_token"] != first["api_token"]
