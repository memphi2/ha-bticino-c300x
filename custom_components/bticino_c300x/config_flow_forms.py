"""Reusable config-flow form helpers for BTicino C300X."""

from __future__ import annotations

import json
from typing import Any

from homeassistant.helpers import selector
from homeassistant.helpers.selector import SelectOptionDict

from .const import (
    ALARM_DOMAIN,
    DASHBOARD_ENTITY_NAME_DISPLAY_CUSTOM,
    DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME,
    WEATHER_DOMAIN,
)
from .dashboard_entities import DASHBOARD_ENTITY_DOMAINS
from .schema_compat import vol


def optional_suggested(key: str, suggested_value: Any) -> vol.Optional:
    """Return an optional form key that can be cleared by the user."""

    if suggested_value in (None, ""):
        return vol.Optional(key)
    return vol.Optional(key, description={"suggested_value": suggested_value})


def actions_json(actions: Any) -> str:
    """Return stable JSON for the action allowlist options form."""

    if not actions:
        return ""
    return json.dumps(actions, indent=2, sort_keys=True)


def alarm_entity_selector() -> Any:
    """Return the HA alarm entity selector."""
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=ALARM_DOMAIN),
    )


def weather_entity_selector() -> Any:
    """Return the HA weather entity selector."""
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=WEATHER_DOMAIN),
    )


def dashboard_entity_selector() -> Any:
    """Return a multi-entity selector for the simple C300X dashboard."""

    return selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain=list(DASHBOARD_ENTITY_DOMAINS),
            multiple=True,
        ),
    )


def alarm_page_entity_selector() -> Any:
    """Return a single-entity selector for the alarm page quick tile."""

    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=list(DASHBOARD_ENTITY_DOMAINS)),
    )


def dashboard_entity_name_display_selector() -> Any:
    """Return the selector for one dashboard entity title."""

    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                SelectOptionDict(value=DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME, label="Home Assistant name"),
                SelectOptionDict(value="entity_id", label="Entity ID"),
                SelectOptionDict(value=DASHBOARD_ENTITY_NAME_DISPLAY_CUSTOM, label="Custom name"),
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def dashboard_entity_custom_name_selector() -> Any:
    """Return the text selector for one custom dashboard entity title."""

    return selector.TextSelector(selector.TextSelectorConfig())


def dashboard_entity_order_selector() -> Any:
    """Return a bounded position input for a native display page."""
    return selector.NumberSelector(selector.NumberSelectorConfig(
        min=0, max=10000, step=1, mode=selector.NumberSelectorMode.BOX,
    ))


def dashboard_entity_tile_size_selector() -> Any:
    """Return the width or height choice for one native display tile."""

    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                SelectOptionDict(value="auto", label="Automatic"),
                SelectOptionDict(value="half", label="Half"),
                SelectOptionDict(value="full", label="Full"),
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def dashboard_entity_secondary_info_selector() -> Any:
    """Return the selector for one dashboard entity secondary text."""

    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                SelectOptionDict(value="state", label="State"),
                SelectOptionDict(value="entity_id", label="Entity ID"),
                SelectOptionDict(value="last_changed", label="Last changed"),
                SelectOptionDict(value="last_updated", label="Last updated"),
                SelectOptionDict(value="none", label="None"),
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def password_selector() -> Any:
    """Return a password field without storing the submitted secret."""

    return selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD),
    )


def actions_json_field() -> Any:
    """Return the HA multiline text selector for action JSON."""

    return selector.TextSelector(selector.TextSelectorConfig(multiline=True))
