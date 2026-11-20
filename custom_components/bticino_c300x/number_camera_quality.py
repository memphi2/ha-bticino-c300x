"""Bit rate and frame rate of the high-resolution camera stream."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfDataRate
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)

from .api import C300XAgentApiError
from .const import DOMAIN, SIGNAL_CONNECTION_STATE_CHANGED
from .entity import C300XEntity
from .entry_types import BticinoC300XConfigEntry

SIGNAL_CAMERA_QUALITY = f"{DOMAIN}_camera_quality"


class C300XCameraQualityNumber(C300XEntity, NumberEntity):
    """One value the device uses for its high-resolution camera stream.

    The device reads it from a settings file when it starts. Like the audio
    codec select, a change writes that file and restarts the device; the
    number shows what the device runs and, while a restart is outstanding,
    the saved value as ``pending_value``. The agent offers it only where the
    firmware has a high-resolution stream (not on 3.0.x).
    """

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _refresh_on_reconnect = True

    def __init__(
        self, entry: BticinoC300XConfigEntry, key: str, field: str, unit: str,
        minimum: int, maximum: int, step: int,
    ) -> None:
        super().__init__(entry, key)
        self._attr_translation_key = key
        self._field = field
        self._limit = "bitrate" if field == "bitrate_kbps" else "fps"
        self._attr_native_unit_of_measurement = unit
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_native_step = step
        self._attr_native_value = None
        self._attr_available = True
        self._pending: int | None = None
        self._restart_required: bool | None = None
        self._refresh_task: asyncio.Task[None] | None = None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The saved value while the device still runs the old one."""

        return {"restart_required": self._restart_required, "pending_value": self._pending}

    async def async_added_to_hass(self) -> None:
        """Follow the other camera number and the restart of the device."""

        await super().async_added_to_hass()
        self.async_on_remove(self._cancel_refresh)
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_CAMERA_QUALITY, self._handle_status)
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_CONNECTION_STATE_CHANGED, self._handle_connection
            )
        )

    async def async_set_native_value(self, value: float) -> None:
        """Save the value on the device, which restarts to use it."""

        api = self._entry.runtime_data.api
        try:
            status = await api.async_camera_quality(**{self._field: int(value)})
        except C300XAgentApiError as err:
            # A refused or failed write may still have changed the file.
            await self.async_update()
            self.async_write_ha_state()
            raise HomeAssistantError("C300X camera quality change failed") from err
        self._share(status)

    async def async_update(self) -> None:
        """Read the values from the device."""

        runtime = self._entry.runtime_data
        try:
            status = await runtime.api.async_camera_quality()
        except C300XAgentApiError:
            if self._entry.runtime_data is runtime:
                self._attr_available = False
            return
        if self._entry.runtime_data is runtime:
            self._apply_status(status)

    def _share(self, status: Mapping[str, Any]) -> None:
        self._apply_status(status)
        self.async_write_ha_state()
        if self.hass is not None:
            async_dispatcher_send(self.hass, SIGNAL_CAMERA_QUALITY, self._entry.entry_id, status)

    @callback
    def _handle_status(self, entry_id: str, status: Mapping[str, Any]) -> None:
        if entry_id == self._entry.entry_id:
            self._apply_status(status)
            self.async_write_ha_state()

    @callback
    def _handle_connection(self, entry_id: str) -> None:
        # The device restarts after a change; it may come back inside the
        # reconnect grace, so read again on every connection change while
        # a restart is outstanding, not only after a gap.
        if (
            entry_id != self._entry.entry_id
            or not self._restart_required
            or not self._entry.runtime_data.connection_state.available
            or (self._refresh_task is not None and not self._refresh_task.done())
        ):
            return
        self._refresh_task = self.hass.async_create_task(self._async_refresh())

    async def _async_refresh(self) -> None:
        await self.async_update()
        self.async_write_ha_state()

    @callback
    def _cancel_refresh(self) -> None:
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            self._refresh_task = None

    def _apply_status(self, status: Mapping[str, Any]) -> None:
        saved = status.get(self._field)
        running = status.get(f"running_{self._field}")
        supported = status.get("supported") is True and _is_int(saved)
        self._attr_available = supported
        if not supported:
            self._attr_native_value = None
            self._pending = None
            self._restart_required = None
            return
        # Zero: the agent does not know what the device started with.
        shown = running if _is_int(running) and running > 0 else saved
        self._attr_native_value = shown
        self._pending = saved if saved != shown else None
        restart = status.get("restart_required")
        self._restart_required = restart if isinstance(restart, bool) else None
        for limit, attribute in (("min", "_attr_native_min_value"), ("max", "_attr_native_max_value")):
            bound = status.get(f"{self._limit}_{limit}")
            if _is_int(bound):
                setattr(self, attribute, bound)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def camera_quality_numbers(entry: BticinoC300XConfigEntry) -> list[NumberEntity]:
    """The two numbers; the limits are replaced by what the agent reports."""

    return [
        C300XCameraQualityNumber(
            entry, "camera_bitrate", "bitrate_kbps", UnitOfDataRate.KILOBITS_PER_SECOND, 300, 3000, 50
        ),
        C300XCameraQualityNumber(entry, "camera_frame_rate", "fps", "fps", 5, 25, 1),
    ]
