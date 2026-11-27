"""The media camera's place among the outdoor units, and the other units' cameras.

The media camera (ring, answer, on-demand video) belongs to the default
outdoor unit's device. It also tells the card about the current call: its
id, its unit and that unit's door button, so the card follows the call
(docs/dev/multi-outdoor-units.md, Card).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .agent_contracts import OutdoorUnit
from .call_registry import SIGNAL_CALLS_CHANGED, SIGNAL_OUTDOOR_UNITS_CHANGED
from .call_sync import entry_call_registry
from .const import DOMAIN
from .entity import C300XEntity
from .entry_types import BticinoC300XConfigEntry
from .identity import default_unit_id, unit_device_identifier, unit_unique_id
from .unit_entity import DeviceInfo, async_track_outdoor_units
from .unit_platforms import C300XUnitCamera


@callback
def async_add_unit_cameras(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
    add_entities: Callable[[Iterable[Entity]], None],
    media_camera: Callable[[], Entity],
) -> None:
    """The media camera for the default outdoor unit, a camera for every other unit.

    Each comes with its unit: before the station named its units there is none.
    """

    def build(unit: OutdoorUnit) -> list[Entity]:
        registry = entry_call_registry(entry)
        if registry is None:
            return []
        return [media_camera() if unit.id == registry.default_unit else C300XUnitCamera(entry, unit)]

    async_track_outdoor_units(hass, entry, add_entities, build)


def current_call_attributes(hass: HomeAssistant | None, entry: BticinoC300XConfigEntry) -> dict[str, Any]:
    """The current call and the door button that opens its unit (else the default unit's)."""

    registry = entry_call_registry(entry)
    call = registry.current_call if registry is not None else None
    unit_id = (call.unit if call is not None else None) or default_unit_id(entry)
    door = None
    if hass is not None and unit_id is not None:
        door = er.async_get(hass).async_get_entity_id("button", DOMAIN, unit_unique_id(entry, unit_id, "door"))
    return {
        "call_id": call.call_id if call is not None else None,
        "call_state": call.state if call is not None else None,
        "call_unit": call.unit if call is not None else None,
        "call_unit_name": (registry.unit_name(call.unit) if call is not None and call.unit else None)
        if registry is not None else None,
        "door_entity_id": door,
    }


class MediaCameraUnit(C300XEntity):
    """Puts the media camera on the default unit's device and follows the calls."""

    @property
    def device_info(self) -> DeviceInfo:
        # Built with the default unit (async_add_unit_cameras), so it is known.
        unit = default_unit_id(self._entry) or ""
        return DeviceInfo(identifiers={unit_device_identifier(self._entry, unit)})

    def _call_attributes(self) -> dict[str, Any]:
        return current_call_attributes(getattr(self, "hass", None), self._entry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def changed(entry_id: str) -> None:
            if entry_id == self._entry.entry_id:
                self.async_write_ha_state()

        for signal in (SIGNAL_CALLS_CHANGED, SIGNAL_OUTDOOR_UNITS_CHANGED):
            self.async_on_remove(async_dispatcher_connect(self.hass, signal, changed))
