"""Move a 2.x entry's registry entries to the station and outdoor unit identities.

Runs at the first setup with an agent that reports outdoor units, before the
platforms load. Entity ids, names, areas and history stay: only unique ids
and device links change (docs/dev/multi-outdoor-units.md, Migration).
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .agent_contracts import OutdoorUnit
from .const import CONF_STATION_ID, DOMAIN
from .entry_types import BticinoC300XConfigEntry
from .identity import (
    station_device_identifier,
    station_unique_id,
    unit_device_identifier,
    unit_unique_id,
    valid_station_id,
)

_LOGGER = logging.getLogger(__name__)
_UNIT_MARK = ":unit:"

ENTRY_VERSION = 2
# 2.x key -> key on the default outdoor unit.
UNIT_KEYS = {
    "doorbell_camera": "camera",
    "doorbell_event": "doorbell",
    "door_unlock": "door",
}
# Entities 3.1.0 no longer has.
REMOVED_KEYS = frozenset({"doorbell_state", "agent_event"})


def _current_id(entry: BticinoC300XConfigEntry) -> str:
    """The id the entry's registry entries carry now: the stored station id, else the entry id of 2.x."""

    return valid_station_id(entry.data.get(CONF_STATION_ID)) or str(entry.entry_id)


def identity_migration_needed(entry: BticinoC300XConfigEntry, agent_station_id: str | None) -> bool:
    """True until the entry carries the station id the agent reports."""

    new = valid_station_id(agent_station_id)
    return new is not None and (new != _current_id(entry) or entry.version < ENTRY_VERSION)


def _move_unit_devices(devices: Any, entry: BticinoC300XConfigEntry, old: str, new: str) -> None:
    """The unit devices of the old station id take the new one."""

    old_mark = f"{old}{_UNIT_MARK}"
    for device in list(dr.async_entries_for_config_entry(devices, entry.entry_id)):
        identifiers = {
            (domain, f"{new}{_UNIT_MARK}{value[len(old_mark):]}")
            if domain == DOMAIN and value.startswith(old_mark) else (domain, value)
            for domain, value in device.identifiers
        }
        if identifiers != device.identifiers:
            devices.async_update_device(device.id, new_identifiers=identifiers)


def async_migrate_identity(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
    agent_station_id: str,
    default_unit: OutdoorUnit,
) -> dict[str, list[str]]:
    """Rename and move the registry entries; safe to run again.

    Returns the entity ids that moved to the unit and those removed.
    """

    new = valid_station_id(agent_station_id)
    if new is None:
        raise ValueError("invalid station id")
    old = _current_id(entry)
    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    old_identifier = (DOMAIN, old)
    result: dict[str, list[str]] = {"moved": [], "removed": []}

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_STATION_ID: new}, version=ENTRY_VERSION,
    )
    station = devices.async_get_device_by_identifier(old_identifier, entry.entry_id)
    if station is not None and old != new:
        devices.async_update_device(station.id, new_identifiers={station_device_identifier(entry)})
    if old != new:
        _move_unit_devices(devices, entry, old, new)
    unit_device: Any = None

    for entity in list(er.async_entries_for_config_entry(entities, entry.entry_id)):
        unique_id = str(entity.unique_id)
        if not unique_id.startswith(f"{old}_"):
            continue
        if unique_id.startswith(f"{old}_unit_"):
            # A unit entity of the old station id: same unit, new station id.
            target = f"{new}_unit_{unique_id[len(old) + 6:]}"
            if old != new and entities.async_get_entity_id(entity.domain, entity.platform, target) is None:
                entities.async_update_entity(entity.entity_id, new_unique_id=target)
            continue
        key = unique_id[len(old) + 1:]
        if key in REMOVED_KEYS:
            entities.async_remove(entity.entity_id)
            result["removed"].append(entity.entity_id)
            continue
        if key in UNIT_KEYS:
            if unit_device is None:
                from .unit_entity import async_register_unit_device

                async_register_unit_device(hass, entry, default_unit)
                unit_device = devices.async_get_device_by_identifier(
                    unit_device_identifier(entry, default_unit.id), entry.entry_id,
                )
            target = unit_unique_id(entry, default_unit.id, UNIT_KEYS[key])
            if entities.async_get_entity_id(entity.domain, entity.platform, target) is not None:
                continue
            entities.async_update_entity(
                entity.entity_id, new_unique_id=target, device_id=unit_device.id,
            )
            result["moved"].append(entity.entity_id)
            continue
        target = station_unique_id(entry, key)
        if old != new and entities.async_get_entity_id(entity.domain, entity.platform, target) is None:
            entities.async_update_entity(entity.entity_id, new_unique_id=target)
    _LOGGER.info(
        "C300X entry %s now uses station id %s; moved %s, removed %s",
        entry.entry_id, new, result["moved"], result["removed"],
    )
    return result


def async_migrate_entry_identity(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
    agent_station_id: str,
    default_unit: OutdoorUnit,
) -> dict[str, list[str]]:
    """Migrate, and tell an entry from before 3.1.0 once what to redo.

    Entries made by 3.1.0 start at ENTRY_VERSION. Such an entry set up while
    the station was offline also has ids to move, but nothing to redo.
    """

    from_2x = entry.version < ENTRY_VERSION
    result = async_migrate_identity(hass, entry, agent_station_id, default_unit)
    if from_2x and (result["moved"] or result["removed"]):
        from .repair_issues import async_create_breaking_change_issue

        async_create_breaking_change_issue(hass, entry)
    return result
