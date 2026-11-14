"""Alarm area of the display settings.

Alarmo drives the alarm commands and the display's Alarm page: its alarm
panel, and an optional quick action beside it, such as the stair light. The
settings have a form of their own, a step of the setup, the reconfigure and
the options, apart from the pages and the Display patch. They are kept whether
or not the Display patch is on, since the alarm commands do not need it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult as FlowResult
else:
    FlowResult = dict[str, Any]

ALARM_KEYS = (CONF_ALARM_ENTITY_ID, CONF_ALARM_PAGE_ENTITY_ID)


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


def alarm_values(data: dict[str, Any]) -> dict[str, Any]:
    """Return the alarm settings out of saved or collected settings."""

    return {key: str(data.get(key) or "") for key in ALARM_KEYS}


def alarm_step(
    flow: Any,
    step_id: str,
    current: dict[str, Any],
    user_input: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, FlowResult | None]:
    """Run one alarm step of a flow.

    Returns the settings to keep, or the form to show: the first one, and
    again with the errors when the post was wrong.
    """

    errors: dict[str, str] = {}
    schema = alarm_schema(current)
    if user_input is not None:
        data, errors = alarm_input(current, user_input)
        if not errors:
            return data, None
        schema = flow.add_suggested_values_to_schema(schema, user_input)
    return None, flow.async_show_form(
        step_id=step_id, data_schema=schema, errors=errors
    )
