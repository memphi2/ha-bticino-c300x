"""Bit rate and frame rate of the high-resolution camera stream."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfDataRate
from homeassistant.exceptions import HomeAssistantError

from .api import C300XAgentApiError
from .entity import C300XEntity
from .entry_types import BticinoC300XConfigEntry


class C300XCameraQualityNumber(C300XEntity, NumberEntity):
    """One value the device uses for its high-resolution camera stream.

    The device keeps it in a settings file that it reads when it starts, so a
    new value is saved at once and used after the next device restart; the
    attribute ``restart_required`` says when one is pending. The agent offers
    it only where the firmware has a high-resolution stream (not on 3.0.x).
    """

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

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
        self._restart_required: bool | None = None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Tell whether the saved value still waits for a device restart."""

        return {"restart_required": self._restart_required}

    async def async_set_native_value(self, value: float) -> None:
        """Save the value on the device."""

        try:
            status = await self._entry.runtime_data.api.async_camera_quality(
                **{self._field: int(value)}
            )
        except C300XAgentApiError as err:
            raise HomeAssistantError("C300X camera quality change failed") from err
        self._apply_status(status)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Read the value from the device."""

        runtime = self._entry.runtime_data
        try:
            status = await runtime.api.async_camera_quality()
        except C300XAgentApiError:
            if self._entry.runtime_data is runtime:
                self._attr_available = False
            return
        if self._entry.runtime_data is runtime:
            self._apply_status(status)

    def _apply_status(self, status: Mapping[str, Any]) -> None:
        value = status.get(self._field)
        supported = status.get("supported") is True and _is_int(value)
        self._attr_available = supported
        self._attr_native_value = value if supported else None
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
