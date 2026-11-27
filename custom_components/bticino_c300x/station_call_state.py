"""The station's own call state as a sensor on the station device.

bt_answering_machine reports it on the bus (``*#8**35*<code>*0*0##``); the
agent names it and Home Assistant seeds it from ``GET /api/v1/calls`` and
follows ``station.call_state``. A code without a known meaning, an agent
restart and a station that has not reported one yet read as unknown.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from ._api_calls import STATION_CALL_STATES
from .call_registry import SIGNAL_CALLS_CHANGED
from .call_sync import entry_call_registry
from .entity import C300XEntity
from .entry_types import BticinoC300XConfigEntry


class C300XStationCallStateSensor(C300XEntity, SensorEntity):
    """idle, setup, ringing, viewing, waiting, conversation, answering_machine, greeting or recording."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(STATION_CALL_STATES)
    _attr_should_poll = False
    _attr_translation_key = "station_call_state"

    def __init__(self, entry: BticinoC300XConfigEntry) -> None:
        super().__init__(entry, "station_call_state")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def changed(entry_id: str) -> None:
            if entry_id == self._entry.entry_id:
                self.async_write_ha_state()

        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_CALLS_CHANGED, changed))

    @property
    def native_value(self) -> str | None:
        registry = entry_call_registry(self._entry)
        state = registry.station_state if registry is not None else None
        return state.state if state is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The station's raw code, also for a code without a known meaning."""

        registry = entry_call_registry(self._entry)
        state = registry.station_state if registry is not None else None
        return {"code": state.code if state is not None else None}
