"""Camera resolution select for BTicino C300X."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .api import C300XAgentApiError
from .entity import C300XEntity
from .entry_types import BticinoC300XConfigEntry

CAMERA_RESOLUTION_OPTIONS = ["high", "low"]


class C300XCameraResolutionSelect(C300XEntity, SelectEntity):
    """Choose the camera stream the agent requests: high or low resolution.

    The agent offers it only where the firmware sends both streams on; on
    3.0.x it is fixed to low and this entity is not created. A change applies
    from the next stream that starts.
    """

    _attr_should_poll = False
    _attr_translation_key = "camera_resolution"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = CAMERA_RESOLUTION_OPTIONS

    def __init__(self, entry: BticinoC300XConfigEntry) -> None:
        super().__init__(entry, "camera_resolution")
        self._attr_current_option = None
        self._attr_available = True

    async def async_select_option(self, option: str) -> None:
        """Save the resolution on the device."""

        if option not in CAMERA_RESOLUTION_OPTIONS:
            return
        try:
            status = await self._entry.runtime_data.api.async_camera_resolution(
                high_resolution=option == "high"
            )
        except C300XAgentApiError as err:
            raise HomeAssistantError("C300X camera resolution change failed") from err
        self._apply_status(status)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Read the resolution from the device."""

        runtime = self._entry.runtime_data
        try:
            status = await runtime.api.async_camera_resolution()
        except C300XAgentApiError:
            if self._entry.runtime_data is runtime:
                self._attr_available = False
            return
        if self._entry.runtime_data is runtime:
            self._apply_status(status)

    def _apply_status(self, status: Mapping[str, Any]) -> None:
        high = status.get("high_resolution")
        self._attr_current_option = (
            ("high" if high else "low") if isinstance(high, bool) else None
        )
        self._attr_available = True
