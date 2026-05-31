"""Shared entity helpers for BTicino C300X."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, Entity

from .capabilities import capability_is_supported
from .const import CONF_VIDEO_ENABLED, DOMAIN, SIGNAL_CONNECTION_STATE_CHANGED


class C300XEntity(Entity):
    """Base entity tied to one C300X config entry."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, key: str) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="BTicino",
            model="Classe 300X",
            name=entry.title,
        )

    @property
    def available(self) -> bool:
        """Return false when the device agent is outside reconnect grace."""

        connection_state = getattr(self._entry.runtime_data, "connection_state", None)
        if connection_state is not None and not connection_state.available:
            return False
        return bool(getattr(self, "_attr_available", True))

    async def async_added_to_hass(self) -> None:
        """Update availability immediately when the agent connection changes."""

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_CONNECTION_STATE_CHANGED,
                self._handle_c300x_connection_state_changed,
            )
        )

    @callback
    def _handle_c300x_connection_state_changed(self, entry_id: str) -> None:
        if entry_id == self._entry.entry_id:
            self.async_write_ha_state()


def supports_capability(entry: ConfigEntry, capability: str) -> bool:
    """Return true when the device agent reports support for a capability."""

    capabilities = getattr(entry.runtime_data, "capabilities", {})
    return capability_is_supported(capabilities, capability)


def entry_config_value(entry: ConfigEntry, key: str, default: Any = None) -> Any:
    """Return an option override when present, otherwise setup data."""

    if key in entry.options:
        value = entry.options[key]
        if value in (None, ""):
            return default
        if isinstance(value, str) and not value.strip():
            return default
        return value
    return entry.data.get(key, default)


def entry_video_enabled(entry: ConfigEntry) -> bool:
    """Return the effective HA video setting for this entry."""

    return bool(entry_config_value(entry, CONF_VIDEO_ENABLED, False))
