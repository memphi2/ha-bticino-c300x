"""Display-dashboard config-flow helpers for BTicino C300X."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers import selector

from .config_flow_forms import (
    actions_json as _actions_json,
)
from .config_flow_forms import (
    actions_json_field as _actions_json_field,
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
    dashboard_entity_tile_size_selector as _dashboard_entity_tile_size_selector,
)
from .config_flow_forms import (
    optional_suggested as _optional_suggested,
)
from .const import (
    CONF_ACTIONS,
    CONF_ACTIONS_JSON,
    CONF_ALARM_ENTITY_ID,
    CONF_ALARM_PAGE_ENTITY_ID,
    CONF_DASHBOARD_DYNAMIC_HOMEPAGE,
    CONF_DASHBOARD_ENTITIES,
    CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
    CONF_DASHBOARD_PAGES,
    CONF_DASHBOARD_PREVENT_RETURN,
    CONF_DEVICE_UI_ENABLED,
    CONF_WEATHER_ENTITY_ID,
    DASHBOARD_ENTITY_NAME_DISPLAY_CUSTOM,
    DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME,
    DASHBOARD_ENTITY_NAME_DISPLAY_OPTIONS,
    DASHBOARD_ENTITY_SECONDARY_INFO_OPTIONS,
    DASHBOARD_ENTITY_SECONDARY_INFO_STATE,
    DEFAULT_DASHBOARD_DYNAMIC_HOMEPAGE,
)
from .dashboard_entities import (
    ALARM_PAGE_ENTITY_DOMAINS,
    DASHBOARD_TILE_SIZE_AUTO,
    DASHBOARD_TILE_SIZES,
    normalize_dashboard_entity_display_overrides,
    normalize_dashboard_entity_ids,
    normalize_dashboard_pages,
)
from .schema_compat import vol

DASHBOARD_PREVENT_RETURN_DEFAULT = False
DASHBOARD_DYNAMIC_HOMEPAGE_DEFAULT = DEFAULT_DASHBOARD_DYNAMIC_HOMEPAGE
_DASHBOARD_ENTITY_NAME_FIELD_SUFFIX = " - Name"
_DASHBOARD_ENTITY_CUSTOM_NAME_FIELD_SUFFIX = " - Custom name"
_DASHBOARD_ENTITY_SECONDARY_FIELD_SUFFIX = " - Secondary line"
_DASHBOARD_ENTITY_SIZE_FIELDS = (("width", "Width"), ("height", "Height"))


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
    if not entities or entities[0].split(".", 1)[0] not in ALARM_PAGE_ENTITY_DOMAINS:
        raise vol.Invalid("invalid alarm page entity")
    return entities[0]


def dashboard_pages(value: Any) -> list[dict[str, Any]]:
    """Validate the configured display pages."""

    try:
        return list(normalize_dashboard_pages(value, strict=True))
    except ValueError as err:
        raise vol.Invalid("invalid dashboard pages") from err


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


def _dashboard_entity_layout_field(index: int, entity_id: str, name: str) -> str:
    return f"{_dashboard_entity_field_label(index, entity_id)} - {name}"


def dashboard_entity_display_field_names(entity_ids: Any) -> dict[str, dict[str, str]]:
    """Return the per-entity fields the display settings are read from.

    The tiles form shows one section per entity and posts these fields; see
    ``config_flow_tiles``.
    """

    return {
        entity_id: {
            "name": _dashboard_entity_name_field(index, entity_id),
            "custom_name": _dashboard_entity_custom_name_field(index, entity_id),
            "secondary": _dashboard_entity_secondary_field(index, entity_id),
            **{
                size_key: _dashboard_entity_layout_field(index, entity_id, size_label)
                for size_key, size_label in _DASHBOARD_ENTITY_SIZE_FIELDS
            },
        }
        for index, entity_id in enumerate(dashboard_entity_ids(entity_ids), start=1)
    }


def dashboard_display_entity_ids(data: dict[str, Any]) -> list[str]:
    """Include the optional Alarmo shortcut without adding it to the overview."""
    entities = dashboard_entity_ids(data.get(CONF_DASHBOARD_ENTITIES, []))
    quick_entity = alarm_page_entity_id(data.get(CONF_ALARM_PAGE_ENTITY_ID, ""))
    if quick_entity and quick_entity not in entities:
        entities.append(quick_entity)
    return entities


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
        # The page comes from the pages step; an order is only left from an
        # entry saved before pages could be set up.
        options: dict[str, str] = {
            key: existing[entity_id][key]
            for key in ("page", "order")
            if key in existing.get(entity_id, {})
        }
        for size_key, size_label in _DASHBOARD_ENTITY_SIZE_FIELDS:
            size = str(user_input.get(
                _dashboard_entity_layout_field(index, entity_id, size_label),
                existing.get(entity_id, {}).get(size_key, DASHBOARD_TILE_SIZE_AUTO),
            ) or "").strip()
            if size in DASHBOARD_TILE_SIZES:
                options[size_key] = size
        if name == DASHBOARD_ENTITY_NAME_DISPLAY_CUSTOM and not custom_name:
            # A custom name without its text leaves the Home Assistant name.
            name = DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME
        if name != DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME:
            options["name"] = name
            if name == DASHBOARD_ENTITY_NAME_DISPLAY_CUSTOM:
                options["custom_name"] = custom_name
        if secondary != DASHBOARD_ENTITY_SECONDARY_INFO_STATE:
            options["secondary"] = secondary
        if options:
            result[entity_id] = options
    return result


def dashboard_schema(
    default_actions_json: str = "",
    default_dashboard_prevent_return: bool = DASHBOARD_PREVENT_RETURN_DEFAULT,
    *,
    default_dashboard_dynamic_homepage: bool = DASHBOARD_DYNAMIC_HOMEPAGE_DEFAULT,
    default_device_ui_enabled: bool = False,
) -> vol.Schema:
    """Return the display and Display patch schema.

    Alarmo, the weather and the entities are chosen per page in the pages
    step; the saved ones are kept when this form is saved.
    """

    return vol.Schema(
        {
            vol.Optional(
                CONF_DEVICE_UI_ENABLED,
                default=default_device_ui_enabled,
            ): bool,
            vol.Optional(
                CONF_DASHBOARD_DYNAMIC_HOMEPAGE,
                default=default_dashboard_dynamic_homepage,
            ): bool,
            vol.Optional(
                CONF_DASHBOARD_PREVENT_RETURN,
                default=default_dashboard_prevent_return,
            ): bool,
            _optional_suggested(
                CONF_ACTIONS_JSON,
                default_actions_json,
            ): _actions_json_field(),
        }
    )


def dashboard_entity_display_schema(
    default_dashboard_entities: Any = None,
    default_dashboard_entity_display_overrides: Any = None,
    *, layout_entity_ids: Any = None,
) -> vol.Schema:
    """Return the per-entity fields the display settings are read from.

    The form that is shown groups them into a section per tile, see
    ``config_flow_tiles``; a post of it is turned back into these fields.
    """

    dashboard_entities = dashboard_entity_ids(default_dashboard_entities or [])
    dashboard_overrides = normalize_dashboard_entity_display_overrides(
        default_dashboard_entity_display_overrides
    )
    fields: dict[Any, Any] = {}
    for index, entity_id in enumerate(dashboard_entities, start=1):
        entity_overrides = dashboard_overrides.get(entity_id, {})
        if layout_entity_ids is None or entity_id in layout_entity_ids:
            for size_key, size_label in _DASHBOARD_ENTITY_SIZE_FIELDS:
                fields[vol.Optional(
                    _dashboard_entity_layout_field(index, entity_id, size_label),
                    default=entity_overrides.get(size_key, DASHBOARD_TILE_SIZE_AUTO),
                )] = _dashboard_entity_tile_size_selector()
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
            _optional_suggested(
                _dashboard_entity_custom_name_field(index, entity_id),
                entity_overrides.get("custom_name", ""),
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


def dashboard_entity_display_form(
    dashboard_input: dict[str, Any],
    overrides: Any = None,
) -> vol.Schema:
    """Return the entity-display form for the chosen dashboard settings."""

    return dashboard_entity_display_schema(
        dashboard_display_entity_ids(dashboard_input),
        overrides,
        layout_entity_ids=dashboard_input.get(CONF_DASHBOARD_ENTITIES, []),
    )


def dashboard_entity_display_has_fields(dashboard_input: dict[str, Any]) -> bool:
    """Return whether the entity-display form has anything to set."""

    return bool(dashboard_entity_display_form(dashboard_input).schema)


def dashboard_entity_display_input(
    dashboard_input: dict[str, Any],
    user_input: dict[str, Any],
) -> dict[str, Any]:
    """Merge a posted entity-display form into the dashboard settings.

    Home Assistant's form leaves out a text or number field the user emptied,
    so such a field the form showed and the post lacks is stored empty; an
    emptied position returns to the automatic one.
    """

    cleared = {
        str(key): ""
        for key, field in dashboard_entity_display_form(dashboard_input).schema.items()
        if isinstance(field, (selector.TextSelector, selector.NumberSelector))
        and str(key) not in user_input
    }
    return {**dashboard_input, **cleared, **user_input}


def dashboard_form_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """Return a posted dashboard form with each field the user emptied.

    Home Assistant's form leaves out a picker or text field the user emptied.
    Such a field has no default, so one the form showed and the post lacks is
    stored empty instead of falling back to the saved value.
    """

    cleared = {
        str(key): [] if field.config.get("multiple") else ""
        for key, field in dashboard_schema().schema.items()
        if key.default is vol.UNDEFINED and str(key) not in user_input
    }
    return {**cleared, **user_input}


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
        CONF_DASHBOARD_PAGES,
        [] if defaults is None else defaults.get(CONF_DASHBOARD_PAGES, []),
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
            dashboard_display_entity_ids(data),
            data.get(CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
                {} if defaults is None else defaults.get(CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES, {})),
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
