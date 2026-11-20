"""Reusable config-flow form helpers for BTicino C300X."""

from __future__ import annotations

import json
from typing import Any

from homeassistant.helpers import selector

from .const import (
    ALARM_DOMAIN,
    DASHBOARD_ENTITY_NAME_DISPLAY_OPTIONS,
    DASHBOARD_ENTITY_SECONDARY_INFO_OPTIONS,
    WEATHER_DOMAIN,
)
from .dashboard_entities import (
    ALARM_PAGE_ACTION_DOMAINS,
    ALARM_PAGE_ENTITY_DOMAINS,
    DASHBOARD_TILE_SIZE_AUTO,
    DASHBOARD_TILE_SIZES,
)
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


def alarm_page_entity_selector(saved: Any = "") -> Any:
    """Return a single-entity selector for the alarm page quick tile.

    It offers the domains a tap can act on. A value saved earlier from another
    domain is offered too, because the selector rejects a prefilled entity
    outside its domains and the form could then not be saved at all.
    """

    domains = list(ALARM_PAGE_ACTION_DOMAINS)
    saved_domain = str(saved or "").split(".", 1)[0]
    if saved_domain in ALARM_PAGE_ENTITY_DOMAINS and saved_domain not in domains:
        domains.append(saved_domain)
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=domains))


def _translated_choice(
    translation_key: str,
    options: Any,
    *,
    custom_value: bool = False,
) -> Any:
    """Return a dropdown whose choices the frontend translates."""

    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=list(options),
            translation_key=translation_key,
            mode=selector.SelectSelectorMode.DROPDOWN,
            custom_value=custom_value,
        )
    )


def dashboard_entity_name_display_selector() -> Any:
    """Return the selector for one dashboard entity title."""

    return _translated_choice("tile_name", DASHBOARD_ENTITY_NAME_DISPLAY_OPTIONS)


def dashboard_entity_custom_name_selector() -> Any:
    """Return the text selector for one custom dashboard entity title."""

    return selector.TextSelector(selector.TextSelectorConfig())


def dashboard_entity_tile_size_selector() -> Any:
    """Return the width or height choice for one native display tile."""

    return _translated_choice("tile_size", (DASHBOARD_TILE_SIZE_AUTO, *DASHBOARD_TILE_SIZES))


def dashboard_entity_secondary_info_selector() -> Any:
    """Return the selector for one dashboard entity secondary text."""

    return _translated_choice("tile_secondary", DASHBOARD_ENTITY_SECONDARY_INFO_OPTIONS)


def password_selector() -> Any:
    """Return a password field without storing the submitted secret."""

    return selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD),
    )


def actions_json_field() -> Any:
    """Return the HA multiline text selector for action JSON."""

    return selector.TextSelector(selector.TextSelectorConfig(multiline=True))
