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
from .const import CONF_STATION_ID
from .entry_types import BticinoC300XConfigEntry
from .identity import (
    station_device_identifier,
    station_id,
    station_unique_id,
    unit_device_identifier,
    unit_unique_id,
    valid_station_id,
)

_LOGGER = logging.getLogger(__name__)

ENTRY_VERSION = 2
# 2.x key -> key on the default outdoor unit.
UNIT_KEYS = {
    "doorbell_camera": "camera",
    "doorbell_event": "doorbell",
    "door_unlock": "door",
}
# Entities 3.1.0 no longer has.
REMOVED_KEYS = frozenset({"doorbell_state", "agent_event"})


def identity_migration_needed(entry: BticinoC300XConfigEntry, agent_station_id: str | None) -> bool:
    """True until the entry carries the station id the agent reports."""

    new = valid_station_id(agent_station_id)
    return new is not None and (new != station_id(entry) or entry.version < ENTRY_VERSION)


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
    old = station_id(entry)
    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    old_identifier = station_device_identifier(entry)
    result: dict[str, list[str]] = {"moved": [], "removed": []}

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_STATION_ID: new}, version=ENTRY_VERSION,
    )
    station = devices.async_get_device(identifiers={old_identifier})
    if station is not None and old != new:
        devices.async_update_device(station.id, new_identifiers={station_device_identifier(entry)})
    unit_device: Any = None

    for entity in list(er.async_entries_for_config_entry(entities, entry.entry_id)):
        unique_id = str(entity.unique_id)
        if not unique_id.startswith(f"{old}_") or unique_id.startswith(f"{old}_unit_"):
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
                unit_device = devices.async_get_device(
                    identifiers={unit_device_identifier(entry, default_unit.id)},
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
