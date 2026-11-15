"""Pages step of the display dashboard settings.

The display shows at most ``DASHBOARD_PAGE_MAX_COUNT`` pages. The form has one
section per page: the first is the status page, which carries the badges and
the weather card, set here as its Weather field; every other page has a name,
which the display shows as its heading. Each section has a position from 1 to ``DASHBOARD_PAGE_MAX_COUNT``,
which orders the pages, and the entities shown on that page, in the order they
are picked.

The entities are stored as before: the dashboard entity list in page order
and the page name of each entity in its display overrides. The page list
stores each page's name and its position, numbered from 1 in display order.

Directly after the status section comes the energy page, an optional ninth page. It
has no entities of its own, as it shows Home Assistant's Energy setup; its
section switches it on, places it among the other pages and selects its
views. Positions therefore run from 1 to ``DASHBOARD_PAGE_MAX_COUNT + 1``.
The energy page stores its own position on the display; the other pages
stay numbered among themselves, and the form shows each with the position it
has on the display. Where the energy page and another page ask for the same
position the energy page comes first, so it is the second page by default.
"""

from __future__ import annotations

import math
from typing import Any

from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from .config_flow_forms import (
    dashboard_entity_custom_name_selector as _page_name_selector,
)
from .config_flow_forms import optional_suggested as _optional_suggested
from .config_flow_forms import (
    weather_entity_selector as _weather_entity_selector,
)
from .config_flow_input import _weather_entity_id
from .const import (
    CONF_ALARM_PAGE_ENTITY_ID,
    CONF_DASHBOARD_ENTITIES,
    CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
    CONF_DASHBOARD_PAGES,
    CONF_DASHBOARD_STATUS_PAGE_ENABLED,
    CONF_ENERGY_PAGE,
    CONF_WEATHER_ENTITY_ID,
)
from .dashboard_energy import ENERGY_VIEWS, normalize_energy_page
from .dashboard_entities import (
    DASHBOARD_ENTITY_DOMAINS,
    DASHBOARD_PAGE_MAX_COUNT,
    DASHBOARD_STATUS_PAGE,
    normalize_dashboard_entity_display_overrides,
    normalize_dashboard_entity_ids,
    normalize_dashboard_page_name,
    normalize_dashboard_pages,
)
from .schema_compat import vol

PAGE_NAME_FIELD = "name"
PAGE_POSITION_FIELD = "position"
PAGE_ENTITIES_FIELD = "entities"
PAGE_WEATHER_FIELD = CONF_WEATHER_ENTITY_ID
PAGE_ENABLED_FIELD = "enabled"
ENERGY_ENABLED_FIELD = "enabled"
ENERGY_VIEWS_FIELD = "views"
POSITION_MAX = DASHBOARD_PAGE_MAX_COUNT + 1


def page_section_key(slot: int) -> str:
    """Return the form key of a page section; slot 1 is the status page."""

    return f"page_{slot}"


def page_name_placeholder(slot: int) -> str:
    """Return the placeholder that carries a section's page name."""

    return f"page_{slot}_name"


def _page_entity_selector() -> Any:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain=list(DASHBOARD_ENTITY_DOMAINS),
            multiple=True,
            reorder=True,
        ),
    )


def _energy_views_selector() -> Any:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=list(ENERGY_VIEWS),
            multiple=True,
            mode=selector.SelectSelectorMode.LIST,
            translation_key="energy_views",
        )
    )


def _page_position_selector() -> Any:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=1,
            max=POSITION_MAX,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def dashboard_page_layout(dashboard_input: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the pages the form shows, the status page first.

    Each page has its name, its position on the display (1 is the first page)
    and its entities. Entities keep the order the display gives them: their
    stored position within the page, then their place in the entity list.
    Pages keep the order the display shows them in. A page without a stored
    position, such as every page of an entry saved before pages could be set
    up, follows the stored ones in the order its name first appears, so the
    display does not change.
    """

    entities = normalize_dashboard_entity_ids(dashboard_input.get(CONF_DASHBOARD_ENTITIES, []))
    overrides = normalize_dashboard_entity_display_overrides(
        dashboard_input.get(CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES, {})
    )
    members: dict[str, list[tuple[int, int, str]]] = {}
    for index, entity_id in enumerate(entities, start=1):
        options = overrides.get(entity_id, {})
        order = int(options.get("order", index * 10))
        members.setdefault(options.get("page", ""), []).append((order, index, entity_id))

    names = [page["name"] for page in normalize_dashboard_pages(dashboard_input.get(CONF_DASHBOARD_PAGES, []))]
    if DASHBOARD_STATUS_PAGE not in names:
        names.insert(0, DASHBOARD_STATUS_PAGE)
    names += [name for name in members if name not in names]
    pages = [
        {
            "name": name,
            "order": position,
            "entities": [entity for _, _, entity in sorted(members.get(name, []))],
        }
        for position, name in enumerate(names, start=1)
    ]
    layout = [page for page in pages if page["name"] == DASHBOARD_STATUS_PAGE]
    layout += [page for page in pages if page["name"] != DASHBOARD_STATUS_PAGE]
    # An entry from before the page limit can use more pages than the form
    # has sections. Their entities stay selected, on the last page.
    for extra in layout[DASHBOARD_PAGE_MAX_COUNT:]:
        layout[DASHBOARD_PAGE_MAX_COUNT - 1]["entities"].extend(extra["entities"])
    return layout[:DASHBOARD_PAGE_MAX_COUNT]


def dashboard_pages_schema(
    dashboard_input: dict[str, Any],
    posted: dict[str, Any] | None = None,
) -> vol.Schema:
    """Return the pages form, one section per page.

    The sections of used pages are open, and so is the first free one, where
    a new page can be added; the other free sections are collapsed.

    A form shown again after an error passes what was sent as ``posted``.
    Each field then shows the sent value only. Home Assistant leaves an
    emptied field out of what it sends, so such a field stays empty instead
    of showing the saved value again.
    """

    layout = dashboard_page_layout(dashboard_input)
    energy = normalize_energy_page(dashboard_input.get(CONF_ENERGY_PAGE))

    def display_position(order: int) -> int:
        # The pages are numbered among themselves; the energy page, when on,
        # takes one position of the display.
        return order + 1 if energy["enabled"] and order >= energy["position"] else order

    def shown(slot: int, field: str, saved: Any) -> Any:
        if posted is None:
            return saved
        values = posted.get(page_section_key(slot))
        return values.get(field) if isinstance(values, dict) else None

    fields: dict[Any, Any] = {}
    free_section_shown = False
    for slot in range(1, DASHBOARD_PAGE_MAX_COUNT + 1):
        page = layout[slot - 1] if slot <= len(layout) else None
        collapsed = False
        if page is None:
            collapsed = free_section_shown
            free_section_shown = True
        page_fields: dict[Any, Any] = {}
        if slot == 1:
            page_fields[vol.Required(
                PAGE_ENABLED_FIELD,
                default=bool(shown(
                    slot, PAGE_ENABLED_FIELD,
                    dashboard_input.get(CONF_DASHBOARD_STATUS_PAGE_ENABLED, True),
                )),
            )] = selector.BooleanSelector()
            page_fields[_optional_suggested(
                PAGE_WEATHER_FIELD,
                shown(slot, PAGE_WEATHER_FIELD, dashboard_input.get(CONF_WEATHER_ENTITY_ID)),
            )] = _weather_entity_selector()
        if slot > 1:
            page_fields[_optional_suggested(
                PAGE_NAME_FIELD,
                shown(slot, PAGE_NAME_FIELD, page["name"] if page else "") or "",
            )] = _page_name_selector()
        page_fields[_optional_suggested(
            PAGE_POSITION_FIELD,
            shown(slot, PAGE_POSITION_FIELD, display_position(page["order"]) if page else None),
        )] = _page_position_selector()
        page_fields[_optional_suggested(
            PAGE_ENTITIES_FIELD,
            shown(
                slot,
                PAGE_ENTITIES_FIELD,
                page["entities"] if page and page["entities"] else None,
            ),
        )] = _page_entity_selector()
        fields[vol.Required(page_section_key(slot))] = section(
            vol.Schema(page_fields),
            {"collapsed": collapsed},
        )
    def energy_shown(field: str, saved: Any) -> Any:
        if posted is None:
            return saved
        values = posted.get(CONF_ENERGY_PAGE)
        return values.get(field) if isinstance(values, dict) else None

    fields[vol.Required(CONF_ENERGY_PAGE)] = section(
        vol.Schema({
            vol.Required(
                ENERGY_ENABLED_FIELD,
                default=bool(energy_shown(ENERGY_ENABLED_FIELD, energy["enabled"])),
            ): selector.BooleanSelector(),
            _optional_suggested(
                PAGE_POSITION_FIELD,
                energy_shown(PAGE_POSITION_FIELD, min(energy["position"], POSITION_MAX)),
            ): _page_position_selector(),
            _optional_suggested(
                ENERGY_VIEWS_FIELD, energy_shown(ENERGY_VIEWS_FIELD, energy["views"]),
            ): _energy_views_selector(),
        }),
        {"collapsed": not energy["enabled"]},
    )
    keys = list(fields)
    return vol.Schema({
        key: fields[key] for key in [keys[0], keys[-1], *keys[1:-1]]
    })


def dashboard_pages_placeholders(
    dashboard_input: dict[str, Any],
    user_input: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Return the page names the section titles show.

    A named page's section is titled with its name, as ": name" after the
    page number; a section without a name keeps the number alone. A form
    shown again with errors shows the names that were sent.
    """

    layout = dashboard_page_layout(dashboard_input)
    placeholders: dict[str, str] = {}
    for slot in range(2, DASHBOARD_PAGE_MAX_COUNT + 1):
        if user_input is not None:
            values = user_input.get(page_section_key(slot)) or {}
            name = normalize_dashboard_page_name(values.get(PAGE_NAME_FIELD, ""))
        else:
            name = layout[slot - 1]["name"] if slot <= len(layout) else ""
        placeholders[page_name_placeholder(slot)] = f": {name}" if name else ""
    return placeholders


def _page_position(value: Any, default: int) -> int:
    try:
        position = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(position):
        return default
    return int(min(float(POSITION_MAX), max(1.0, position)) + 0.5)


def dashboard_pages_input(
    dashboard_input: dict[str, Any],
    user_input: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Merge a posted pages form into the dashboard settings.

    Home Assistant leaves a field the user emptied out of a section, so a
    missing name or entity list is empty and a missing position is the
    section's own number. A page is used when it has a name or entities; the
    status page is always used, and a page with entities needs a name, except
    the page without a title that the saved entities already form. Pages
    with the same position keep the order of their sections. The weather of
    the status page is stored with the pages; a post without that section
    keeps the saved weather. Returns the settings and the form errors.
    """

    errors: dict[str, str] = {}
    pages: list[tuple[int, int, str, list[str]]] = []
    seen_names: set[str] = set()
    seen_entities: set[str] = set()
    # Entities saved without a page sit on a page without a title. That page
    # may stay as it is, so saving the form unchanged does not give it a
    # heading on the display; a name is needed once anything else goes onto it.
    untitled_entities = {
        entity_id
        for page in dashboard_page_layout(dashboard_input)
        if not page["name"]
        for entity_id in page["entities"]
    }
    for slot in range(1, DASHBOARD_PAGE_MAX_COUNT + 1):
        key = page_section_key(slot)
        values = user_input.get(key) or {}
        if slot == 1:
            name = DASHBOARD_STATUS_PAGE
        else:
            name = normalize_dashboard_page_name(values.get(PAGE_NAME_FIELD, ""))
        try:
            entities = list(normalize_dashboard_entity_ids(values.get(PAGE_ENTITIES_FIELD, []), strict=True))
        except ValueError:
            errors[key] = "invalid_dashboard_entities"
            continue
        if slot > 1 and not name and not entities:
            continue
        if not name and not set(entities) <= untitled_entities:
            errors[key] = "dashboard_page_name_missing"
            continue
        if slot > 1 and name.casefold() == DASHBOARD_STATUS_PAGE.casefold():
            errors[key] = "dashboard_page_name_reserved"
            continue
        if name.casefold() in seen_names:
            errors[key] = "dashboard_page_name_duplicate"
            continue
        if seen_entities.intersection(entities):
            errors[key] = "dashboard_entity_on_several_pages"
            continue
        seen_names.add(name.casefold())
        seen_entities.update(entities)
        pages.append((_page_position(values.get(PAGE_POSITION_FIELD), slot), slot, name, entities))
    weather = str(dashboard_input.get(CONF_WEATHER_ENTITY_ID) or "")
    status = user_input.get(page_section_key(1))
    status_enabled = dashboard_input.get(CONF_DASHBOARD_STATUS_PAGE_ENABLED, True) is True
    if status is not None:
        status_enabled = status.get(PAGE_ENABLED_FIELD, status_enabled) is True
        try:
            weather = _weather_entity_id(status.get(PAGE_WEATHER_FIELD, ""))
        except vol.Invalid:
            errors.setdefault(page_section_key(1), "invalid_weather_entity")
    # A post without the energy section keeps the saved energy page. In a
    # posted section an emptied position is the default one and an emptied
    # selection of views means all of them.
    energy = normalize_energy_page(dashboard_input.get(CONF_ENERGY_PAGE))
    posted_energy = user_input.get(CONF_ENERGY_PAGE)
    if posted_energy is not None:
        energy = normalize_energy_page({
            "enabled": posted_energy.get(ENERGY_ENABLED_FIELD) is True,
            "position": _page_position(
                posted_energy.get(PAGE_POSITION_FIELD), normalize_energy_page(None)["position"]
            ),
            "views": posted_energy.get(ENERGY_VIEWS_FIELD),
        })
    if errors:
        return dashboard_input, errors

    pages.sort(key=lambda page: page[:2])
    if posted_energy is not None and energy["enabled"]:
        # Its place on the display: after every page that asked for an
        # earlier position, before a page that asked for the same one.
        energy["position"] = 1 + sum(1 for page in pages if page[0] < energy["position"])
    overrides = normalize_dashboard_entity_display_overrides(
        dashboard_input.get(CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES, {})
    )
    # The Alarmo quick entity is on no page; its tile settings are kept.
    kept_entities = seen_entities | {
        str(dashboard_input.get(CONF_ALARM_PAGE_ENTITY_ID) or "")
    }
    ordered_entities: list[str] = []
    for _, _, name, page_entities in pages:
        for entity_id in page_entities:
            options = {
                key: value
                for key, value in overrides.get(entity_id, {}).items()
                if key not in ("page", "order")
            }
            options["page"] = name
            overrides[entity_id] = options
            ordered_entities.append(entity_id)
    return {
        **dashboard_input,
        CONF_WEATHER_ENTITY_ID: weather,
        CONF_DASHBOARD_STATUS_PAGE_ENABLED: status_enabled,
        CONF_DASHBOARD_ENTITIES: ordered_entities,
        CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: {
            entity_id: options
            for entity_id, options in overrides.items()
            if entity_id in kept_entities and options
        },
        CONF_DASHBOARD_PAGES: [
            {"name": name, "order": position}
            for position, (_, _, name, _) in enumerate(pages, start=1)
        ],
        CONF_ENERGY_PAGE: energy,
    }, errors
