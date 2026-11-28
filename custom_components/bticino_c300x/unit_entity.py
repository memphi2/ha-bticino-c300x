"""Entities of one outdoor unit, on its own device below the station."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .agent_contracts import OutdoorUnit
from .call_registry import (
    SIGNAL_CALLS_CHANGED,
    SIGNAL_OUTDOOR_UNITS_CHANGED,
    C300XCallRegistry,
    units_from_stored,
)
from .call_sync import entry_call_registry
from .const import CONF_OUTDOOR_UNITS, DOMAIN
from .entity import C300XEntity
from .entry_types import BticinoC300XConfigEntry
from .identity import (
    station_device_identifier,
    station_id_known,
    unit_device_identifier,
    unit_unique_id,
)

if TYPE_CHECKING:
    from homeassistant.helpers.device_registry import DeviceInfo
else:
    from homeassistant.helpers.entity import DeviceInfo

__all__ = ["DeviceInfo"]

OUTDOOR_UNIT_MODEL = "Outdoor unit"


def unit_device_info(entry: BticinoC300XConfigEntry, unit: OutdoorUnit) -> DeviceInfo:
    """Link an entity to its unit's device, registered by async_register_unit_device."""

    return DeviceInfo(identifiers={unit_device_identifier(entry, unit.id)})


@callback
def async_register_unit_device(
    hass: HomeAssistant, entry: BticinoC300XConfigEntry, unit: OutdoorUnit,
) -> None:
    """The unit's device below the station: the station's name for it, else "Outdoor unit <where>"."""

    from .entity import station_device_fields

    devices = dr.async_get(hass)
    station = devices.async_get_or_create(config_entry_id=entry.entry_id, **station_device_fields(entry))
    names: dict[str, Any] = (
        {"name": unit.name} if unit.name
        else {"translation_key": "outdoor_unit", "translation_placeholders": {"unit": unit.where}}
    )
    devices.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={unit_device_identifier(entry, unit.id)},
        via_device_id=station.id,
        manufacturer="BTicino",
        model=OUTDOOR_UNIT_MODEL,
        **names,
    )


@callback
def event_device_id(hass: HomeAssistant, entry: BticinoC300XConfigEntry, unit_id: str | None) -> str | None:
    """The device a station event belongs to: its unit's, else the station's.

    None while the entry waits for its station id (before the agent update
    Repair): there is no device yet, and the event still reaches the bus.
    """

    if not station_id_known(entry):
        return None
    devices = dr.async_get(hass)
    identifiers = [station_device_identifier(entry)]
    if unit_id is not None:
        # A unit that rang for the first time has no device yet.
        identifiers.insert(0, unit_device_identifier(entry, unit_id))
    for identifier in identifiers:
        device = devices.async_get_device_by_identifier(identifier, entry.entry_id)
        if device is not None:
            return device.id
    return None


def unit_device_removable(entry: BticinoC300XConfigEntry, identifiers: Iterable[tuple[str, str]]) -> bool:
    """A unit device may go once the station no longer reports its unit.

    The station's own device and the device of a unit the station still
    reports stay. Without a known unit list nothing is removed.
    """

    prefix = unit_device_identifier(entry, "")[1]
    unit_ids = {value[len(prefix):] for domain, value in identifiers
                if domain == DOMAIN and value.startswith(prefix)}
    if not unit_ids:
        return False
    registry = entry_call_registry(entry)
    if registry is not None and registry.loaded:
        known: set[str] = set(registry.units)
    else:
        stored = units_from_stored(entry.data.get(CONF_OUTDOOR_UNITS))
        if stored is None:
            return False
        known = {unit.id for unit in stored.units}
    return not unit_ids & known


class C300XUnitEntity(C300XEntity):
    """Base for the entities of one outdoor unit."""

    def __init__(self, entry: BticinoC300XConfigEntry, unit: OutdoorUnit, key: str) -> None:
        C300XEntity.__init__(self, entry, key)
        self._unit = unit
        self._attr_unique_id = unit_unique_id(entry, unit.id, key)
        self._attr_device_info = unit_device_info(entry, unit)

    @property
    def device_info(self) -> DeviceInfo:
        return unit_device_info(self._entry, self._unit)

    @property
    def unit_id(self) -> str:
        return self._unit.id

    @property
    def _calls(self) -> C300XCallRegistry | None:
        return entry_call_registry(self._entry)

    def _listen_calls(self, handler: Callable[[], None]) -> None:
        """Run ``handler`` whenever this entry's calls change."""

        @callback
        def changed(entry_id: str) -> None:
            if entry_id == self._entry.entry_id:
                handler()

        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_CALLS_CHANGED, changed))


@callback
def async_track_outdoor_units(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
    add_entities: Callable[[Iterable[Entity]], None],
    build: Callable[[OutdoorUnit], Iterable[Entity]],
    wants: Callable[[OutdoorUnit], bool] | None = None,
) -> None:
    """Add the entities of every unit the station has, and of units it learns later.

    With ``wants`` only units it accepts get their entities, also a known
    unit once it is accepted (a door contact seen for the first time).
    """

    added: set[str] = set()

    @callback
    def add_new(entry_id: str | None = None) -> None:
        if entry_id is not None and entry_id != entry.entry_id:
            return
        registry = entry_call_registry(entry)
        if registry is None:
            return
        entities: list[Entity] = []
        for unit in registry.units.values():
            # A unit the station renamed: its device takes the new name.
            async_register_unit_device(hass, entry, unit)
            if unit.id not in added and (wants is None or wants(unit)):
                added.add(unit.id)
                entities.extend(build(unit))
        if entities:
            add_entities(entities)

    add_new()
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_OUTDOOR_UNITS_CHANGED, add_new))
