"""Shared entity helpers for BTicino C300X."""

from __future__ import annotations

from collections.abc import Mapping

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, Entity

from .capabilities import capability_is_supported
from .const import CONF_VIDEO_ENABLED, DOMAIN, SIGNAL_CONNECTION_STATE_CHANGED
from .entry_config import entry_config_value


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
    def device_info(self) -> DeviceInfo:
        """Return device metadata shown in the Home Assistant device page."""

        return _device_info(self._entry)

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


def entry_video_enabled(entry: ConfigEntry) -> bool:
    """Return the effective HA video setting for this entry."""

    return bool(entry_config_value(entry, CONF_VIDEO_ENABLED, False))


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return C300X device metadata without extra device reads."""

    info: dict[str, object] = {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "manufacturer": "BTicino",
        "model": "Classe 300X",
        "name": entry.title,
    }
    firmware = _agent_info_string(entry, "firmware")
    if firmware is not None:
        info["sw_version"] = firmware
    return DeviceInfo(**info)


def _agent_info_string(entry: ConfigEntry, key: str) -> str | None:
    """Return a non-empty string value from cached agent setup metadata."""

    runtime_data = getattr(entry, "runtime_data", None)
    agent_info = getattr(runtime_data, "agent_info", {})
    if not isinstance(agent_info, Mapping):
        return None
    value = agent_info.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None
