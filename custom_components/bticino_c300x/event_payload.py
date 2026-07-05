"""Helpers for C300X agent event payloads."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .capabilities import event_label
from .const import DASHBOARD_ENTITY_DOOR_UNLOCK
from .event_types import agent_event_key as _agent_event_key

ACTION_EVENT_KEYS = {
    DASHBOARD_ENTITY_DOOR_UNLOCK: "door_unlock_started",
}


def agent_event_key(data: Mapping[str, Any]) -> str | None:
    """Return the stable machine key from a agent event payload."""

    return _agent_event_key(data)


def agent_event_name(
    data: Mapping[str, Any],
    language: str | None = None,
) -> str | None:
    """Return the human-readable name from a agent event payload."""

    localized = _localized_label(data, language)
    if localized:
        return localized

    for key in ("event_value", "event_name", "event_label"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return event_label(value, language) or value

    event_key = agent_event_key(data)
    return event_label(event_key, language) or event_key


def agent_event_display_data(
    data: Mapping[str, Any],
    language: str | None = None,
) -> dict[str, Any]:
    """Return payload data with display fields separated from stable keys."""

    result = dict(data)
    event_key = agent_event_key(result)
    event_name = agent_event_name(result, language)

    if event_key:
        result["event_key"] = event_key
        result["event_type_key"] = event_key
    if event_name:
        result["event"] = event_name
        result["event_type"] = event_name
        result["event_value"] = event_name
        result["event_name"] = event_name
    return result


def action_event_key(data: Mapping[str, Any]) -> str | None:
    """Return the HA event key for a local HA-triggered C300X action."""

    action_id = data.get("action_id")
    if not isinstance(action_id, str):
        return None
    return ACTION_EVENT_KEYS.get(action_id)


def action_event_display_data(
    data: Mapping[str, Any],
    language: str | None = None,
) -> dict[str, Any]:
    """Return display-ready event data for a local HA-triggered action."""

    event_key = action_event_key(data)
    if event_key is None:
        return {}

    result = dict(data)
    result["event_key"] = event_key
    result["event_type_key"] = event_key
    result.setdefault("event_at", datetime.now(UTC).isoformat())
    return agent_event_display_data(result, language)

def _localized_label(data: Mapping[str, Any], language: str | None) -> str | None:
    language_code = str(language or "").lower()
    if language_code.startswith("de"):
        key = "event_label_de"
    elif language_code.startswith("it"):
        key = "event_label_it"
    elif language_code.startswith("fr"):
        key = "event_label_fr"
    else:
        key = "event_label_en"
    value = data.get(key)
    return value if isinstance(value, str) and value else None
