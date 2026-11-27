"""Station events: rings, a door opened, the stair light switched on.

A unit's ``door`` fires ``opened`` with the bus frame of its lock, whatever
opened it (a button, the station, the app); the station's ``stair_light``
fires ``activated`` with every stair light frame.

Rings: the station ringing, and the outdoor unit a visitor rang at.

The station's ``ring`` fires at once with every press. The unit's
``doorbell`` fires when the agent has named the call's unit, with the same
call id: on ``call.caller_identified``, or at once for a press whose unit is
known. A press during a live call is the same call and rings both again. A unit the station had not listed fires when its entity is added
(docs/dev/multi-outdoor-units.md).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from homeassistant.components.event import (
    DoorbellEventType,
    EventDeviceClass,
    EventEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .agent_contracts import Call, OutdoorUnit
from .const import EVENT_AGENT_EVENT_RECEIVED
from .entity import C300XEntity, supports_capability
from .entry_types import BticinoC300XConfigEntry
from .event_payload import agent_event_key
from .unit_entity import C300XUnitEntity, async_track_outdoor_units
from .video import resolve_doorbell_camera_entity_id

if TYPE_CHECKING:
    from homeassistant.core import Event

PARALLEL_UPDATES = 0
DOOR_OPENED = "opened"
STAIR_LIGHT_ACTIVATED = "activated"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the station's ring and stair light, and each outdoor unit's ring and door."""

    rings = supports_capability(entry, "doorbell_events")
    doors = supports_capability(entry, "locks")
    entities: list[EventEntity] = []
    if rings:
        entities.append(C300XStationRingEventEntity(entry))
    if supports_capability(entry, "stair_light"):
        entities.append(C300XStairLightEventEntity(entry))
    if entities:
        async_add_entities(entities)
    if not (rings or doors):
        return

    def build(unit: OutdoorUnit) -> list[EventEntity]:
        unit_entities: list[EventEntity] = []
        if rings:
            unit_entities.append(C300XUnitDoorbellEventEntity(entry, unit))
        if doors:
            unit_entities.append(C300XUnitDoorEventEntity(entry, unit))
        return unit_entities

    async_track_outdoor_units(hass, entry, async_add_entities, build)


class _StationFrameEvent(EventEntity):
    """Fires one event type for one agent event of this entry."""

    _attr_should_poll = False
    _entry: BticinoC300XConfigEntry
    _agent_event_key: str

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.hass.bus.async_listen(EVENT_AGENT_EVENT_RECEIVED, self._agent_event))

    @callback
    def _agent_event(self, event: Event) -> None:
        data = event.data
        if data.get("entry_id") != self._entry.entry_id or agent_event_key(data) != self._agent_event_key:
            return
        attributes = self._frame_attributes(data)
        if attributes is not None:
            self._trigger_event(self._attr_event_types[0], attributes)
            self.async_write_ha_state()

    def _frame_attributes(self, data: Mapping[str, Any]) -> dict[str, Any] | None:
        raise NotImplementedError


class C300XUnitDoorEventEntity(_StationFrameEvent, C300XUnitEntity):
    """This outdoor unit's door was opened, by whatever opened it."""

    _attr_event_types = [DOOR_OPENED]
    _attr_translation_key = "door"
    _agent_event_key = "door_unlock_started"

    def __init__(self, entry: BticinoC300XConfigEntry, unit: OutdoorUnit) -> None:
        C300XUnitEntity.__init__(self, entry, unit, "door_event")

    def _frame_attributes(self, data: Mapping[str, Any]) -> dict[str, Any] | None:
        # The agent names the unit of the lock's address; call_id is set
        # while the unit has a live call.
        if data.get("unit") != self.unit_id:
            return None
        return {"call_id": data.get("call_id")}


class C300XStairLightEventEntity(_StationFrameEvent, C300XEntity):
    """The stair light was switched on, from the station, the app or Home Assistant."""

    _attr_event_types = [STAIR_LIGHT_ACTIVATED]
    _attr_translation_key = "stair_light"
    _agent_event_key = "stair_light_activated"

    def __init__(self, entry: BticinoC300XConfigEntry) -> None:
        C300XEntity.__init__(self, entry, "stair_light_event")

    def _frame_attributes(self, data: Mapping[str, Any]) -> dict[str, Any] | None:
        frame = data.get("data")
        return {"address": frame.get("address") if isinstance(frame, Mapping) else None}


class _RingEvent(EventEntity):
    """Rings with their call id, from the agent events on the bus."""

    _attr_device_class = EventDeviceClass.DOORBELL
    _attr_event_types = [DoorbellEventType.RING]
    _attr_should_poll = False
    _entry: BticinoC300XConfigEntry

    def _init_ring(self) -> None:
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
        if not isinstance(call_id, str):
            return
        attributes = self._ring_attributes(agent_event_key(data), data)
        if attributes is not None:
            self._ring(call_id, attributes, data.get("event_at"))

    def _ring(self, call_id: str, attributes: dict[str, Any], ring_at: Any) -> None:
        self._last_call_id = call_id
        self._last_ring_at = ring_at
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
        return {"unit": data.get("unit")}


class C300XUnitDoorbellEventEntity(_RingEvent, C300XUnitEntity):
    """A visitor rang at this outdoor unit."""

    _attr_translation_key = "doorbell_event"

    def __init__(self, entry: BticinoC300XConfigEntry, unit: OutdoorUnit) -> None:
        C300XUnitEntity.__init__(self, entry, unit, "doorbell")
        self._init_ring()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._claim_rings()

    @callback
    def _claim_rings(self) -> None:
        """Listen for this unit's rings, and fire those that came before."""

        registry = self._calls
        if registry is None:
            return
        unit_id = self.unit_id
        registry.ring_listeners.add(unit_id)
        self.async_on_remove(lambda: registry.ring_listeners.discard(unit_id))
        for call in registry.take_waiting_rings(unit_id):
            self._ring(call.call_id, self._call_attributes(call), dt_util.utcnow().isoformat())

    def _ring_attributes(self, key: str | None, data: Mapping[str, Any]) -> dict[str, Any] | None:
        # call_sync names the unit that rings, once per unit and press.
        if data.get("ring_unit_id") != self.unit_id:
            return None
        registry = self._calls
        return self._call_attributes(registry.call(data["call_id"]) if registry is not None else None)

    def _call_attributes(self, call: Call | None) -> dict[str, Any]:
        return {
            "unit": self.unit_id,
            "unit_name": self._unit.name or None,
            "attribution": call.attribution if call is not None else None,
        }
