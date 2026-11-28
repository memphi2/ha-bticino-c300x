"""The identity migration and unit devices against Home Assistant's own registries."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
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


def test_a_unit_the_station_renames_renames_its_device(tmp_path: Path) -> None:
    from homeassistant.helpers.dispatcher import async_dispatcher_send

    from custom_components.bticino_c300x import unit_entity
    from custom_components.bticino_c300x.call_registry import (
        SIGNAL_OUTDOOR_UNITS_CHANGED,
        C300XCallRegistry,
    )

    async def run() -> None:
        hass = await _hass(tmp_path)
        entry = _entry(hass, {"host": "door", CONF_STATION_ID: OLD}, identity_migration.ENTRY_VERSION)
        calls = C300XCallRegistry()
        calls.set_units(UNITS)
        entry.runtime_data = type("Runtime", (), {"calls": calls})()
        added: list[str] = []
        unit_entity.async_track_outdoor_units(hass, entry, added.extend, lambda unit: [unit.id])
        devices = dr.async_get(hass)
        gate = devices.async_get_device_by_identifier((DOMAIN, f"{OLD}:unit:20"), entry.entry_id)
        assert gate is not None and gate.name == "Gate"

        calls.set_units(normalize_outdoor_units({"default_unit": "20", "units": [
            {"id": "20", "where": "20", "name": "Front gate", "default": True},
            {"id": "21", "where": "21", "name": "Side door"},
        ]}))
        async_dispatcher_send(hass, SIGNAL_OUTDOOR_UNITS_CHANGED, entry.entry_id)
        await hass.async_block_till_done()
        assert devices.async_get(gate.id).name == "Front gate"
        assert added == ["20", "21"]
        await hass.async_stop(force=True)

    asyncio.run(run())


def test_only_an_entry_from_before_3_1_gets_the_breaking_change_repair(tmp_path: Path) -> None:
    # A 3.1 entry set up while the station was offline kept the entry-id camera
    # id; its migration moves it, but the entry has nothing to redo.
    from types import SimpleNamespace

    from homeassistant.helpers import issue_registry as ir

    from custom_components.bticino_c300x.call_registry import C300XCallRegistry
    from custom_components.bticino_c300x.repair_issues import (
        OUTDOOR_UNITS_BREAKING_CHANGE_ISSUE,
        repair_issue_id,
    )
    from custom_components.bticino_c300x.runtime_manager import C300XRuntimeManager

    class Api:
        async def async_outdoor_units(self) -> Any:
            return UNITS

        async def async_calls(self) -> Any:
            from custom_components.bticino_c300x._api_calls import normalize_calls

            return normalize_calls({"calls": []})

    async def run() -> None:
        hass = await _hass(tmp_path)
        issues = ir.async_get(hass)
        capabilities = {"calls": True, "outdoor_units": True}
        for version, repaired in ((identity_migration.ENTRY_VERSION, False), (1, True)):
            entry = _entry(hass, {"host": "door"}, version)
            station = dr.async_get(hass).async_get_or_create(
                config_entry_id=entry.entry_id, identifiers={(DOMAIN, entry.entry_id)})
            camera = _register(er.async_get(hass), entry, station, "camera", f"{entry.entry_id}_doorbell_camera")
            entry.runtime_data = SimpleNamespace(calls=C300XCallRegistry(), api=Api(), capabilities=capabilities)
            manager = SimpleNamespace(
                hass=hass, entry=entry, capabilities=capabilities,
                connection_state=SimpleNamespace(available=True),
                setup_data={"device_id": f"c300x-00000000000{version}"},
            )

            await C300XRuntimeManager.async_sync_calls(manager)  # type: ignore[arg-type]

            assert er.async_get(hass).async_get(camera).unique_id == f"c300x-00000000000{version}_unit_20_camera"
            issue = issues.async_get_issue(DOMAIN, repair_issue_id(OUTDOOR_UNITS_BREAKING_CHANGE_ISSUE, entry.entry_id))
            assert (issue is not None) is repaired, version
        await hass.async_stop(force=True)

    asyncio.run(run())


def test_the_device_of_the_merged_unit_20_2_goes_with_its_entities(tmp_path: Path) -> None:
    """Units 20 and 20#2 are the one unit 20: the device unit:20_2 is removed once."""

    merged = normalize_outdoor_units({"default_unit": "20", "units": [
        {"id": "20", "where": "20#2", "name": "Gate", "default": True},
        {"id": "21", "where": "21", "name": "Side door"},
    ]})

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
            for unit_id in ("20", "20_2", "21")
        }
        camera = _register(entities, entry, units["20"], "camera", f"{OLD}_unit_20_camera")
        orphan_door = _register(entities, entry, units["20_2"], "button", f"{OLD}_unit_20_2_door")
        orphan_ring = _register(entities, entry, units["20_2"], "event", f"{OLD}_unit_20_2_doorbell")
        entities.async_update_entity(orphan_ring, disabled_by=er.RegistryEntryDisabler.USER)
        side = _register(entities, entry, units["21"], "button", f"{OLD}_unit_21_door")

        removed = identity_migration.async_remove_merged_unit_devices(hass, entry, merged.units)

        assert removed == [orphan_door, orphan_ring]
        assert devices.async_get(units["20_2"].id) is None
        assert entities.async_get(orphan_door) is None and entities.async_get(orphan_ring) is None
        assert devices.async_get(units["20"].id) is not None and devices.async_get(units["21"].id) is not None
        assert entities.async_get(camera) is not None and entities.async_get(side) is not None
        # Once only: nothing is left to remove.
        assert identity_migration.async_remove_merged_unit_devices(hass, entry, merged.units) == []
        # A unit the agent itself reports as 20_2 keeps its device.
        kept = devices.async_get_or_create(
            config_entry_id=entry.entry_id, identifiers={(DOMAIN, f"{OLD}:unit:20_2")}, via_device_id=station.id,
        )
        reported = normalize_outdoor_units({"default_unit": "20_2", "units": [
            {"id": "20_2", "where": "20#2", "name": "Gate", "default": True},
        ]})
        assert identity_migration.async_remove_merged_unit_devices(hass, entry, reported.units) == []
        assert devices.async_get(kept.id) is not None
        await hass.async_stop(force=True)

    asyncio.run(run())


def test_setup_removes_the_merged_unit_device_before_the_platforms(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from custom_components.bticino_c300x._api_calls import normalize_calls
    from custom_components.bticino_c300x.call_registry import C300XCallRegistry
    from custom_components.bticino_c300x.runtime_manager import C300XRuntimeManager

    class Api:
        async def async_outdoor_units(self) -> Any:
            return normalize_outdoor_units({"default_unit": "20", "units": [
                {"id": "20", "where": "20#2", "name": "Gate", "default": True},
            ]})

        async def async_calls(self) -> Any:
            return normalize_calls({"calls": []})

    async def run() -> None:
        hass = await _hass(tmp_path)
        entry = _entry(hass, {"host": "door", CONF_STATION_ID: OLD}, identity_migration.ENTRY_VERSION)
        devices, entities = dr.async_get(hass), er.async_get(hass)
        station = devices.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, OLD)})
        orphan = devices.async_get_or_create(
            config_entry_id=entry.entry_id, identifiers={(DOMAIN, f"{OLD}:unit:20_2")}, via_device_id=station.id,
        )
        door = _register(entities, entry, orphan, "button", f"{OLD}_unit_20_2_door")
        capabilities = {"calls": True, "outdoor_units": True}
        entry.runtime_data = SimpleNamespace(calls=C300XCallRegistry(), api=Api(), capabilities=capabilities)
        manager = SimpleNamespace(
            hass=hass, entry=entry, capabilities=capabilities,
            connection_state=SimpleNamespace(available=True), setup_data={"device_id": OLD},
        )

        await C300XRuntimeManager.async_sync_calls(manager)  # type: ignore[arg-type]

        assert devices.async_get(orphan.id) is None
        assert entities.async_get(door) is None
        await hass.async_stop(force=True)

    asyncio.run(run())


def test_a_station_event_finds_its_device_without_the_deprecated_lookup(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    # device_registry.async_get_device is deprecated and stops working in
    # 2027.8; the lookup goes by identifier within the entry.
    from custom_components.bticino_c300x import unit_entity

    async def run() -> None:
        hass = await _hass(tmp_path)
        entry = _entry(hass, {"host": "door", CONF_STATION_ID: OLD}, identity_migration.ENTRY_VERSION)
        unit_entity.async_register_unit_device(hass, entry, UNITS.units[0])
        devices = dr.async_get(hass)
        station = devices.async_get_device_by_identifier((DOMAIN, OLD), entry.entry_id)
        gate = devices.async_get_device_by_identifier((DOMAIN, f"{OLD}:unit:20"), entry.entry_id)
        assert station is not None and gate is not None
        assert unit_entity.event_device_id(hass, entry, "20") == gate.id
        # A unit that has no device yet, and an event without a unit.
        assert unit_entity.event_device_id(hass, entry, "21") == station.id
        assert unit_entity.event_device_id(hass, entry, None) == station.id
        await hass.async_stop(force=True)

    with caplog.at_level(logging.WARNING):
        asyncio.run(run())
    assert not [record for record in caplog.records if "async_get_device`" in record.getMessage()]
