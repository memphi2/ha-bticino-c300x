"""Display-dashboard config-flow helpers for BTicino C300X."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from .config_flow_forms import (
    actions_json as _actions_json,
)
from .config_flow_forms import (
    actions_json_field as _actions_json_field,
)
from .config_flow_forms import (
    alarm_entity_selector as _alarm_entity_selector,
)
from .config_flow_forms import (
    dashboard_entity_name_display_selector as _dashboard_entity_name_display_selector,
)
from .config_flow_forms import (
    dashboard_entity_secondary_info_selector as _dashboard_entity_secondary_info_selector,
)
from .config_flow_forms import (
    dashboard_entity_selector as _dashboard_entity_selector,
)
from .config_flow_forms import (
    optional_suggested as _optional_suggested,
)
from .config_flow_forms import (
    weather_entity_selector as _weather_entity_selector,
)
from .const import (
    CONF_ACTIONS,
    CONF_ACTIONS_JSON,
    CONF_ALARM_ENTITY_ID,
    CONF_DASHBOARD_DYNAMIC_HOMEPAGE,
    CONF_DASHBOARD_ENTITIES,
    CONF_DASHBOARD_ENTITY_NAME_DISPLAY,
    CONF_DASHBOARD_ENTITY_SECONDARY_INFO,
    CONF_DASHBOARD_PREVENT_RETURN,
    CONF_DEVICE_UI_ENABLED,
    CONF_WEATHER_ENTITY_ID,
    DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME,
    DASHBOARD_ENTITY_NAME_DISPLAY_OPTIONS,
    DASHBOARD_ENTITY_SECONDARY_INFO_OPTIONS,
    DASHBOARD_ENTITY_SECONDARY_INFO_STATE,
)
from .dashboard_entities import normalize_dashboard_entity_ids

DASHBOARD_PREVENT_RETURN_DEFAULT = False
DASHBOARD_DYNAMIC_HOMEPAGE_DEFAULT = False


def dashboard_entity_ids(value: Any) -> list[str]:
    """Validate selected entities for the simple C300X dashboard page."""

    try:
        return list(normalize_dashboard_entity_ids(value, strict=True))
    except ValueError as err:
        raise vol.Invalid("invalid dashboard entities") from err


def dashboard_entity_name_display(value: Any) -> str:
    """Validate how direct dashboard entities should be named."""

    display = str(value or DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME).strip()
    if display not in DASHBOARD_ENTITY_NAME_DISPLAY_OPTIONS:
        return DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME
    return display


def dashboard_entity_secondary_info(value: Any) -> str:
    """Validate direct dashboard entity secondary-info mode."""

    info = str(value or DASHBOARD_ENTITY_SECONDARY_INFO_STATE).strip()
    if info not in DASHBOARD_ENTITY_SECONDARY_INFO_OPTIONS:
        return DASHBOARD_ENTITY_SECONDARY_INFO_STATE
    return info


def dashboard_schema(
    default_alarm_entity: str,
    default_weather_entity: str,
    default_actions_json: str = "",
    default_dashboard_prevent_return: bool = DASHBOARD_PREVENT_RETURN_DEFAULT,
    default_dashboard_entities: Any = None,
    default_dashboard_entity_name_display: str = DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME,
    default_dashboard_entity_secondary_info: str = DASHBOARD_ENTITY_SECONDARY_INFO_STATE,
    default_dashboard_dynamic_homepage: bool = DASHBOARD_DYNAMIC_HOMEPAGE_DEFAULT,
    *,
    default_device_ui_enabled: bool = False,
) -> vol.Schema:
    """Return the display dashboard schema."""

    return vol.Schema(
        {
            vol.Optional(
                CONF_DEVICE_UI_ENABLED,
                default=default_device_ui_enabled,
            ): bool,
            _optional_suggested(
                CONF_ALARM_ENTITY_ID,
                default_alarm_entity,
            ): _alarm_entity_selector(),
            _optional_suggested(
                CONF_WEATHER_ENTITY_ID,
                default_weather_entity,
            ): _weather_entity_selector(),
            _optional_suggested(
                CONF_DASHBOARD_ENTITIES,
                dashboard_entity_ids(default_dashboard_entities or []),
            ): _dashboard_entity_selector(),
            vol.Optional(
                CONF_DASHBOARD_DYNAMIC_HOMEPAGE,
                default=default_dashboard_dynamic_homepage,
            ): bool,
            vol.Optional(
                CONF_DASHBOARD_ENTITY_NAME_DISPLAY,
                default=dashboard_entity_name_display(
                    default_dashboard_entity_name_display
                ),
            ): _dashboard_entity_name_display_selector(),
            vol.Optional(
                CONF_DASHBOARD_ENTITY_SECONDARY_INFO,
                default=dashboard_entity_secondary_info(
                    default_dashboard_entity_secondary_info
                ),
            ): _dashboard_entity_secondary_info_selector(),
            _optional_suggested(
                CONF_ACTIONS_JSON,
                default_actions_json,
            ): _actions_json_field(),
            vol.Optional(
                CONF_DASHBOARD_PREVENT_RETURN,
                default=default_dashboard_prevent_return,
            ): bool,
        }
    )


def dashboard_input_defaults(
    user_input: dict[str, Any],
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return dashboard input defaults for the separate display dashboard page."""

    data = dict(user_input)
    data.setdefault(
        CONF_DEVICE_UI_ENABLED,
        False if defaults is None else defaults.get(CONF_DEVICE_UI_ENABLED, False),
    )
    data.setdefault(
        CONF_ALARM_ENTITY_ID,
        "" if defaults is None else defaults[CONF_ALARM_ENTITY_ID],
    )
    data.setdefault(
        CONF_WEATHER_ENTITY_ID,
        "" if defaults is None else defaults[CONF_WEATHER_ENTITY_ID],
    )
    data.setdefault(
        CONF_DASHBOARD_ENTITIES,
        [] if defaults is None else defaults.get(CONF_DASHBOARD_ENTITIES, []),
    )
    data.setdefault(
        CONF_DASHBOARD_DYNAMIC_HOMEPAGE,
        (
            DASHBOARD_DYNAMIC_HOMEPAGE_DEFAULT
            if defaults is None
            else defaults.get(
                CONF_DASHBOARD_DYNAMIC_HOMEPAGE,
                DASHBOARD_DYNAMIC_HOMEPAGE_DEFAULT,
            )
        ),
    )
    data.setdefault(
        CONF_DASHBOARD_ENTITY_NAME_DISPLAY,
        (
            DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME
            if defaults is None
            else defaults.get(
                CONF_DASHBOARD_ENTITY_NAME_DISPLAY,
                DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME,
            )
        ),
    )
    data.setdefault(
        CONF_DASHBOARD_ENTITY_SECONDARY_INFO,
        (
            DASHBOARD_ENTITY_SECONDARY_INFO_STATE
            if defaults is None
            else defaults.get(
                CONF_DASHBOARD_ENTITY_SECONDARY_INFO,
                DASHBOARD_ENTITY_SECONDARY_INFO_STATE,
            )
        ),
    )
    data.setdefault(
        CONF_ACTIONS_JSON,
        "" if defaults is None else _actions_json(defaults[CONF_ACTIONS]),
    )
    data.setdefault(
        CONF_DASHBOARD_PREVENT_RETURN,
        (
            DASHBOARD_PREVENT_RETURN_DEFAULT
            if defaults is None
            else defaults[CONF_DASHBOARD_PREVENT_RETURN]
        ),
    )
    return data
