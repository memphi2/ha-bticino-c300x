"""Shared display configuration and dashboard control value parsing."""

from __future__ import annotations

import math
from typing import Any

from .action import (
    ActionValidationError,
    validate_action_map,
)
from .const import (
    CONF_ACTIONS,
    CONF_ALARM_ENTITY_ID,
    CONF_ALARM_PAGE_ENTITY_ID,
    CONF_DASHBOARD_ENTITIES,
    CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
    CONF_DASHBOARD_NAVIGATION,
    CONF_DASHBOARD_PAGES,
    CONF_DASHBOARD_PREVENT_RETURN,
    CONF_DASHBOARD_STATUS_PAGE_ENABLED,
    CONF_ENERGY_PAGE,
    CONF_WEATHER_ENTITY_ID,
)
from .dashboard_energy import normalize_energy_page
from .dashboard_entities import (
    DASHBOARD_ENTITY_DOMAIN_SET,
    DashboardPage,
    normalize_dashboard_entity_display_overrides,
    normalize_dashboard_entity_ids,
    normalize_dashboard_pages,
)
from .dashboard_images import IMAGE_TILE_DOMAINS
from .dashboard_page_order import dashboard_navigation
from .entry_config import entry_config_value
from .entry_types import BticinoC300XConfigEntry

_DASHBOARD_DEFAULT_PAGE = "C300X"


_DASHBOARD_ACTION_PAGE = ""


_DASHBOARD_SWITCH_DOMAINS = {"fan", "input_boolean", "light", "switch"}


_DASHBOARD_SWITCH_SERVICES = {"toggle"}


_DASHBOARD_TOGGLE_ENTITY_DOMAINS = {
    "automation", "fan", "humidifier", "input_boolean", "light", "siren", "switch",
}


_DASHBOARD_BUTTON_ENTITY_DOMAINS = {"button", "input_button", "scene", "script"}


_DASHBOARD_SLIDER_ENTITY_DOMAINS = {"input_number", "number"}


_DASHBOARD_CHOICE_ENTITY_DOMAINS = {"input_select", "select"}


_DASHBOARD_READ_ONLY_ENTITY_DOMAINS = {"binary_sensor", "device_tracker", "person", "sensor"}


_DASHBOARD_SUPPORTED_ENTITY_DOMAINS = DASHBOARD_ENTITY_DOMAIN_SET


_DASHBOARD_SLIDER_ACTIONS = {"decrement", "increment"}


_DASHBOARD_CHOICE_ACTIONS = {"next", "previous"}


def configured_alarm_entity_id(entry: BticinoC300XConfigEntry) -> str | None:
    """Return the alarm entity configured for a C300X entry."""

    value = entry_config_value(entry, CONF_ALARM_ENTITY_ID)
    return value if isinstance(value, str) and value else None


def configured_alarm_page_entity_id(entry: BticinoC300XConfigEntry) -> str | None:
    """Return the optional dashboard-compatible entity shown on the alarm page."""

    value = entry_config_value(entry, CONF_ALARM_PAGE_ENTITY_ID)
    entities = _dashboard_entity_ids([value] if isinstance(value, str) else value)
    if not entities or entities[0].split(".", 1)[0] in IMAGE_TILE_DOMAINS:
        return None
    return entities[0]


def configured_weather_entity_id(entry: BticinoC300XConfigEntry) -> str | None:
    """Return the weather entity configured for the C300X dashboard."""

    value = entry_config_value(entry, CONF_WEATHER_ENTITY_ID)
    return value if isinstance(value, str) and value else None


def configured_status_page_enabled(entry: BticinoC300XConfigEntry) -> bool:
    """Return the independent visibility of the status page."""

    return entry_config_value(entry, CONF_DASHBOARD_STATUS_PAGE_ENABLED, True) is True


def configured_actions(entry: BticinoC300XConfigEntry) -> dict[str, dict[str, Any]]:
    """Return the validated configured action allowlist."""

    try:
        return validate_action_map(entry_config_value(entry, CONF_ACTIONS, {}))
    except ActionValidationError:
        return {}


def configured_dashboard_entities(entry: BticinoC300XConfigEntry) -> tuple[str, ...]:
    """Return selected standard HA entities for the C300X dashboard."""

    return _dashboard_entity_ids(entry_config_value(entry, CONF_DASHBOARD_ENTITIES, []))


def configured_energy_page(entry: BticinoC300XConfigEntry) -> dict[str, Any]:
    """Return the settings of the display's energy page."""

    return normalize_energy_page(entry_config_value(entry, CONF_ENERGY_PAGE, {}))


def configured_dashboard_pages(entry: BticinoC300XConfigEntry) -> tuple[DashboardPage, ...]:
    """Return the configured display pages in display order, or none.

    An entry saved before pages could be set up has none; its pages then
    follow the first occurrence of their names, as they always did.
    """

    return normalize_dashboard_pages(entry_config_value(entry, CONF_DASHBOARD_PAGES, []))


def configured_dashboard_navigation(entry: BticinoC300XConfigEntry) -> str:
    """Return how the display changes pages: arrows or the favourites bar."""

    return dashboard_navigation(entry_config_value(entry, CONF_DASHBOARD_NAVIGATION, None))


def configured_dashboard_entity_display_overrides(
    entry: BticinoC300XConfigEntry,
) -> dict[str, dict[str, str]]:
    """Return per-entity dashboard display overrides."""

    return normalize_dashboard_entity_display_overrides(
        entry_config_value(entry, CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES, {})
    )


def configured_dashboard_prevent_return(entry: BticinoC300XConfigEntry) -> bool:
    """Return whether the dashboard should prevent returning to the homepage."""

    return bool(entry_config_value(entry, CONF_DASHBOARD_PREVENT_RETURN, True))


def _dashboard_entity_ids(value: Any) -> tuple[str, ...]:
    """Normalize selected dashboard entity IDs without importing the config flow."""

    return normalize_dashboard_entity_ids(value)


def _dashboard_float(value: Any, fallback: float | None) -> float | None:
    """Return a finite float; NaN, inf and non-numbers give the fallback."""

    if isinstance(value, bool):
        return fallback
    try:
        number = float(value)
    except TypeError, ValueError, OverflowError:
        return fallback
    return number if math.isfinite(number) else fallback


def _dashboard_first_attribute(attributes: dict[str, Any], *names: str) -> Any | None:
    """Return the first present slider attribute while preserving zero values."""

    for name in names:
        if name in attributes and attributes[name] not in (None, ""):
            return attributes[name]
    return None
