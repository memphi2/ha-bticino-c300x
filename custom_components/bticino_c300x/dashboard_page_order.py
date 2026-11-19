"""Shared logical display slots for regular, Energy, Agenda and Leave home pages."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence, Set
from typing import Any

from .const import (
    CONF_AGENDA_PAGE,
    CONF_ENERGY_PAGE,
    CONF_LEAVE_HOME_PAGE,
    DASHBOARD_NAVIGATION_PAGER,
    DASHBOARD_NAVIGATION_TABS,
)
from .dashboard_entities import DASHBOARD_PAGE_MAX_COUNT

SPECIAL_PAGE_ORDER = (CONF_ENERGY_PAGE, CONF_AGENDA_PAGE, CONF_LEAVE_HOME_PAGE)
PAGE_POSITION_MAX = DASHBOARD_PAGE_MAX_COUNT + len(SPECIAL_PAGE_ORDER)
DASHBOARD_NAVIGATIONS = (DASHBOARD_NAVIGATION_PAGER, DASHBOARD_NAVIGATION_TABS)


def dashboard_navigation(value: Any) -> str:
    """Return how the display changes pages.

    The favourites bar shows the first pages as buttons along the bottom
    edge. Anything else, such as an entry saved before the bar existed, is
    the previous and next arrows.
    """

    return DASHBOARD_NAVIGATION_TABS if value == DASHBOARD_NAVIGATION_TABS else DASHBOARD_NAVIGATION_PAGER


def page_position(value: Any, default: int) -> int:
    """Match the page form's finite, clamped, nearest-integer positions."""
    try:
        position = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(position):
        return default
    return int(min(float(PAGE_POSITION_MAX), max(1.0, position)) + 0.5)


def special_page_active(key: str, settings: Mapping[str, Any]) -> bool:
    return settings.get("enabled") is True and (
        key != CONF_ENERGY_PAGE or bool(settings.get("views"))
    )


def page_layout_slots(
    regular_names: Sequence[str], special_pages: Mapping[str, Mapping[str, Any]],
) -> list[tuple[str, str]]:
    """Replay saved absolute special slots against relative regular-page order.

    Keep configured but invisible regular pages in this input; the caller
    removes empty slots after ordering. Ties are Energy, Agenda, Leave home,
    then regular pages. Insertion never reverses two tied special pages.
    """
    slots = [("regular", name) for name in regular_names]
    selected = sorted(
        (int(settings["position"]), priority, key)
        for priority, key in enumerate(SPECIAL_PAGE_ORDER)
        if (settings := special_pages.get(key)) is not None and special_page_active(key, settings)
    )
    previous = -1
    for position, _, key in selected:
        index = min(len(slots), max(previous + 1, position - 1))
        slots.insert(index, ("special", key))
        previous = index
    return slots


def submitted_special_positions(
    regular_positions: Sequence[int],
    special_pages: Mapping[str, Mapping[str, Any]],
    submitted: Set[str],
) -> dict[str, dict[str, Any]]:
    """Resolve form positions together; store active submitted pages at their rank.

    Regular pages still persist only relative order. Disabled or omitted
    special pages retain their position and all selections unchanged.
    """
    result = {key: dict(value) for key, value in special_pages.items()}
    requested = [(position, len(SPECIAL_PAGE_ORDER), index, "")
                 for index, position in enumerate(regular_positions)]
    requested.extend(
        (int(settings["position"]), priority, 0, key)
        for priority, key in enumerate(SPECIAL_PAGE_ORDER)
        if (settings := special_pages.get(key)) is not None and special_page_active(key, settings)
    )
    for rank, (_, _, _, key) in enumerate(sorted(requested), start=1):
        if key and key in submitted:
            result[key]["position"] = rank
    return result
