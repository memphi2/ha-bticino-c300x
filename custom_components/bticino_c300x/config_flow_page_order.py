"""Presentation-only positions and ordering for the display-pages form."""

from typing import Any

from .const import CONF_ENERGY_PAGE
from .dashboard_energy import normalize_energy_page
from .dashboard_entities import DASHBOARD_PAGE_MAX_COUNT, normalize_dashboard_page_name
from .dashboard_optional_config import optional_page_values
from .dashboard_page_order import SPECIAL_PAGE_ORDER, page_layout_slots, page_position


def page_form_positions(
    layout: list[dict[str, Any]],
    saved: dict[str, Any],
    posted: dict[str, Any] | None = None,
) -> dict[str, int | None]:
    """Resolve saved logical slots; on retry show the requested positions.

    Disabled special pages keep their configured position. Unused regular
    sections have no display position, but remain available after used ones.
    This does not renumber stored pages or remove invisible logical slots.
    """
    special = {
        CONF_ENERGY_PAGE: normalize_energy_page(saved.get(CONF_ENERGY_PAGE)),
        **optional_page_values(saved),
    }
    regular_keys = {page["name"]: f"page_{slot}" for slot, page in enumerate(layout, 1)}
    positions: dict[str, int | None] = {
        f"page_{slot}": None for slot in range(1, DASHBOARD_PAGE_MAX_COUNT + 1)
    }
    positions.update({key: value["position"] for key, value in special.items()})
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
        defaults = {CONF_ENERGY_PAGE: normalize_energy_page(None), **optional_page_values({})}
        for key in SPECIAL_PAGE_ORDER:
            if isinstance(values := posted.get(key), dict):
                positions[key] = page_position(values.get("position"), defaults[key]["position"])
    return positions


def ordered_page_sections(fields: dict[Any, Any], positions: dict[str, int | None]) -> dict[Any, Any]:
    """Sort meaningful sections by position, retaining stable form section keys."""
    def order(marker: Any) -> tuple[bool, int, int]:
        key = str(marker)
        position = positions[key]
        priority = SPECIAL_PAGE_ORDER.index(key) if key in SPECIAL_PAGE_ORDER else len(SPECIAL_PAGE_ORDER)
        return position is None, position or 0, priority

    return {key: fields[key] for key in sorted(fields, key=order)}
