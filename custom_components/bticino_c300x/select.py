"""Select entities for BTicino C300X."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import C300XAgentApiError
from .const import (
    EVENT_AGENT_EVENT_RECEIVED,
    SMARTPHONE_FORWARDING_MODES,
    SMARTPHONE_FORWARDING_STATE_UNPROVISIONED,
)
from .entity import C300XEntity, supports_capability
from .entry_types import BticinoC300XConfigEntry
from .event_payload import agent_event_key
from .forwarding import coerce_forwarding_mode_state

if TYPE_CHECKING:
    from homeassistant.core import Event

PARALLEL_UPDATES = 1

_FORWARDING_STATE_LABELS = {
    "enabled": "Smartphone",
    "homeassistant": "Home Assistant",
    "blocked": "Blocked",
    SMARTPHONE_FORWARDING_STATE_UNPROVISIONED: "Unprovisioned",
}
_FORWARDING_OPTION_LABELS = {
    mode: label
    for mode, label in _FORWARDING_STATE_LABELS.items()
    if mode in SMARTPHONE_FORWARDING_MODES
}
_FORWARDING_MODE_BY_LABEL = {
    label: mode for mode, label in _FORWARDING_OPTION_LABELS.items()
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up C300X select entities."""

    entities: list[SelectEntity] = []
    if supports_capability(entry, "smartphone_forwarding"):
        entities.append(C300XSmartphoneForwardingModeSelect(entry))
    if entities:
        await _async_refresh_initial_states(entities)
        async_add_entities(entities)


class C300XSmartphoneForwardingModeSelect(C300XEntity, SelectEntity):
    """Select the C300X smartphone forwarding mode."""

    _attr_should_poll = False
    _attr_translation_key = "smartphone_forwarding_mode"
    _attr_options = list(_FORWARDING_OPTION_LABELS.values())

    def __init__(self, entry: BticinoC300XConfigEntry) -> None:
        super().__init__(entry, "smartphone_forwarding_mode")
        self._mode: int | None = None
        self._state = "unknown"
        self._attr_available = True

    @property
    def current_option(self) -> str | None:
        """Return the current forwarding mode."""

        return _FORWARDING_STATE_LABELS.get(self._state)

    @property
    def extra_state_attributes(self) -> dict[str, str | int | None]:
        """Return raw forwarding state metadata."""

        return {"mode": self._mode, "state": self._state}

    async def async_select_option(self, option: str) -> None:
        """Set the forwarding mode."""

        mode = _FORWARDING_MODE_BY_LABEL.get(option, option)
        if mode not in SMARTPHONE_FORWARDING_MODES:
            return
        status = await self._entry.runtime_data.api.async_set_smartphone_forwarding_mode(
            mode
        )
        self._apply_status(status)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Refresh forwarding state through the active read-only endpoint."""

        try:
            status = await self._entry.runtime_data.api.async_smartphone_forwarding_status()
        except C300XAgentApiError:
            self._attr_available = False
            return
        self._apply_status(status)

    def _apply_status(self, status: Mapping[str, Any]) -> None:
        mode = status.get("mode")
        state = status.get("state", "unknown")
        self._mode = mode if isinstance(mode, int) else None
        self._state = state if isinstance(state, str) else "unknown"
        self._entry.runtime_data.event_state.smartphone_forwarding_mode = self._state
        self._attr_available = True

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
        event_type = agent_event_key(event.data) or ""
        if not event_type.startswith("smartphone_forwarding_"):
            return
        forwarding = _normalize_smartphone_forwarding_event(event.data)
        state = forwarding.get("state")
        mode = forwarding.get("mode")
        self._state = state if isinstance(state, str) else "unknown"
        self._mode = mode if isinstance(mode, int) else None
        self._entry.runtime_data.event_state.smartphone_forwarding_mode = self._state
        self._attr_available = True
        self.async_write_ha_state()


def _normalize_smartphone_forwarding_event(
    payload: Mapping[str, Any],
) -> dict[str, str | int | None]:
    return coerce_forwarding_mode_state(payload.get("mode"), payload.get("state"))


async def _async_refresh_initial_states(entities: list[SelectEntity]) -> None:
    for entity in entities:
        await cast(Any, entity).async_update()
