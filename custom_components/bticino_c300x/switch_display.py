"""Configuration switches for the original C300X display settings."""

from collections.abc import Mapping
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .api_errors import C300XAgentApiError
from .const import EVENT_AGENT_EVENT_RECEIVED, SIGNAL_SETTING_STATE
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
        self._state_generation = 0

    def _apply(self, data: Mapping[str, Any]) -> None:
        value = data.get("enabled")
        self._attr_is_on = value if isinstance(value, bool) else None
        self._attr_available = data.get("available") is True and self._attr_is_on is not None

    async def async_update(self) -> None:
        generation = self._state_generation
        try:
            status = await self._entry.runtime_data.api.async_touch_tone_status()
        except C300XAgentApiError:
            if generation == self._state_generation:
                self._attr_available = False
        else:
            # A push or acknowledged write supersedes reads already in flight.
            if generation == self._state_generation:
                self._apply(status)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, enabled: bool) -> None:
        generation = self._state_generation
        try:
            status = await self._entry.runtime_data.api.async_set_touch_tone(enabled)
        except C300XAgentApiError as err:
            if generation == self._state_generation:
                await self.async_update()
            self.async_write_ha_state()
            raise HomeAssistantError("C300X touch tone could not be confirmed. Check the Display patch.") from err
        if generation == self._state_generation:
            self._state_generation += 1
            self._apply(status)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.hass.bus.async_listen(EVENT_AGENT_EVENT_RECEIVED, self._handle_event))
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_SETTING_STATE, self._handle_snapshot,
        ))
        # Initial platform reads precede subscription; recover changes in that gap.
        await self.async_update()

    @callback
    def _handle_snapshot(self, entry_id: str, event_type: str, data: Any) -> None:
        if event_type == "display_touch_tone_changed":
            self._handle_state(entry_id, data)

    @callback
    def _handle_state(self, entry_id: str, data: Any) -> None:
        if entry_id != self._entry.entry_id or not isinstance(data, Mapping):
            return
        self._state_generation += 1
        self._apply(data)
        self.async_write_ha_state()

    @callback
    def _handle_event(self, event: Any) -> None:
        if event.data.get("entry_id") != self._entry.entry_id:
            return
        if agent_event_key(event.data) != "display_touch_tone_changed":
            return
        self._handle_state(self._entry.entry_id, event.data.get("data"))
