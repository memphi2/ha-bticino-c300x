"""Titles and order of the sections in the display-pages form.

The form reads like the display: the pages that are shown come first, in
display order and numbered from 1. Pages that are not shown follow without a
number: built-in pages that are switched off and named pages without
entities. The free sections for new pages are last. Nothing here changes what
is stored.
"""

from collections.abc import Mapping
from typing import Any

from .config_flow_optional_pages import optional_pages_input
from .const import CONF_DASHBOARD_STATUS_PAGE_ENABLED, CONF_ENERGY_PAGE
from .dashboard_energy import normalize_energy_page
from .dashboard_entities import DASHBOARD_PAGE_MAX_COUNT, normalize_dashboard_page_name
from .dashboard_optional_config import optional_page_values
from .dashboard_page_order import SPECIAL_PAGE_ORDER, page_layout_slots, page_position

_NOT_SHOWN_ORDER = ("page_1", *SPECIAL_PAGE_ORDER)


def _posted_page_on(key: str, values: Mapping[str, Any], saved: Mapping[str, Any]) -> bool:
    if values.get("enabled", saved.get("enabled")) is not True:
        return False
    return key != CONF_ENERGY_PAGE or any(
        value is True for field, value in values.items() if field.startswith("view_")
    )


def page_form_positions(
    layout: list[dict[str, Any]],
    saved: dict[str, Any],
    posted: dict[str, Any] | None = None,
) -> dict[str, int | None]:
    """Return each section's place in the stored page order, or None for no place.

    This is what the position fields show and what saving them keeps: every
    used regular page has a place, shown on the display or not, and so has
    every optional page that is switched on. A form shown again after an
    error has the positions that were sent instead.
    """
    special = {
        CONF_ENERGY_PAGE: normalize_energy_page(saved.get(CONF_ENERGY_PAGE)),
        **optional_page_values(saved),
    }
    regular_keys = {page["name"]: f"page_{slot}" for slot, page in enumerate(layout, 1)}
    positions: dict[str, int | None] = {
        f"page_{slot}": None for slot in range(1, DASHBOARD_PAGE_MAX_COUNT + 1)
    }
    positions.update(dict.fromkeys(SPECIAL_PAGE_ORDER))
    for position, (kind, name) in enumerate(page_layout_slots(
        [page["name"] for page in sorted(layout, key=lambda page: page["order"])], special,
    ), 1):
        positions[regular_keys[name] if kind == "regular" else name] = position
    if posted is not None:
        for slot in range(1, DASHBOARD_PAGE_MAX_COUNT + 1):
            key = f"page_{slot}"
            values = posted.get(key)
            values = values if isinstance(values, dict) else {}
            used = slot == 1 or normalize_dashboard_page_name(values.get("name", "")) or values.get("entities")
            positions[key] = page_position(values.get("position"), slot) if used else None
        defaults = {CONF_ENERGY_PAGE: normalize_energy_page(None), **optional_pages_input(saved, posted)}
        for key in SPECIAL_PAGE_ORDER:
            if isinstance(values := posted.get(key), dict):
                positions[key] = (
                    page_position(values.get("position"), defaults[key]["position"])
                    if _posted_page_on(key, values, special[key]) else None
                )
    return positions


def _tie_rank(key: str) -> int:
    if key in SPECIAL_PAGE_ORDER:
        return SPECIAL_PAGE_ORDER.index(key)
    return len(SPECIAL_PAGE_ORDER) + int(key.removeprefix("page_"))


def page_form_numbers(
    layout: list[dict[str, Any]],
    saved: dict[str, Any],
    posted: dict[str, Any] | None = None,
) -> dict[str, int | None]:
    """Return the page number each section title shows, or None for no number.

    The numbers count the pages the display shows, from 1 in display order.
    A status page that is switched off and a page without entities have a
    place in the stored order but no number. Two pages sent with the same
    position are numbered the way they will be saved: Energy, Agenda, Leave
    home, Situations, then the regular pages.
    """
    positions = page_form_positions(layout, saved, posted)

    def shown(key: str) -> bool:
        if key in SPECIAL_PAGE_ORDER:
            return True
        slot = int(key.removeprefix("page_"))
        values = posted.get(key) if posted is not None else None
        values = values if isinstance(values, dict) else {}
        if slot == 1:
            enabled = saved.get(CONF_DASHBOARD_STATUS_PAGE_ENABLED, True)
            return values.get("enabled", enabled) is True
        if posted is not None:
            return bool(values.get("entities"))
        return slot <= len(layout) and bool(layout[slot - 1]["entities"])

    numbers: dict[str, int | None] = dict.fromkeys(positions)
    listed = sorted(
        (position, _tie_rank(key), key)
        for key, position in positions.items()
        if position is not None and shown(key)
    )
    numbers.update({key: number for number, (_, _, key) in enumerate(listed, 1)})
    return numbers


def ordered_page_sections(
    fields: dict[Any, Any],
    positions: dict[str, int | None],
    numbers: dict[str, int | None],
) -> dict[Any, Any]:
    """Sort the sections: numbered pages, pages that are not shown, the free sections."""

    def order(marker: Any) -> tuple[int, int]:
        key = str(marker)
        number = numbers[key]
        if number is not None:
            return 0, number
        if key in _NOT_SHOWN_ORDER:
            return 1, _NOT_SHOWN_ORDER.index(key)
        slot = int(key.removeprefix("page_"))
        return (1 if positions[key] is not None else 2), len(_NOT_SHOWN_ORDER) + slot

    return {key: fields[key] for key in sorted(fields, key=order)}
