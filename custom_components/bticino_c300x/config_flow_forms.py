"""Reusable config-flow form helpers for BTicino C300X."""

from __future__ import annotations

import json
from typing import Any

import voluptuous as vol

from .const import (
    ALARM_DOMAIN,
    DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME,
    WEATHER_DOMAIN,
)
from .dashboard_entities import DASHBOARD_ENTITY_DOMAINS

selector: Any
try:
    from homeassistant.helpers import selector as ha_selector

    selector = ha_selector
except (ImportError, ModuleNotFoundError):  # pragma: no cover - local test stubs
    selector = None


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
    """Return the HA alarm entity selector with a test-friendly fallback."""

    if selector is None:
        return str
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=ALARM_DOMAIN),
    )


def weather_entity_selector() -> Any:
    """Return the HA weather entity selector with a test-friendly fallback."""

    if selector is None:
        return str
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=WEATHER_DOMAIN),
    )


def dashboard_entity_selector() -> Any:
    """Return a multi-entity selector for the simple C300X dashboard."""

    if selector is None:
        return list
    return selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain=list(DASHBOARD_ENTITY_DOMAINS),
            multiple=True,
        ),
    )


def dashboard_entity_name_display_selector() -> Any:
    """Return the selector for one dashboard entity title."""

    if selector is None:
        return str
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                {
                    "value": DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME,
                    "label": "Home Assistant name",
                },
                {
                    "value": "entity_id",
                    "label": "Entity ID",
                },
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def dashboard_entity_secondary_info_selector() -> Any:
    """Return the selector for one dashboard entity secondary text."""

    if selector is None:
        return str
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                {"value": "state", "label": "State"},
                {"value": "entity_id", "label": "Entity ID"},
                {"value": "last_changed", "label": "Last changed"},
                {"value": "last_updated", "label": "Last updated"},
                {"value": "none", "label": "None"},
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def password_selector() -> Any:
    """Return a password field without storing the submitted secret."""

    if selector is None:
        return str
    return selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD),
    )


def actions_json_field() -> Any:
    """Return the HA multiline text selector for action JSON."""

    if selector is None:
        return str
    return selector.TextSelector(selector.TextSelectorConfig(multiline=True))
