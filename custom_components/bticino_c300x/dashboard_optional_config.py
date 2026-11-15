"""Bounded, independently enabled Agenda and Leave home configuration."""

from __future__ import annotations

from typing import Any

from .const import CONF_AGENDA_PAGE, CONF_LEAVE_HOME_PAGE
from .dashboard_page_order import page_position
from .entry_config import entry_config_value
from .validation_patterns import HA_ACTION_ID_RE, HA_ENTITY_ID_RE

OPTIONAL_PAGE_KEYS = (CONF_AGENDA_PAGE, CONF_LEAVE_HOME_PAGE)
MAX_CALENDARS = 8
MAX_CHECKS = 24
MAX_ACTIONS = 8


def selected_ids(value: Any, domain: str | None, limit: int) -> list[str]:
    """Keep explicit, valid selections only; never discover entities implicitly."""
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    pattern = HA_ENTITY_ID_RE if domain else HA_ACTION_ID_RE
    for item in value:
        if (isinstance(item, str) and pattern.fullmatch(item)
                and (domain is None or item.startswith(domain + "."))
                and item not in result):
            result.append(item)
        if len(result) == limit:
            break
    return result


def normalize_agenda_page(value: Any) -> dict[str, Any]:
    data = value if isinstance(value, dict) else {}
    return {"enabled": data.get("enabled") is True,
            "position": page_position(data.get("position"), 10),
            "calendars": selected_ids(data.get("calendars"), "calendar", MAX_CALENDARS)}


def normalize_leave_home_page(value: Any) -> dict[str, Any]:
    data = value if isinstance(value, dict) else {}
    return {
        "enabled": data.get("enabled") is True,
        "position": page_position(data.get("position"), 11),
        "contacts": selected_ids(data.get("contacts"), "binary_sensor", MAX_CHECKS),
        "lights": selected_ids(data.get("lights"), "light", MAX_CHECKS),
        "actions": selected_ids(data.get("actions"), None, MAX_ACTIONS),
        "show_alarm": data.get("show_alarm") is True,
    }


def optional_page_values(data: dict[str, Any]) -> dict[str, Any]:
    return {CONF_AGENDA_PAGE: normalize_agenda_page(data.get(CONF_AGENDA_PAGE)),
            CONF_LEAVE_HOME_PAGE: normalize_leave_home_page(data.get(CONF_LEAVE_HOME_PAGE))}


def configured_agenda_page(entry: Any) -> dict[str, Any]:
    return normalize_agenda_page(entry_config_value(entry, CONF_AGENDA_PAGE))


def configured_leave_home_page(entry: Any) -> dict[str, Any]:
    return normalize_leave_home_page(entry_config_value(entry, CONF_LEAVE_HOME_PAGE))
