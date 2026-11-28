"""Call sensor, door button, door contact, camera and last visitor image of an outdoor unit."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
from homeassistant.components.button import ButtonEntity
from homeassistant.components.camera import Camera
from homeassistant.components.image import ImageEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .agent_contracts import OutdoorUnit
from .api_errors import C300XAgentApiError
from .call_sync import entry_call_registry
from .capabilities import locks_for_capabilities
from .config_snapshots import snapshot_options
from .entry_types import BticinoC300XConfigEntry
from .unit_entity import C300XUnitEntity

_LOGGER = logging.getLogger(__name__)

CALL_STATES = ["idle", "ringing", "answered", "viewing"]


class C300XUnitCallSensor(C300XUnitEntity, SensorEntity):
    """What this outdoor unit is doing: idle, ringing, answered or viewing."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = CALL_STATES
    _attr_should_poll = False
    _attr_translation_key = "call"

    def __init__(self, entry: BticinoC300XConfigEntry, unit: OutdoorUnit) -> None:
        C300XUnitEntity.__init__(self, entry, unit, "call")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._listen_calls(self.async_write_ha_state)

    def _state(self) -> tuple[str, str | None]:
        registry = self._calls
        return registry.unit_state(self.unit_id) if registry is not None else ("idle", None)

    @property
    def native_value(self) -> str:
        return self._state()[0]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state, call_id = self._state()
        registry = self._calls
        call = registry.call(call_id) if registry is not None else None
        return {
            "call_id": call_id,
            "attribution": call.attribution if call is not None else None,
            "answered_by": call.answered_by if call is not None else None,
        }


class C300XUnitDoorContactBinarySensor(C300XUnitEntity, BinarySensorEntity):
    """This outdoor unit's door contact: on while the door is open.

    The agent reports it from the station's door frames; after an agent
    restart the state is unknown until the next frame.
    """

    _attr_device_class = BinarySensorDeviceClass.DOOR
    _attr_should_poll = False
    _attr_translation_key = "door_contact"

    def __init__(self, entry: BticinoC300XConfigEntry, unit: OutdoorUnit) -> None:
        C300XUnitEntity.__init__(self, entry, unit, "door_contact")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from .call_registry import SIGNAL_DOORS_CHANGED

        @callback
        def changed(entry_id: str) -> None:
            if entry_id == self._entry.entry_id:
                self.async_write_ha_state()

        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_DOORS_CHANGED, changed))

    @property
    def is_on(self) -> bool | None:
        registry = self._calls
        unit = registry.unit(self.unit_id) if registry is not None else None
        state = unit.door.state if unit is not None and unit.door is not None else None
        return None if state is None else state == "open"


def door_lock_unit(entry: BticinoC300XConfigEntry, activation: Mapping[str, Any]) -> str | None:
    """The known outdoor unit whose door lock this activation is, else None.

    That unit's door button opens the lock and has its name; the lock gets
    no button of its own on the station.
    """

    registry = entry_call_registry(entry)
    unit = activation.get("unit")
    if activation.get("type") != "lock" or registry is None or unit not in registry.units:
        return None
    return str(unit)


def _lock_name(entry: BticinoC300XConfigEntry, unit: OutdoorUnit) -> str | None:
    """The name of this unit's lock: its activation's, as on the station's display.

    Else the name the agent reports for the lock's address.
    """

    activations = getattr(entry.runtime_data, "activations", None)
    items = activations.get("items") if isinstance(activations, dict) else None
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and item.get("name") and door_lock_unit(entry, item) == unit.id:
            return str(item["name"])
    locks = locks_for_capabilities(getattr(entry.runtime_data, "capabilities", {}))
    return next((lock["name"] for lock in locks if lock["id"] == unit.lock_where), None)


class C300XUnitDoorButton(C300XUnitEntity, ButtonEntity):
    """Opens the lock of this outdoor unit."""

    _attr_translation_key = "door"

    def __init__(self, entry: BticinoC300XConfigEntry, unit: OutdoorUnit) -> None:
        C300XUnitEntity.__init__(self, entry, unit, "door")
        name = _lock_name(entry, unit)
        # Door unlock without a name, and for a lock with the unit's own
        # name: the displayed name starts with the unit's.
        if name and name != unit.name:
            self._attr_name = name

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The same for every unit: its lock's bus address and that lock's name, else the unit's."""

        registry = self._calls
        unit = registry.units.get(self.unit_id, self._unit) if registry is not None else self._unit
        return {"lock_address": unit.lock_where, "lock_name": _lock_name(self._entry, unit) or unit.name or None}

    async def async_press(self) -> None:
        from .executor import async_unlock_door
        from .use_cases.common import raise_agent_command_failed

        await raise_agent_command_failed(
            async_unlock_door(self.hass, self._entry, self.unit_id), entry=self._entry,
        )


class C300XUnitCamera(C300XUnitEntity, Camera):
    """A unit without on-demand video: its live picture while it calls, else its last visitor.

    The station switches the picture to the calling unit, so a still taken
    while this unit has the current call shows it. Video of a unit other
    than the default one comes later with its own concept.
    """

    _attr_should_poll = False
    _attr_translation_key = "unit_camera"

    def __init__(self, entry: BticinoC300XConfigEntry, unit: OutdoorUnit) -> None:
        Camera.__init__(self)
        C300XUnitEntity.__init__(self, entry, unit, "camera")
        self.content_type = "image/jpeg"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._listen_calls(self.async_write_ha_state)

    @property
    def is_streaming(self) -> bool:
        return self._has_current_call()

    def _has_current_call(self) -> bool:
        registry = self._calls
        call = registry.current_call if registry is not None else None
        return call is not None and call.unit == self.unit_id

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None,
    ) -> bytes | None:
        if self._has_current_call():
            try:
                content, _content_type = await self._entry.runtime_data.api.async_doorbell_snapshot(
                    *snapshot_options(self._entry).size,
                )
            except C300XAgentApiError as err:
                _LOGGER.debug("C300X live picture of unit %s failed: %s", self.unit_id, err)
            else:
                from .snapshot_capture import framebuffer_jpeg

                return await self.hass.async_add_executor_job(framebuffer_jpeg, content, _content_type, None)
        return await async_last_visitor_image(self.hass, self._entry, self.unit_id)


class C300XUnitLastVisitorImage(C300XUnitEntity, ImageEntity):
    """The latest kept image of a call at this outdoor unit."""

    _attr_content_type = "image/jpeg"
    _attr_should_poll = False
    _attr_translation_key = "last_visitor"

    def __init__(self, hass: HomeAssistant, entry: BticinoC300XConfigEntry, unit: OutdoorUnit) -> None:
        ImageEntity.__init__(self, hass)
        C300XUnitEntity.__init__(self, entry, unit, "last_visitor")
        self._visit_at: float | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from .visitor_journal import EVENT_JOURNAL_CHANGED

        @callback
        def changed(event: Any) -> None:
            if event.data.get("entry_id") == self._entry.entry_id:
                self._refresh()

        self.async_on_remove(self.hass.bus.async_listen(EVENT_JOURNAL_CHANGED, changed))
        from .snapshots import SIGNAL_SNAPSHOT_CHANGED

        @callback
        def snapshot_changed(entry_id: str) -> None:
            if entry_id == self._entry.entry_id:
                self._refresh()

        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_SNAPSHOT_CHANGED, snapshot_changed))
        self._refresh(write=False)

    @callback
    def _refresh(self, *, write: bool = True) -> None:
        visit = _latest_visit(self.hass, self._entry, self.unit_id)
        at = visit.get("at") if visit is not None else None
        if at == self._visit_at:
            return
        self._visit_at = at
        self._attr_image_last_updated = (
            datetime.fromtimestamp(at, UTC) if isinstance(at, (int, float)) else None
        )
        if write:
            self.async_write_ha_state()

    async def async_image(self) -> bytes | None:
        return await async_last_visitor_image(self.hass, self._entry, self.unit_id)


def _latest_visit(hass: HomeAssistant, entry: BticinoC300XConfigEntry, unit_id: str) -> dict[str, Any] | None:
    from .visitor_journal import get_journal

    journal = get_journal(hass, entry.entry_id)
    return journal.latest_unit_visit(unit_id) if journal is not None else None


async def async_last_visitor_image(
    hass: HomeAssistant, entry: BticinoC300XConfigEntry, unit_id: str,
) -> bytes | None:
    """The image of the latest visit at this unit that kept one, while retained."""

    from .snapshots import get_snapshots

    visit = _latest_visit(hass, entry, unit_id)
    manager = get_snapshots(hass, entry.entry_id)
    if visit is None or manager is None or manager.closed:
        return None
    name = visit["snapshot"]["name"]
    try:
        image: bytes | None = await manager.disk_job(
            manager.store.read, name, snapshot_options(entry).retention_days,
        )
    except (OSError, ValueError):
        return None
    return image
