"""A reinstall or a handed-over older entry ends with the station's outdoor unit devices.

The setup hands the new keys to the existing entry (3.0.0b2) and reloads it;
that setup reads the outdoor units and migrates the entry's identity (3.1.0).
Both run here on Home Assistant's own config entry, device, entity and issue
registries.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any

from homeassistant import bootstrap, config_entries, core, loader
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from custom_components.bticino_c300x import identity_migration
from custom_components.bticino_c300x._api_calls import (
    normalize_calls,
    normalize_outdoor_units,
)
from custom_components.bticino_c300x.call_registry import C300XCallRegistry
from custom_components.bticino_c300x.config_flow_station_entry import (
    async_hand_keys_to_entry,
)
from custom_components.bticino_c300x.const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_MAINTENANCE_TOKEN,
    CONF_STATION_ID,
    DOMAIN,
)
from custom_components.bticino_c300x.repair_issues import (
    OUTDOOR_UNITS_BREAKING_CHANGE_ISSUE,
    repair_issue_id,
)
from custom_components.bticino_c300x.runtime_manager import C300XRuntimeManager

STATION = "c300x-0003504a1b2c"
UNIQUE_ID = "c300x0003504a1b2c"
UNITS = normalize_outdoor_units({"default_unit": "20", "units": [
    {"id": "20", "where": "20", "name": "Gate", "default": True},
    {"id": "21", "where": "21", "name": "Side door"},
]})
CONNECTION = {
    CONF_AGENT_HOST: "192.0.2.10", CONF_AGENT_PORT: 8091,
    CONF_AGENT_TOKEN: "new-" + "a" * 40, CONF_MAINTENANCE_TOKEN: "new-" + "m" * 40,
}


class _Api:
    async def async_outdoor_units(self) -> Any:
        return UNITS

    async def async_calls(self) -> Any:
        return normalize_calls({"calls": []})


async def _hass(tmp_path: Path) -> core.HomeAssistant:
    hass = core.HomeAssistant(str(tmp_path))
    hass.config.skip_pip = True
    loader.async_setup(hass)
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    await bootstrap.async_load_base_functionality(hass)
    return hass


def _entry(hass: core.HomeAssistant, unique_id: str, data: dict[str, Any], version: int) -> Any:
    entry = config_entries.ConfigEntry(
        version=version, minor_version=1, domain=DOMAIN, title="Door", data=data, options={},
        source="user", unique_id=unique_id, discovery_keys=MappingProxyType({}), subentries_data=None,
    )
    hass.config_entries._entries[entry.entry_id] = entry  # noqa: SLF001
    return entry


async def _reloaded_setup(hass: core.HomeAssistant, entry: Any) -> None:
    """What the reloaded entry's setup does with the units before its platforms load."""

    capabilities = {"calls": True, "outdoor_units": True}
    entry.runtime_data = SimpleNamespace(calls=C300XCallRegistry(), api=_Api(), capabilities=capabilities)
    manager = SimpleNamespace(
        hass=hass, entry=entry, capabilities=capabilities,
        connection_state=SimpleNamespace(available=True), setup_data={"device_id": STATION},
    )
    await C300XRuntimeManager.async_sync_calls(manager)  # type: ignore[arg-type]


def _handed_over(tmp_path: Path, unique_id: str, data: dict[str, Any], version: int, key: str) -> None:
    async def run() -> None:
        hass = await _hass(tmp_path)
        reloads: list[str] = []
        hass.config_entries.async_schedule_reload = reloads.append  # type: ignore[method-assign]
        entry = _entry(hass, unique_id, {
            CONF_AGENT_HOST: "door.lan", CONF_AGENT_PORT: 8091,
            CONF_AGENT_TOKEN: "lost", CONF_MAINTENANCE_TOKEN: "lost", **data,
        }, version)
        devices, entities = dr.async_get(hass), er.async_get(hass)
        prefix = data.get(CONF_STATION_ID, entry.entry_id)
        station = devices.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, prefix)})
        holder = station
        if CONF_STATION_ID in data:
            # A 3.1 entry's platforms made the unit device already.
            holder = devices.async_get_or_create(
                config_entry_id=entry.entry_id, identifiers={(DOMAIN, f"{prefix}:unit:20")},
                via_device_id=station.id,
            )
        camera = entities.async_get_or_create(
            "camera", DOMAIN, f"{prefix}_{key}", config_entry=entry, device_id=holder.id,
        ).entity_id

        assert await async_hand_keys_to_entry(
            hass, entry, CONNECTION, unique_id=UNIQUE_ID, display_pending=False,
        )
        assert reloads == [entry.entry_id]
        await _reloaded_setup(hass, entry)

        assert entry.unique_id == UNIQUE_ID
        assert (entry.data[CONF_AGENT_TOKEN], entry.data[CONF_AGENT_HOST]) == ("new-" + "a" * 40, "192.0.2.10")
        assert (entry.data[CONF_STATION_ID], entry.version) == (STATION, identity_migration.ENTRY_VERSION)
        station = devices.async_get_device_by_identifier((DOMAIN, STATION), entry.entry_id)
        unit = devices.async_get_device_by_identifier((DOMAIN, f"{STATION}:unit:20"), entry.entry_id)
        assert station is not None and unit is not None and unit.via_device_id == station.id
        assert holder.id in (station.id, unit.id)
        assert len(dr.async_entries_for_config_entry(devices, entry.entry_id)) == 2
        assert (entities.async_get(camera).unique_id, entities.async_get(camera).device_id) == (
            f"{STATION}_doorbell_camera", unit.id)
        issue = ir.async_get(hass).async_get_issue(
            DOMAIN, repair_issue_id(OUTDOOR_UNITS_BREAKING_CHANGE_ISSUE, entry.entry_id))
        # Only an entry from before 3.1 has something to redo.
        assert (issue is not None) is (version < identity_migration.ENTRY_VERSION)
        await hass.async_stop(force=True)

    asyncio.run(run())


def test_an_older_entry_handed_the_keys_moves_to_the_station_and_its_units(tmp_path: Path) -> None:
    # A 2.x entry under an address identity: it takes the station's identity,
    # its doorbell camera moves to the default unit, the Repair names the rest.
    _handed_over(tmp_path, f"{DOMAIN}:door.lan:8091", {}, 1, "doorbell_camera")


def test_a_3_1_entry_reinstalled_keeps_its_station_and_unit_devices(tmp_path: Path) -> None:
    # The keys were lost; the entry and its unit devices stay, nothing to redo.
    _handed_over(tmp_path, UNIQUE_ID, {CONF_STATION_ID: STATION}, identity_migration.ENTRY_VERSION, "doorbell_camera")
