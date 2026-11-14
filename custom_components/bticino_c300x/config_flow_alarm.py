"""Alarm area of the display settings.

Alarmo drives the display's Alarm page: its alarm panel, and an optional quick
action beside it, such as the stair light. The area has a form of its own,
apart from the pages and the Display patch.
"""

from __future__ import annotations

from typing import Any

from .config_flow_dashboard import alarm_page_entity_id as _alarm_page_entity_id
from .config_flow_forms import (
    alarm_entity_selector as _alarm_entity_selector,
)
from .config_flow_forms import (
    alarm_page_entity_selector as _alarm_page_entity_selector,
)
from .config_flow_forms import optional_suggested as _optional_suggested
from .config_flow_input import _alarm_entity_id
from .const import (
    CONF_ALARM_ENTITY_ID,
    CONF_ALARM_PAGE_ENTITY_ID,
    CONF_DASHBOARD_ENTITIES,
    CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
)
from .dashboard_entities import (
    normalize_dashboard_entity_display_overrides,
    normalize_dashboard_entity_ids,
)
from .schema_compat import vol


def alarm_schema(dashboard_input: dict[str, Any]) -> vol.Schema:
    """Return the alarm form, prefilled from the saved settings."""

    return vol.Schema(
        {
            _optional_suggested(
                CONF_ALARM_ENTITY_ID,
                dashboard_input.get(CONF_ALARM_ENTITY_ID),
            ): _alarm_entity_selector(),
            _optional_suggested(
                CONF_ALARM_PAGE_ENTITY_ID,
                dashboard_input.get(CONF_ALARM_PAGE_ENTITY_ID),
            ): _alarm_page_entity_selector(),
        }
    )


def alarm_input(
    dashboard_input: dict[str, Any],
    user_input: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Merge a posted alarm form into the dashboard settings.

    Home Assistant leaves out a picker the user emptied, so a missing field is
    stored empty. The display settings of an entity that is no longer shown,
    the former quick action, are dropped. Returns the settings and the form
    errors.
    """

    errors: dict[str, str] = {}
    alarm = quick = ""
    try:
        alarm = _alarm_entity_id(user_input.get(CONF_ALARM_ENTITY_ID, ""))
    except vol.Invalid:
        errors[CONF_ALARM_ENTITY_ID] = "invalid_alarm_entity"
    try:
        quick = _alarm_page_entity_id(user_input.get(CONF_ALARM_PAGE_ENTITY_ID, ""))
    except vol.Invalid:
        errors[CONF_ALARM_PAGE_ENTITY_ID] = "invalid_alarm_page_entity"
    if errors:
        return dashboard_input, errors

    shown = set(
        normalize_dashboard_entity_ids(dashboard_input.get(CONF_DASHBOARD_ENTITIES, []))
    )
    overrides = normalize_dashboard_entity_display_overrides(
        dashboard_input.get(CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES, {})
    )
    return {
        **dashboard_input,
        CONF_ALARM_ENTITY_ID: alarm,
        CONF_ALARM_PAGE_ENTITY_ID: quick,
        CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: {
            entity_id: options
            for entity_id, options in overrides.items()
            if entity_id in shown or entity_id == quick
        },
    }, errors
