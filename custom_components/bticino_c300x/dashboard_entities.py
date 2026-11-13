"""Dashboard entity selection helpers."""

from __future__ import annotations

import math
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
    "climate",
    "cover",
    "fan",
    "input_boolean",
    "input_button",
    "input_number",
    "input_select",
    "light",
    "media_player",
    "number",
    "select",
    "script",
    "scene",
    "sensor",
    "switch",
)
DASHBOARD_ENTITY_DOMAIN_SET = frozenset(DASHBOARD_ENTITY_DOMAINS)
# The alarm page has room for one plain action tile, not for a player.
ALARM_PAGE_ENTITY_DOMAINS = tuple(
    domain for domain in DASHBOARD_ENTITY_DOMAINS if domain != "media_player"
)
# A tile is half or full in each direction. "auto" is never stored: an entity
# without the key keeps the size its type has always had on the display.
DASHBOARD_TILE_SIZE_AUTO = "auto"
DASHBOARD_TILE_SIZES = ("half", "full")
DASHBOARD_TILE_SIZE_KEYS = ("width", "height")
DASHBOARD_PAGE_NAME_MAX_LENGTH = 60
DASHBOARD_POSITION_MAX = 10000
# The status page carries the badges and the weather card. Its internal name
# is the title the display hides; the other pages are named by the user.
DASHBOARD_STATUS_PAGE = "C300X"
DASHBOARD_PAGE_MAX_COUNT = 8
DashboardEntityDisplayOverrides = dict[str, dict[str, str]]
DashboardPage = dict[str, Any]


def normalize_dashboard_page_name(value: Any) -> str:
    """Return a page name with its whitespace collapsed, cut to the limit."""

    return " ".join(str(value or "").split())[:DASHBOARD_PAGE_NAME_MAX_LENGTH]


def normalize_dashboard_pages(value: Any, *, strict: bool = False) -> tuple[DashboardPage, ...]:
    """Return the configured display pages, ordered as the display shows them.

    Each page has a name and a position; the status page is named
    ``DASHBOARD_STATUS_PAGE`` and an empty name is the page without a title.
    Pages sort by position, then by the order they were stored in. A name
    appears once and there are at most ``DASHBOARD_PAGE_MAX_COUNT`` pages.
    """

    if value in (None, ""):
        return ()
    if not isinstance(value, (list, tuple)):
        if strict:
            raise ValueError("invalid dashboard pages")
        return ()
    pages: list[tuple[int, int, DashboardPage]] = []
    seen: set[str] = set()
    for index, raw_page in enumerate(value):
        if not isinstance(raw_page, dict):
            if strict:
                raise ValueError("invalid dashboard page")
            continue
        name = normalize_dashboard_page_name(raw_page.get("name"))
        if name in seen or any(ord(char) < 32 for char in name):
            if strict:
                raise ValueError("invalid dashboard page name")
            continue
        try:
            order = float(raw_page.get("order", 0))
            if isinstance(raw_page.get("order"), bool) or not math.isfinite(order):
                raise ValueError("invalid dashboard page order")
        except (TypeError, ValueError, OverflowError):
            if strict:
                raise ValueError("invalid dashboard page order") from None
            order = 0.0
        position = int(min(float(DASHBOARD_POSITION_MAX), max(0.0, order)) + 0.5)
        seen.add(name)
        pages.append((position, index, {"name": name, "order": position}))
    if len(pages) > DASHBOARD_PAGE_MAX_COUNT:
        if strict:
            raise ValueError("too many dashboard pages")
        pages = pages[:DASHBOARD_PAGE_MAX_COUNT]
    return tuple(page for _, _, page in sorted(pages, key=lambda entry: entry[:2]))


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
        if _is_weather_entity_id(raw_entity_id):
            # Releases before pages placed the weather card from here; it now
            # heads the status page, so a stored placement is dropped.
            continue
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
        page = str(raw_options.get("page", "") or "").strip()
        if page:
            if len(page) > DASHBOARD_PAGE_NAME_MAX_LENGTH or any(ord(char) < 32 for char in page):
                if strict:
                    raise ValueError("invalid dashboard page name")
            else:
                options["page"] = page
        if "order" in raw_options:
            try:
                order = float(raw_options["order"])
                if isinstance(raw_options["order"], bool) or not math.isfinite(order) or not order.is_integer() or not 0 <= order <= DASHBOARD_POSITION_MAX:
                    raise ValueError("invalid dashboard order")
                options["order"] = str(int(order))
            except (TypeError, ValueError, OverflowError):
                if strict:
                    raise ValueError("invalid dashboard order") from None
        for size_key in DASHBOARD_TILE_SIZE_KEYS:
            size = str(raw_options.get(size_key, "") or "").strip()
            if not size or size == DASHBOARD_TILE_SIZE_AUTO:
                continue
            if size not in DASHBOARD_TILE_SIZES:
                if strict:
                    raise ValueError("invalid dashboard tile size")
                continue
            options[size_key] = size
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


def _is_weather_entity_id(value: Any) -> bool:
    """Return whether a display-override key names a weather entity."""

    entity_id = str(value or "").strip().lower()
    domain, _, object_id = entity_id.partition(".")
    return domain == "weather" and bool(ENTITY_OBJECT_ID_RE.fullmatch(object_id))


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


def _invalid_dashboard_entity(strict: bool) -> str | None:
    if strict:
        raise ValueError("invalid dashboard entity")
    return None
