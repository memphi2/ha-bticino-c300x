"""Dashboard entity selection helpers."""

from __future__ import annotations

import re
from typing import Any

from .const import (
    DASHBOARD_ENTITY_NAME_DISPLAY_CUSTOM,
    DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME,
    DASHBOARD_ENTITY_NAME_DISPLAY_OPTIONS,
    DASHBOARD_ENTITY_SECONDARY_INFO_OPTIONS,
    DASHBOARD_ENTITY_SECONDARY_INFO_STATE,
)
from .validation_patterns import ENTITY_OBJECT_ID_RE

DASHBOARD_ENTITY_DOMAINS = (
    "binary_sensor",
    "button",
    "fan",
    "input_boolean",
    "input_button",
    "input_number",
    "input_select",
    "light",
    "number",
    "select",
    "script",
    "scene",
    "sensor",
    "switch",
)
DASHBOARD_ENTITY_DOMAIN_SET = frozenset(DASHBOARD_ENTITY_DOMAINS)
DashboardEntityDisplayOverrides = dict[str, dict[str, str]]


def normalize_dashboard_entity_ids(value: Any, *, strict: bool = False) -> tuple[str, ...]:
    """Normalize selected dashboard entity IDs."""

    result: list[str] = []
    seen: set[str] = set()
    for raw_value in _iter_dashboard_entity_values(value, strict=strict):
        entity_id = _normalize_dashboard_entity_id(raw_value, strict=strict)
        if entity_id is None:
            continue
        if entity_id not in seen:
            result.append(entity_id)
            seen.add(entity_id)
    return tuple(result)


def normalize_dashboard_entity_display_overrides(
    value: Any,
    *,
    strict: bool = False,
) -> DashboardEntityDisplayOverrides:
    """Normalize per-entity dashboard display override options."""

    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        if strict:
            raise ValueError("invalid dashboard entity display overrides")
        return {}

    result: DashboardEntityDisplayOverrides = {}
    for raw_entity_id, raw_options in value.items():
        entity_id = _normalize_dashboard_entity_id(raw_entity_id, strict=strict)
        if entity_id is None:
            continue
        if not isinstance(raw_options, dict):
            if strict:
                raise ValueError("invalid dashboard entity display override")
            continue
        options: dict[str, str] = {}
        name = str(
            raw_options.get("name", raw_options.get("name_display", ""))
            or ""
        ).strip()
        secondary = str(
            raw_options.get("secondary", raw_options.get("secondary_info", ""))
            or ""
        ).strip()
        custom_name = str(raw_options.get("custom_name", "") or "").strip()
        if name:
            if name not in DASHBOARD_ENTITY_NAME_DISPLAY_OPTIONS:
                if strict:
                    raise ValueError("invalid dashboard entity display name mode")
            else:
                options["name"] = name
                if name == DASHBOARD_ENTITY_NAME_DISPLAY_CUSTOM:
                    if not custom_name and strict:
                        raise ValueError("missing dashboard entity custom name")
                    if custom_name:
                        options["custom_name"] = custom_name
        if secondary:
            if secondary not in DASHBOARD_ENTITY_SECONDARY_INFO_OPTIONS:
                if strict:
                    raise ValueError("invalid dashboard entity secondary info mode")
            else:
                options["secondary"] = secondary
        if options:
            result[entity_id] = options
    return result


def dashboard_entity_name_display_override(
    overrides: DashboardEntityDisplayOverrides,
    entity_id: str,
    fallback: str = DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME,
) -> str:
    """Return the name-display mode for one entity."""

    return overrides.get(entity_id, {}).get("name", fallback)


def dashboard_entity_secondary_info_override(
    overrides: DashboardEntityDisplayOverrides,
    entity_id: str,
    fallback: str = DASHBOARD_ENTITY_SECONDARY_INFO_STATE,
) -> str:
    """Return the secondary-info mode for one entity."""

    return overrides.get(entity_id, {}).get("secondary", fallback)


def dashboard_entity_custom_name_override(
    overrides: DashboardEntityDisplayOverrides,
    entity_id: str,
) -> str:
    """Return the custom display name for one entity."""

    return overrides.get(entity_id, {}).get("custom_name", "")


def _iter_dashboard_entity_values(value: Any, *, strict: bool) -> tuple[Any, ...]:
    """Return raw entity values from config-flow string or selector data."""

    if value in (None, ""):
        return ()
    if isinstance(value, str):
        return tuple(item for item in re.split(r"[\s,]+", value) if item)
    if isinstance(value, (list, tuple, set)):
        return tuple(value)
    if strict:
        raise ValueError("invalid dashboard entities")
    return ()


def _normalize_dashboard_entity_id(value: Any, *, strict: bool) -> str | None:
    """Return one normalized dashboard entity id."""

    entity_id = str(value or "").strip().lower()
    if not entity_id:
        return None
    if "." not in entity_id:
        return _invalid_dashboard_entity(strict)
    domain, object_id = entity_id.split(".", 1)
    if (
        domain not in DASHBOARD_ENTITY_DOMAIN_SET
        or not ENTITY_OBJECT_ID_RE.fullmatch(object_id)
    ):
        return _invalid_dashboard_entity(strict)
    return entity_id


def _invalid_dashboard_entity(strict: bool) -> None:
    if strict:
        raise ValueError("invalid dashboard entity")
    return None
