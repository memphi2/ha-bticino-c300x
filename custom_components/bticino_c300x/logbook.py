"""Logbook lines for the station events on the bus, which have no entity.

Each line names the device the event belongs to (an outdoor unit or the
station) and says what happened in the language of Home Assistant. The
event's device_id assigns it to that device's logbook.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from homeassistant.components.logbook import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .capabilities import event_label
from .const import DOMAIN, EVENT_AGENT_EVENT_RECEIVED


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, str]]], None],
) -> None:
    """Describe the station events."""

    @callback
    def describe_agent_event(event: Event) -> dict[str, str]:
        key = str(event.data.get("event_type") or "")
        return {
            LOGBOOK_ENTRY_NAME: _source_name(hass, event.data),
            LOGBOOK_ENTRY_MESSAGE: event_label(key, hass.config.language) or key,
        }

    async_describe_event(DOMAIN, EVENT_AGENT_EVENT_RECEIVED, describe_agent_event)


def _source_name(hass: HomeAssistant, data: Mapping[str, Any]) -> str:
    """The device's name, else the station entry's title."""

    device_id = data.get("device_id")
    device = dr.async_get(hass).async_get(device_id) if isinstance(device_id, str) else None
    if device is not None and (device.name_by_user or device.name):
        return str(device.name_by_user or device.name)
    entry_id = data.get("entry_id")
    entry = hass.config_entries.async_get_entry(entry_id) if isinstance(entry_id, str) else None
    return entry.title if entry is not None else "BTicino"
