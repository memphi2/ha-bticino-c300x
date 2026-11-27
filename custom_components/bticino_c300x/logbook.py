"""Logbook lines for the integration's bus events, which have no entity.

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
from .const import DOMAIN, EVENT_ACTION_RECEIVED, EVENT_AGENT_EVENT_RECEIVED

ACTION_LABELS = {
    "en": "Action run: {action}",
    "de": "Aktion ausgeführt: {action}",
    "it": "Azione eseguita: {action}",
    "fr": "Action exécutée : {action}",
    "es": "Acción ejecutada: {action}",
}


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, str]]], None],
) -> None:
    """Describe the station events and the actions Home Assistant ran."""

    @callback
    def describe_agent_event(event: Event) -> dict[str, str]:
        key = str(event.data.get("event_type") or "")
        return {
            LOGBOOK_ENTRY_NAME: _source_name(hass, event.data),
            LOGBOOK_ENTRY_MESSAGE: event_label(key, hass.config.language) or key,
        }

    @callback
    def describe_action(event: Event) -> dict[str, str]:
        language = str(hass.config.language or "").split("-", 1)[0].lower()
        text = ACTION_LABELS.get(language, ACTION_LABELS["en"])
        return {
            LOGBOOK_ENTRY_NAME: _source_name(hass, event.data),
            LOGBOOK_ENTRY_MESSAGE: text.format(action=event.data.get("action_id")),
        }

    async_describe_event(DOMAIN, EVENT_AGENT_EVENT_RECEIVED, describe_agent_event)
    async_describe_event(DOMAIN, EVENT_ACTION_RECEIVED, describe_action)


def _source_name(hass: HomeAssistant, data: Mapping[str, Any]) -> str:
    """The device's name, else the station entry's title."""

    device_id = data.get("device_id")
    device = dr.async_get(hass).async_get(device_id) if isinstance(device_id, str) else None
    if device is not None and (device.name_by_user or device.name):
        return str(device.name_by_user or device.name)
    entry_id = data.get("entry_id")
    entry = hass.config_entries.async_get_entry(entry_id) if isinstance(entry_id, str) else None
    return entry.title if entry is not None else "BTicino"
