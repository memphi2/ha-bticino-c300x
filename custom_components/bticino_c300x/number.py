"""Number entities for BTicino C300X."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import C300XAgentApiError
from .const import EVENT_AGENT_EVENT_RECEIVED
from .entity import C300XEntity
from .event_payload import agent_event_key

if TYPE_CHECKING:
    from homeassistant.core import Event

PARALLEL_UPDATES = 1
_RINGER_VOLUME_MIN = 0
_RINGER_VOLUME_MAX = 10
_RINGER_VOLUME_STEP = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up C300X number entities."""

    entities: list[NumberEntity] = []
    if _supports_ringer_volume(entry):
        entities.append(C300XRingerVolumeNumber(entry))
    if entities:
        await _async_refresh_initial_states(entities)
        async_add_entities(entities)


class C300XRingerVolumeNumber(C300XEntity, NumberEntity):
    """Set the C300X ringer volume."""

    _attr_should_poll = False
    _attr_translation_key = "ringer_volume"
    _attr_native_min_value = _RINGER_VOLUME_MIN
    _attr_native_max_value = _RINGER_VOLUME_MAX
    _attr_native_step = _RINGER_VOLUME_STEP

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "ringer_volume")
        self._volume: int | None = None
        self._attr_available = True

    @property
    def native_value(self) -> int | None:
        """Return the current ringer volume."""

        return self._volume

    async def async_set_native_value(self, value: float) -> None:
        """Set the ringer volume."""

        volume = _coerce_active_ringer_volume(value)
        if volume is None:
            raise HomeAssistantError("Ringer volume must be between 0 and 10")
        try:
            status = await self._entry.runtime_data.api.async_set_ringer_volume(volume)
        except C300XAgentApiError as err:
            await self.async_update()
            self.async_write_ha_state()
            raise HomeAssistantError("C300X ringer volume update failed") from err
        self._apply_status(status)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Refresh ringer volume through the agent read-only endpoint."""

        try:
            status = await self._entry.runtime_data.api.async_ringer_status()
        except C300XAgentApiError:
            self._attr_available = False
            return
        self._apply_status(status)

    def _apply_status(self, status: Mapping[str, Any]) -> None:
        volume = _coerce_active_ringer_volume(status.get("volume"))
        self._volume = volume
        self._attr_available = volume is not None

    async def async_added_to_hass(self) -> None:
        """Subscribe to push state updates."""

        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(
                EVENT_AGENT_EVENT_RECEIVED,
                self._handle_agent_event,
            )
        )

    @callback
    def _handle_agent_event(self, event: Event) -> None:
        if event.data.get("entry_id") != self._entry.entry_id:
            return
        if agent_event_key(event.data) != "ringer_volume_changed":
            return
        volume = _coerce_active_ringer_volume(event.data.get("volume"))
        if volume is None:
            return
        self._volume = volume
        self._attr_available = True
        self.async_write_ha_state()


def _supports_ringer_volume(entry: ConfigEntry) -> bool:
    capabilities = getattr(entry.runtime_data, "capabilities", {})
    ringer = capabilities.get("ringer") if isinstance(capabilities, Mapping) else None
    return (
        isinstance(ringer, Mapping)
        and ringer.get("supported") is True
        and ringer.get("volume") is True
    )


def _coerce_active_ringer_volume(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not number.is_integer():
        return None
    volume = int(number)
    if _RINGER_VOLUME_MIN <= volume <= _RINGER_VOLUME_MAX:
        return volume
    return None


async def _async_refresh_initial_states(entities: list[NumberEntity]) -> None:
    for entity in entities:
        await cast(Any, entity).async_update()
