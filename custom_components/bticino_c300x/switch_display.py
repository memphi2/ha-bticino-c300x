"""Configuration switches for the original C300X display settings."""

from collections.abc import Mapping
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from .api_errors import C300XAgentApiError
from .const import EVENT_AGENT_EVENT_RECEIVED
from .entity import C300XEntity
from .entry_types import BticinoC300XConfigEntry
from .event_payload import agent_event_key


class C300XTouchToneSwitch(C300XEntity, SwitchEntity):
    """Control the stock touch sound with confirmed state and push updates."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "touch_tone"
    _attr_icon = "mdi:gesture-tap"

    def __init__(self, entry: BticinoC300XConfigEntry) -> None:
        super().__init__(entry, "touch_tone")
        self._attr_is_on = None
        self._attr_available = False

    def _apply(self, data: Mapping[str, Any]) -> None:
        value = data.get("enabled")
        self._attr_is_on = value if isinstance(value, bool) else None
        self._attr_available = data.get("available") is True and self._attr_is_on is not None

    async def async_update(self) -> None:
        try:
            self._apply(await self._entry.runtime_data.api.async_touch_tone_status())
        except C300XAgentApiError:
            self._attr_available = False

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, enabled: bool) -> None:
        try:
            self._apply(await self._entry.runtime_data.api.async_set_touch_tone(enabled))
        except C300XAgentApiError as err:
            await self.async_update()
            self.async_write_ha_state()
            raise HomeAssistantError("C300X touch tone could not be confirmed. Check the Display patch.") from err
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.hass.bus.async_listen(EVENT_AGENT_EVENT_RECEIVED, self._handle_event))

    @callback
    def _handle_event(self, event: Any) -> None:
        if event.data.get("entry_id") != self._entry.entry_id:
            return
        if agent_event_key(event.data) != "display_touch_tone_changed":
            return
        data = event.data.get("data")
        if isinstance(data, Mapping):
            self._apply(data)
            self.async_write_ha_state()
