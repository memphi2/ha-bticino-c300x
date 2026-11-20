"""Pages step of the display dashboard settings.

The display has up to ``DASHBOARD_PAGE_MAX_COUNT`` regular pages. The form has one
section per page: the status page carries the badges and the weather card,
set here as its Weather field; every other page has a name,
which the display shows as its heading. Each section has a position from 1 to 12,
which orders the pages, and the entities shown on that page, in the order they
are picked.

The entities are stored as before: the dashboard entity list in page order
and the page name of each entity in its display overrides. The page list
stores each page's name and its position, numbered from 1 in display order.

Energy, Agenda, Leave home and Situations are independently enabled extra pages. They
store absolute display positions; regular pages stay numbered among themselves.
The shared layout helper converts between these positions for the form and
the display. Equal requested positions put Energy, Agenda, Leave home and Situations
before regular pages, in that order. Disabled pages retain their settings.
Section titles and order follow display positions, not internal form slot keys;
unused regular sections remain available at the end.
"""

from __future__ import annotations

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
from .config_flow_optional_pages import (
    optional_page_sections,
    optional_pages_errors,
    optional_pages_input,
)
from .config_flow_optional_pages import (
    page_position_selector as _page_position_selector,
)
from .config_flow_page_order import (
    ordered_page_sections,
    page_form_numbers,
    page_form_positions,
)
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
from .dashboard_page_order import (
    PAGE_POSITION_MAX as POSITION_MAX,
)
from .dashboard_page_order import (
    page_position as _page_position,
)
from .dashboard_page_order import (
    submitted_special_positions,
)
from .schema_compat import vol

PAGE_NAME_FIELD = "name"
PAGE_POSITION_FIELD = "position"
PAGE_ENTITIES_FIELD = "entities"
PAGE_WEATHER_FIELD = CONF_WEATHER_ENTITY_ID
PAGE_ENABLED_FIELD = "enabled"
ENERGY_ENABLED_FIELD = "enabled"
ENERGY_VIEWS_FIELD = "views"


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


def _energy_view_selections(energy: dict[str, Any], posted: Any) -> list[str]:
    """Overlay explicit toggles on saved views, retaining legacy form posts."""

    if not isinstance(posted, dict):
        return list(energy["views"])
    views = energy["views"]
    if ENERGY_VIEWS_FIELD in posted:
        views = normalize_energy_page({"views": posted[ENERGY_VIEWS_FIELD]})["views"]
    return [
        view for view in ENERGY_VIEWS
        if posted.get(f"view_{view}", view in views) is True
    ]


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
    positions = page_form_positions(layout, dashboard_input)

    def shown(slot: int, field: str, saved: Any) -> Any:
        if posted is None:
            return saved
        values = posted.get(page_section_key(slot))
        return values.get(field) if isinstance(values, dict) else None

    fields: dict[Any, Any] = {}
    for slot in range(1, DASHBOARD_PAGE_MAX_COUNT + 1):
        page = layout[slot - 1] if slot <= len(layout) else None
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
            shown(slot, PAGE_POSITION_FIELD, positions[page_section_key(slot)]),
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
            {"collapsed": slot > len(layout) + 1},
        )
    def energy_shown(field: str, saved: Any) -> Any:
        if posted is None:
            return saved
        values = posted.get(CONF_ENERGY_PAGE)
        return values.get(field) if isinstance(values, dict) else None

    posted_energy = posted.get(CONF_ENERGY_PAGE) if posted is not None else None
    selected_views = _energy_view_selections(energy, posted_energy)
    enabled = (
        posted_energy.get(ENERGY_ENABLED_FIELD, energy["enabled"]) is True
        if isinstance(posted_energy, dict) else energy["enabled"]
    )
    fields[vol.Required(CONF_ENERGY_PAGE)] = section(
        vol.Schema({
            vol.Required(
                ENERGY_ENABLED_FIELD,
                default=enabled,
            ): selector.BooleanSelector(),
            _optional_suggested(
                PAGE_POSITION_FIELD,
                energy_shown(PAGE_POSITION_FIELD, min(energy["position"], POSITION_MAX)),
            ): _page_position_selector(),
            **{
                vol.Required(f"view_{view}", default=view in selected_views): selector.BooleanSelector()
                for view in ENERGY_VIEWS
            },
        }),
        {"collapsed": not enabled},
    )
    fields.update(optional_page_sections(dashboard_input, posted))
    return vol.Schema(ordered_page_sections(
        fields,
        page_form_positions(layout, dashboard_input, posted),
        page_form_numbers(layout, dashboard_input, posted),
    ))


def dashboard_pages_placeholders(
    dashboard_input: dict[str, Any],
    user_input: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Return the page names and positions the section titles show.

    A named page's section is titled with its name, as ": name" after the
    page number. A page the display does not show has no number. A free
    section, where a page can be added, is titled with a plus sign. A form
    shown again with errors shows the names that were sent.
    """

    layout = dashboard_page_layout(dashboard_input)
    positions = page_form_positions(layout, dashboard_input, user_input)
    placeholders = {
        f"{key}_position": f" {number}" if number is not None else ""
        for key, number in page_form_numbers(layout, dashboard_input, user_input).items()
    }
    for slot in range(2, DASHBOARD_PAGE_MAX_COUNT + 1):
        if user_input is not None:
            values = user_input.get(page_section_key(slot)) or {}
            name = normalize_dashboard_page_name(values.get(PAGE_NAME_FIELD, ""))
        else:
            name = layout[slot - 1]["name"] if slot <= len(layout) else ""
        free = slot > len(layout) and positions[page_section_key(slot)] is None
        placeholders[page_name_placeholder(slot)] = f": {name}" if name else " +" if free else ""
    return placeholders


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

    errors: dict[str, str] = optional_pages_errors(user_input)
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
    # posted section an emptied position is the default one. Explicit toggles
    # override saved selections; switching all off retains the global intent.
    energy = normalize_energy_page(dashboard_input.get(CONF_ENERGY_PAGE))
    posted_energy = user_input.get(CONF_ENERGY_PAGE)
    if isinstance(posted_energy, dict):
        energy = normalize_energy_page({
            "enabled": posted_energy.get(ENERGY_ENABLED_FIELD, energy["enabled"]) is True,
            "position": _page_position(
                posted_energy.get(PAGE_POSITION_FIELD), normalize_energy_page(None)["position"]
            ),
            "views": _energy_view_selections(energy, posted_energy),
        })
    if errors:
        return dashboard_input, errors

    pages.sort(key=lambda page: page[:2])
    special_pages = submitted_special_positions(
        [page[0] for page in pages],
        {CONF_ENERGY_PAGE: energy, **optional_pages_input(dashboard_input, user_input)},
        {key for key, value in user_input.items() if isinstance(value, dict)},
    )
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
        **special_pages,
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
    }, errors
