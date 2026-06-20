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
    alarm_page_entity_selector as _alarm_page_entity_selector,
)
from .config_flow_forms import (
    dashboard_entity_custom_name_selector as _dashboard_entity_custom_name_selector,
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
    CONF_ALARM_PAGE_ENTITY_ID,
    CONF_DASHBOARD_DYNAMIC_HOMEPAGE,
    CONF_DASHBOARD_ENTITIES,
    CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
    CONF_DASHBOARD_PREVENT_RETURN,
    CONF_DEVICE_UI_ENABLED,
    CONF_WEATHER_ENTITY_ID,
    DASHBOARD_ENTITY_NAME_DISPLAY_CUSTOM,
    DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME,
    DASHBOARD_ENTITY_NAME_DISPLAY_OPTIONS,
    DASHBOARD_ENTITY_SECONDARY_INFO_OPTIONS,
    DASHBOARD_ENTITY_SECONDARY_INFO_STATE,
)
from .dashboard_entities import (
    normalize_dashboard_entity_display_overrides,
    normalize_dashboard_entity_ids,
)

DASHBOARD_PREVENT_RETURN_DEFAULT = False
DASHBOARD_DYNAMIC_HOMEPAGE_DEFAULT = True
_DASHBOARD_ENTITY_NAME_FIELD_SUFFIX = " - Name"
_DASHBOARD_ENTITY_CUSTOM_NAME_FIELD_SUFFIX = " - Custom name"
_DASHBOARD_ENTITY_SECONDARY_FIELD_SUFFIX = " - Secondary line"


def dashboard_entity_ids(value: Any) -> list[str]:
    """Validate selected entities for the simple C300X dashboard page."""

    try:
        return list(normalize_dashboard_entity_ids(value, strict=True))
    except ValueError as err:
        raise vol.Invalid("invalid dashboard entities") from err


def alarm_page_entity_id(value: Any) -> str:
    """Validate the optional alarm page quick entity."""

    if value in (None, ""):
        return ""
    entities = dashboard_entity_ids([value])
    if not entities:
        raise vol.Invalid("invalid alarm page entity")
    return entities[0]


def dashboard_entity_display_overrides(value: Any) -> dict[str, dict[str, str]]:
    """Validate per-entity dashboard display override mapping."""

    if value in (None, ""):
        return {}
    try:
        return normalize_dashboard_entity_display_overrides(value, strict=True)
    except ValueError as err:
        raise vol.Invalid("invalid dashboard entity display overrides") from err


def _dashboard_entity_field_label(index: int, entity_id: str) -> str:
    object_id = entity_id.split(".", 1)[-1].replace("_", " ").strip()
    label = object_id.title() if object_id else f"Entity {index}"
    return f"{index}. {label}"


def _dashboard_entity_name_field(index: int, entity_id: str) -> str:
    return f"{_dashboard_entity_field_label(index, entity_id)}{_DASHBOARD_ENTITY_NAME_FIELD_SUFFIX}"


def _dashboard_entity_secondary_field(index: int, entity_id: str) -> str:
    return f"{_dashboard_entity_field_label(index, entity_id)}{_DASHBOARD_ENTITY_SECONDARY_FIELD_SUFFIX}"


def _dashboard_entity_custom_name_field(index: int, entity_id: str) -> str:
    return f"{_dashboard_entity_field_label(index, entity_id)}{_DASHBOARD_ENTITY_CUSTOM_NAME_FIELD_SUFFIX}"


def _dashboard_entity_name_display(value: Any) -> str:
    display = str(value or DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME).strip()
    if display not in DASHBOARD_ENTITY_NAME_DISPLAY_OPTIONS:
        return DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME
    return display


def _dashboard_entity_secondary_info(value: Any) -> str:
    info = str(value or DASHBOARD_ENTITY_SECONDARY_INFO_STATE).strip()
    if info not in DASHBOARD_ENTITY_SECONDARY_INFO_OPTIONS:
        return DASHBOARD_ENTITY_SECONDARY_INFO_STATE
    return info


def dashboard_entity_display_form_complete(
    user_input: dict[str, Any] | None,
    entity_ids: Any,
) -> bool:
    """Return whether the per-entity display controls were rendered and posted."""

    if user_input is None:
        return True
    entities = dashboard_entity_ids(entity_ids)
    return all(
        _dashboard_entity_name_field(index, entity_id) in user_input
        and _dashboard_entity_custom_name_field(index, entity_id) in user_input
        and _dashboard_entity_secondary_field(index, entity_id) in user_input
        for index, entity_id in enumerate(entities, start=1)
    )


def dashboard_entity_display_overrides_from_fields(
    user_input: dict[str, Any],
    entity_ids: Any,
    defaults: Any = None,
) -> dict[str, dict[str, str]]:
    """Build per-entity display overrides from rendered form controls."""

    entities = dashboard_entity_ids(entity_ids)
    existing = normalize_dashboard_entity_display_overrides(defaults)
    result: dict[str, dict[str, str]] = {}
    for index, entity_id in enumerate(entities, start=1):
        name = _dashboard_entity_name_display(
            user_input.get(
                _dashboard_entity_name_field(index, entity_id),
                existing.get(entity_id, {}).get(
                    "name",
                    DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME,
                ),
            )
        )
        secondary = _dashboard_entity_secondary_info(
            user_input.get(
                _dashboard_entity_secondary_field(index, entity_id),
                existing.get(entity_id, {}).get(
                    "secondary",
                    DASHBOARD_ENTITY_SECONDARY_INFO_STATE,
                ),
            )
        )
        custom_name = str(
            user_input.get(
                _dashboard_entity_custom_name_field(index, entity_id),
                existing.get(entity_id, {}).get("custom_name", ""),
            )
            or ""
        ).strip()
        options: dict[str, str] = {}
        if name != DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME:
            options["name"] = name
            if name == DASHBOARD_ENTITY_NAME_DISPLAY_CUSTOM and custom_name:
                options["custom_name"] = custom_name
        if secondary != DASHBOARD_ENTITY_SECONDARY_INFO_STATE:
            options["secondary"] = secondary
        if options:
            result[entity_id] = options
    return result


def dashboard_schema(
    default_alarm_entity: str,
    default_weather_entity: str,
    default_actions_json: str = "",
    default_dashboard_prevent_return: bool = DASHBOARD_PREVENT_RETURN_DEFAULT,
    default_dashboard_entities: Any = None,
    default_dashboard_entity_display_overrides: Any = None,
    default_dashboard_dynamic_homepage: bool = DASHBOARD_DYNAMIC_HOMEPAGE_DEFAULT,
    default_alarm_page_entity: str = "",
    *,
    default_device_ui_enabled: bool = False,
) -> vol.Schema:
    """Return the display dashboard schema."""

    dashboard_entities = dashboard_entity_ids(default_dashboard_entities or [])
    fields: dict[Any, Any] = {
            vol.Optional(
                CONF_DEVICE_UI_ENABLED,
                default=default_device_ui_enabled,
            ): bool,
            vol.Optional(
                CONF_DASHBOARD_PREVENT_RETURN,
                default=default_dashboard_prevent_return,
            ): bool,
            vol.Optional(
                CONF_DASHBOARD_DYNAMIC_HOMEPAGE,
                default=default_dashboard_dynamic_homepage,
            ): bool,
            _optional_suggested(
                CONF_ALARM_ENTITY_ID,
                default_alarm_entity,
            ): _alarm_entity_selector(),
            _optional_suggested(
                CONF_ALARM_PAGE_ENTITY_ID,
                default_alarm_page_entity,
            ): _alarm_page_entity_selector(),
            _optional_suggested(
                CONF_WEATHER_ENTITY_ID,
                default_weather_entity,
            ): _weather_entity_selector(),
            _optional_suggested(
                CONF_DASHBOARD_ENTITIES,
                dashboard_entities,
            ): _dashboard_entity_selector(),
            _optional_suggested(
                CONF_ACTIONS_JSON,
                default_actions_json,
            ): _actions_json_field(),
    }
    return vol.Schema(fields)


def dashboard_entity_display_schema(
    default_dashboard_entities: Any = None,
    default_dashboard_entity_display_overrides: Any = None,
) -> vol.Schema:
    """Return the per-entity display options schema."""

    dashboard_entities = dashboard_entity_ids(default_dashboard_entities or [])
    dashboard_overrides = normalize_dashboard_entity_display_overrides(
        default_dashboard_entity_display_overrides
    )
    fields: dict[Any, Any] = {}
    for index, entity_id in enumerate(dashboard_entities, start=1):
        entity_overrides = dashboard_overrides.get(entity_id, {})
        fields[
            vol.Optional(
                _dashboard_entity_name_field(index, entity_id),
                default=entity_overrides.get(
                    "name",
                    DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME,
                ),
            )
        ] = _dashboard_entity_name_display_selector()
        fields[
            vol.Optional(
                _dashboard_entity_custom_name_field(index, entity_id),
                default=entity_overrides.get("custom_name", ""),
            )
        ] = _dashboard_entity_custom_name_selector()
        fields[
            vol.Optional(
                _dashboard_entity_secondary_field(index, entity_id),
                default=entity_overrides.get(
                    "secondary",
                    DASHBOARD_ENTITY_SECONDARY_INFO_STATE,
                ),
            )
        ] = _dashboard_entity_secondary_info_selector()
    return vol.Schema(fields)


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
        CONF_ALARM_PAGE_ENTITY_ID,
        "" if defaults is None else defaults.get(CONF_ALARM_PAGE_ENTITY_ID, ""),
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
    data[CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES] = (
        dashboard_entity_display_overrides_from_fields(
            data,
            data.get(CONF_DASHBOARD_ENTITIES, ()),
            {} if defaults is None else defaults.get(
                CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
                {},
            ),
        )
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
