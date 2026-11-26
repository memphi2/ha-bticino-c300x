"""The identity migration against Home Assistant's own registries."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import MappingProxyType
from typing import Any

from homeassistant import bootstrap, config_entries, core, loader
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.bticino_c300x import identity_migration
from custom_components.bticino_c300x._api_calls import normalize_outdoor_units
from custom_components.bticino_c300x.const import CONF_STATION_ID, DOMAIN

UNITS = normalize_outdoor_units({"default_unit": "20", "units": [
    {"id": "20", "where": "20", "name": "Gate", "default": True},
    {"id": "21", "where": "21", "name": "Side door"},
]})
OLD = "c300x-0123456789ab"
NEW = "c300x-ba9876543210"


async def _hass(tmp_path: Path) -> core.HomeAssistant:
    hass = core.HomeAssistant(str(tmp_path))
    hass.config.skip_pip = True
    loader.async_setup(hass)
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    await bootstrap.async_load_base_functionality(hass)
    return hass


def _entry(hass: core.HomeAssistant, data: dict[str, Any], version: int) -> config_entries.ConfigEntry:
    entry = config_entries.ConfigEntry(
        version=version, minor_version=1, domain=DOMAIN, title="Door", data=data, options={},
        source="user", unique_id=None, discovery_keys=MappingProxyType({}), subentries_data=None,
    )
    # Registered, not set up: the migration runs before the platforms load.
    hass.config_entries._entries[entry.entry_id] = entry  # noqa: SLF001
    return entry


def _register(entities: er.EntityRegistry, entry: Any, device: Any, domain: str, unique_id: str) -> str:
    return entities.async_get_or_create(
        domain, DOMAIN, unique_id, config_entry=entry, device_id=device.id,
    ).entity_id


def test_a_2x_entry_moves_to_the_station_and_its_default_unit(tmp_path: Path) -> None:
    async def run() -> None:
        hass = await _hass(tmp_path)
        entry = _entry(hass, {"host": "door"}, 1)
        devices, entities = dr.async_get(hass), er.async_get(hass)
        station = devices.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, entry.entry_id)})
        camera = _register(entities, entry, station, "camera", f"{entry.entry_id}_doorbell_camera")
        door = _register(entities, entry, station, "button", f"{entry.entry_id}_door_unlock")
        mute = _register(entities, entry, station, "switch", f"{entry.entry_id}_ringer_mute")
        state = _register(entities, entry, station, "sensor", f"{entry.entry_id}_doorbell_state")

        result = identity_migration.async_migrate_identity(hass, entry, OLD, UNITS.units[0])

        unit = devices.async_get_device_by_identifier((DOMAIN, f"{OLD}:unit:20"), entry.entry_id)
        assert unit is not None and unit.via_device_id == station.id
        assert station.id == devices.async_get_device_by_identifier((DOMAIN, OLD), entry.entry_id).id
        assert (entities.async_get(camera).unique_id, entities.async_get(camera).device_id) == (
            f"{OLD}_unit_20_camera", unit.id)
        assert entities.async_get(door).unique_id == f"{OLD}_unit_20_door"
        assert (entities.async_get(mute).unique_id, entities.async_get(mute).device_id) == (
            f"{OLD}_ringer_mute", station.id)
        assert entities.async_get(state) is None
        assert result == {"moved": [camera, door], "removed": [state]}
        assert (entry.version, entry.data[CONF_STATION_ID]) == (identity_migration.ENTRY_VERSION, OLD)
        await hass.async_stop(force=True)

    asyncio.run(run())


def test_a_new_station_id_takes_the_unit_devices_and_entities_along(tmp_path: Path) -> None:
    # A migrated entry whose station id changes: the unit devices and unit
    # entities keep their place instead of leaving orphans and "_2" entities.
    async def run() -> None:
        hass = await _hass(tmp_path)
        entry = _entry(hass, {"host": "door", CONF_STATION_ID: OLD}, identity_migration.ENTRY_VERSION)
        devices, entities = dr.async_get(hass), er.async_get(hass)
        station = devices.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, OLD)})
        units = {
            unit_id: devices.async_get_or_create(
                config_entry_id=entry.entry_id, identifiers={(DOMAIN, f"{OLD}:unit:{unit_id}")},
                via_device_id=station.id,
            )
            for unit_id in ("20", "21")
        }
        camera = _register(entities, entry, units["20"], "camera", f"{OLD}_unit_20_camera")
        side = _register(entities, entry, units["21"], "button", f"{OLD}_unit_21_door")
        mute = _register(entities, entry, station, "switch", f"{OLD}_ringer_mute")
        assert identity_migration.identity_migration_needed(entry, NEW)

        for _ in range(2):
            identity_migration.async_migrate_identity(hass, entry, NEW, UNITS.units[0])
            for unit_id, device in units.items():
                assert devices.async_get(device.id).identifiers == {(DOMAIN, f"{NEW}:unit:{unit_id}")}
            assert devices.async_get(station.id).identifiers == {(DOMAIN, NEW)}
            assert entities.async_get(camera).unique_id == f"{NEW}_unit_20_camera"
            assert entities.async_get(camera).device_id == units["20"].id
            assert entities.async_get(side).unique_id == f"{NEW}_unit_21_door"
            assert entities.async_get(mute).unique_id == f"{NEW}_ringer_mute"
            assert len(dr.async_entries_for_config_entry(devices, entry.entry_id)) == 3
            assert len(er.async_entries_for_config_entry(entities, entry.entry_id)) == 3
        assert not identity_migration.identity_migration_needed(entry, NEW)
        await hass.async_stop(force=True)

    asyncio.run(run())
