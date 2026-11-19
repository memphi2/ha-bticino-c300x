"""Titles and order of the sections in the display-pages form.

The form reads like the display: the pages that are shown come first, in
display order and numbered from 1. Built-in pages that are switched off
follow without a number, and the free sections for new pages are last.
Nothing here changes what is stored.
"""

from collections.abc import Mapping
from typing import Any

from .config_flow_optional_pages import optional_pages_input
from .const import CONF_ENERGY_PAGE
from .dashboard_energy import normalize_energy_page
from .dashboard_entities import DASHBOARD_PAGE_MAX_COUNT, normalize_dashboard_page_name
from .dashboard_optional_config import optional_page_values
from .dashboard_page_order import SPECIAL_PAGE_ORDER, page_layout_slots, page_position


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
    """Return the number each section title shows, or None for no number.

    A page has a number when it takes a place in the page order: every used
    regular page and every built-in page that is switched on. A form shown
    again after an error shows the positions that were sent instead.
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


def ordered_page_sections(fields: dict[Any, Any], positions: dict[str, int | None]) -> dict[Any, Any]:
    """Sort the sections: numbered pages, built-in pages that are off, the free sections.

    Two pages sent with the same position are listed the way they will be
    saved: Energy, Agenda, Leave home, Situations, then the regular pages.
    """

    def order(marker: Any) -> tuple[int, int, int]:
        key = str(marker)
        special = key in SPECIAL_PAGE_ORDER
        rank = SPECIAL_PAGE_ORDER.index(key) if special else len(SPECIAL_PAGE_ORDER) + int(key.removeprefix("page_"))
        position = positions[key]
        if position is not None:
            return 0, position, rank
        return (1 if special else 2), 0, rank

    return {key: fields[key] for key in sorted(fields, key=order)}
