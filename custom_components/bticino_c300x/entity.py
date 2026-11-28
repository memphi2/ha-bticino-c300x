"""Shared entity helpers for BTicino C300X."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any, cast

from homeassistant.core import callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .capabilities import capability_is_supported
from .const import CONF_VIDEO_ENABLED, DOMAIN, SIGNAL_CONNECTION_STATE_CHANGED
from .device_profile import entry_profile
from .entry_config import entry_config_value as entry_config_value
from .entry_types import BticinoC300XConfigEntry
from .identity import station_device_identifier, station_mac, station_unique_id

if TYPE_CHECKING:
    from homeassistant.helpers.device_registry import DeviceInfo
else:
    from homeassistant.helpers.entity import DeviceInfo


def entry_entity_unique_id(entry: BticinoC300XConfigEntry, key: str) -> str:
    """Return the unique id this integration gives an entity of one entry.

    A registry lookup outside the entity layer needs the same formula, and a
    diverging copy makes it report a registered entity as unregistered.
    """

    return station_unique_id(entry, key)


class C300XEntity(Entity):
    """Base entity tied to one C300X config entry."""

    _attr_has_entity_name = True
    _refresh_on_reconnect = False

    def __init__(self, entry: BticinoC300XConfigEntry, key: str) -> None:
        self._entry = entry
        self._attr_unique_id = entry_entity_unique_id(entry, key)
        self._attr_device_info = _device_info(entry)
        self._last_connection_state_available = _connection_state_available(entry)
        self._reconnect_refresh_task: asyncio.Task[None] | None = None

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

        self.async_on_remove(self._cancel_reconnect_refresh)
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_CONNECTION_STATE_CHANGED,
                self._handle_c300x_connection_state_changed,
            )
        )

    @callback
    def _handle_c300x_connection_state_changed(self, entry_id: str) -> None:
        if entry_id != self._entry.entry_id:
            return
        current = _connection_state_available(self._entry)
        if (
            current is not False
            and (
                getattr(self, "_attr_available", True) is False
                or (
                    self._refresh_on_reconnect
                    and current is True
                    and self._last_connection_state_available is False
                )
            )
            and hasattr(self, "async_update")
            and (
                self._reconnect_refresh_task is None
                or self._reconnect_refresh_task.done()
            )
        ):
            # These entities do not poll and are marked unavailable by their own
            # failed read. The agent answered again, so ask it once more: nothing
            # else would bring them back until the device itself reports a change.
            # Opted-in entities also recover missed pushes after a connection gap.
            self._reconnect_refresh_task = self.hass.async_create_background_task(
                self._async_refresh_after_reconnect(),
                f"{DOMAIN}_refresh_after_reconnect_{self._attr_unique_id}",
            )
        if current == self._last_connection_state_available:
            return
        self._last_connection_state_available = current
        self.async_write_ha_state()

    @callback
    def _cancel_reconnect_refresh(self) -> None:
        if self._reconnect_refresh_task is not None:
            self._reconnect_refresh_task.cancel()
            self._reconnect_refresh_task = None

    async def _async_refresh_after_reconnect(self) -> None:
        await cast(Any, self).async_update()
        self.async_write_ha_state()


def supports_capability(entry: BticinoC300XConfigEntry, capability: str) -> bool:
    """Return true when the device agent reports support for a capability."""

    capabilities = getattr(entry.runtime_data, "capabilities", {})
    return capability_is_supported(capabilities, capability)


def supports_capability_if_known(entry: BticinoC300XConfigEntry, capability: str) -> bool:
    """Like supports_capability, but true while the agent has reported no capabilities."""

    capabilities = getattr(getattr(entry, "runtime_data", None), "capabilities", None)
    if not isinstance(capabilities, dict) or not capabilities:
        return True
    return supports_capability(entry, capability)


def entry_video_enabled(entry: BticinoC300XConfigEntry) -> bool:
    """Return the effective HA video setting for this entry."""

    return bool(entry_config_value(entry, CONF_VIDEO_ENABLED, False))


def _connection_state_available(entry: BticinoC300XConfigEntry) -> bool | None:
    runtime_data = getattr(entry, "runtime_data", None)
    connection_state = getattr(runtime_data, "connection_state", None)
    value = getattr(connection_state, "available", None)
    return value if isinstance(value, bool) else None


def _device_info(entry: BticinoC300XConfigEntry) -> DeviceInfo:
    """Return C300X device metadata without extra device reads.

    Built in one call: from Home Assistant 2026.11 a device info is a
    dataclass, and setting a field on it afterwards is deprecated. The
    fields are left out where the station reports nothing, which neither the
    TypedDict of older versions nor the dataclass can type.
    """

    build = cast("Callable[..., DeviceInfo]", DeviceInfo)
    return build(**station_device_fields(entry))


def station_device_fields(entry: BticinoC300XConfigEntry) -> dict[str, Any]:
    """The station device's fields; a value the station does not report leaves its field out."""

    fields: dict[str, Any] = {
        "identifiers": {station_device_identifier(entry)},
        "manufacturer": "BTicino",
        "model": "Classe 100X" if entry_profile(entry).is_c100x else "Classe 300X",
        "name": entry.title,
    }
    mac = station_mac(entry)
    if mac is not None:
        fields["connections"] = {(CONNECTION_NETWORK_MAC, mac)}
    # What the station reports about itself is shown as it is.
    for field, key in (("sw_version", "firmware"), ("hw_version", "board"), ("model_id", "article")):
        value = _agent_info_string(entry, key)
        if value is not None:
            fields[field] = value
    return fields


def _agent_info_string(entry: BticinoC300XConfigEntry, key: str) -> str | None:
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


async def async_refresh_initial_states(entities: Iterable[Entity]) -> None:
    """Populate entity states once during setup without enabling periodic polling."""

    for entity in entities:
        await cast(Any, entity).async_update()
