"""Dashboard entity selection helpers."""

from __future__ import annotations

import re
from typing import Any

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
