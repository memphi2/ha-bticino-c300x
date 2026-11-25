"""Ring events: the station ringing, and the outdoor unit a visitor rang at.

The station's ``ring`` fires at once with every new call. The unit's
``doorbell`` fires when the call's unit is known, with the same call id: at
once when the station has one unit, else on ``call.caller_identified``
(docs/dev/multi-outdoor-units.md).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from homeassistant.components.event import (
    DoorbellEventType,
    EventDeviceClass,
    EventEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .agent_contracts import OutdoorUnit
from .const import EVENT_AGENT_EVENT_RECEIVED
from .entity import C300XEntity, supports_capability
from .entry_types import BticinoC300XConfigEntry
from .event_payload import agent_event_key
from .unit_entity import C300XUnitEntity, async_track_outdoor_units
from .video import resolve_doorbell_camera_entity_id

if TYPE_CHECKING:
    from homeassistant.core import Event

PARALLEL_UPDATES = 0
# A call fires once; the agent keeps at most eight calls.
_FIRED_CALLS = 8


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the station ring and one doorbell event per outdoor unit."""

    if not supports_capability(entry, "doorbell_events"):
        return
    async_add_entities([C300XStationRingEventEntity(entry)])

    def build(unit: OutdoorUnit) -> list[C300XUnitDoorbellEventEntity]:
        return [C300XUnitDoorbellEventEntity(entry, unit)]

    async_track_outdoor_units(hass, entry, async_add_entities, build)


class _RingEvent(EventEntity):
    """One ring per call id, from the agent events on the bus."""

    _attr_device_class = EventDeviceClass.DOORBELL
    _attr_event_types = [DoorbellEventType.RING]
    _attr_should_poll = False
    _entry: BticinoC300XConfigEntry

    def _init_ring(self) -> None:
        self._fired: deque[str] = deque(maxlen=_FIRED_CALLS)
        self._last_ring_at: str | None = None
        self._last_call_id: str | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.hass.bus.async_listen(EVENT_AGENT_EVENT_RECEIVED, self._agent_event))

    @callback
    def _agent_event(self, event: Event) -> None:
        data = event.data
        if data.get("entry_id") != self._entry.entry_id:
            return
        call_id = data.get("call_id")
        if not isinstance(call_id, str) or call_id in self._fired:
            return
        attributes = self._ring_attributes(agent_event_key(data), data)
        if attributes is None:
            return
        self._fired.append(call_id)
        self._last_call_id = call_id
        self._last_ring_at = data.get("event_at")
        self._trigger_event(DoorbellEventType.RING, {"call_id": call_id, **attributes})
        self.async_write_ha_state()

    def _ring_attributes(self, key: str | None, data: Mapping[str, Any]) -> dict[str, Any] | None:
        raise NotImplementedError

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        hass = getattr(self, "hass", None)
        return {
            "call_id": self._last_call_id,
            "last_ring_at": self._last_ring_at,
            "camera_entity_id": resolve_doorbell_camera_entity_id(hass, self._entry) if hass else None,
        }


class C300XStationRingEventEntity(_RingEvent, C300XEntity):
    """The indoor station rings: the fastest trigger, without the unit's name."""

    _attr_translation_key = "ring"

    def __init__(self, entry: BticinoC300XConfigEntry) -> None:
        C300XEntity.__init__(self, entry, "ring")
        self._init_ring()

    def _ring_attributes(self, key: str | None, data: Mapping[str, Any]) -> dict[str, Any] | None:
        if key != "doorbell_pressed":
            return None
        return {"unit": data.get("unit_id")}


class C300XUnitDoorbellEventEntity(_RingEvent, C300XUnitEntity):
    """A visitor rang at this outdoor unit."""

    _attr_translation_key = "doorbell_event"

    def __init__(self, entry: BticinoC300XConfigEntry, unit: OutdoorUnit) -> None:
        C300XUnitEntity.__init__(self, entry, unit, "doorbell")
        self._init_ring()

    def _ring_attributes(self, key: str | None, data: Mapping[str, Any]) -> dict[str, Any] | None:
        unit = data.get("unit_id")
        registry = self._calls
        if key == "doorbell_pressed" and unit is None:
            # One unit: it is the caller, no need to wait for the caller frame.
            if registry is None or list(registry.units) != [self.unit_id]:
                return None
            unit = self.unit_id
        elif key not in {"doorbell_pressed", "call_caller_identified"}:
            return None
        if unit != self.unit_id:
            return None
        call = registry.call(data["call_id"]) if registry is not None else None
        return {
            "unit": self.unit_id,
            "unit_name": self._unit.name or None,
            "attribution": call.attribution if call is not None else None,
        }
