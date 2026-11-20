"""The Display submenu of the settings and its list of pages.

The settings menu has one Display entry. It opens a submenu with the Display
patch, the pages, the tiles and Alarmo. The pages are a list: every page of
the display is an entry that opens a form with that page's fields only.

A page form is the pages form of the setup reduced to one section. What it
posts is completed with the other sections as they are saved, so one page is
validated and stored as if the whole form had been sent. The other sections
are not on the form, so what the page asks of them is done for it: a new
position makes the pages in between move by one, and an entity the page takes
leaves the page that had it.
"""

from __future__ import annotations

from typing import Any, cast

from homeassistant.config_entries import ConfigFlowResult
from homeassistant.data_entry_flow import section

from .config_flow_dashboard import (
    dashboard_entity_display_has_fields,
    dashboard_input_defaults,
)
from .config_flow_dashboard_pages import (
    PAGE_ENTITIES_FIELD,
    PAGE_POSITION_FIELD,
    dashboard_page_layout,
    dashboard_pages_input,
    dashboard_pages_placeholders,
    dashboard_pages_schema,
    page_section_key,
)
from .config_flow_features import current_feature_options
from .const import CONF_DEVICE_UI_ENABLED
from .dashboard_entities import DASHBOARD_PAGE_MAX_COUNT
from .schema_compat import vol

PAGE_LIST_STEP = "dashboard_page_list"
NEW_PAGE_STEP = "page_new"
DISPLAY_STEP = "display"


def display_menu(config_entry: Any) -> list[str]:
    """Return the areas of the Display submenu, without its way back.

    Pages and tiles need the Display patch, which the first area switches on.
    The tiles need something to show as well: an entity on a page or the
    Alarmo quick entity. Alarmo works without the patch.
    """

    saved = current_feature_options(config_entry)
    menu = ["dashboard"]
    if saved[CONF_DEVICE_UI_ENABLED]:
        menu.append(PAGE_LIST_STEP)
        if dashboard_entity_display_has_fields(dashboard_input_defaults({}, saved)):
            menu.append("dashboard_entity_display")
    menu.append("dashboard_alarm")
    return menu


def page_list(dashboard_input: dict[str, Any]) -> list[str]:
    """Return the entries of the page list in the order of the display.

    Every used page and every built-in page is an entry. The free sections
    are one entry, which adds a page, as long as one is free.
    """

    used = len(dashboard_page_layout(dashboard_input))
    entries = [
        key
        for key in map(str, dashboard_pages_schema(dashboard_input).schema)
        if not key.startswith("page_") or int(key.removeprefix("page_")) <= used
    ]
    if used < DASHBOARD_PAGE_MAX_COUNT:
        entries.append(NEW_PAGE_STEP)
    return entries


def unchanged_pages_post(dashboard_input: dict[str, Any]) -> dict[str, Any]:
    """Return what the whole pages form posts when it is sent as it opens."""

    post: dict[str, Any] = {}
    for marker, fields in dashboard_pages_schema(dashboard_input).schema.items():
        values: dict[str, Any] = {}
        for field in fields.schema.schema:
            default: Any = getattr(field, "default", vol.UNDEFINED)
            suggested = (getattr(field, "description", None) or {}).get("suggested_value")
            if callable(default):
                values[str(field)] = default()
            elif suggested is not None:
                values[str(field)] = suggested
        post[str(marker)] = values
    return post


def single_page_post(
    dashboard_input: dict[str, Any], key: str, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Complete the post of one page form with the other pages as saved."""

    values = user_input.get(key)
    values = values if isinstance(values, dict) else {}
    post = unchanged_pages_post(dashboard_input)
    before = _position(post.get(key, {}).get(PAGE_POSITION_FIELD))
    after = _position(values.get(PAGE_POSITION_FIELD))
    taken = values.get(PAGE_ENTITIES_FIELD)
    taken = set(taken) if isinstance(taken, list) else set()
    for other_key, other in post.items():
        if other_key == key:
            continue
        place = _position(other.get(PAGE_POSITION_FIELD))
        if place is not None and after is not None and after != before:
            # The page takes its new place; the pages in between make room.
            if (before is None or after < before) and after <= place and (before is None or place < before):
                other[PAGE_POSITION_FIELD] = place + 1
            elif before is not None and before < place <= after:
                other[PAGE_POSITION_FIELD] = place - 1
        entities = other.get(PAGE_ENTITIES_FIELD)
        if isinstance(entities, list) and taken.intersection(entities):
            other[PAGE_ENTITIES_FIELD] = [entity for entity in entities if entity not in taken]
    return {**post, key: values}


def _position(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value):
        return None
    return int(value)


def single_page_schema(
    dashboard_input: dict[str, Any], key: str, posted: dict[str, Any] | None
) -> vol.Schema:
    """Return the pages form reduced to the opened page, its section open."""

    full = dashboard_pages_schema(
        dashboard_input,
        None if posted is None else single_page_post(dashboard_input, key, posted),
    )
    for marker, fields in full.schema.items():
        if str(marker) == key:
            return vol.Schema({marker: section(fields.schema, {"collapsed": False})})
    raise KeyError(key)


def single_page_errors(
    dashboard_input: dict[str, Any], key: str, errors: dict[str, str]
) -> dict[str, str]:
    """Return the errors for a form that shows the opened page only.

    An error on another page that the saved pages have without this form is
    shown above the form. Any other one comes from what the opened page asks
    for, whichever page the check names, and is shown on the opened page.
    """

    saved = dashboard_pages_input(dashboard_input, unchanged_pages_post(dashboard_input))[1]
    shown: dict[str, str] = {}
    for field, error in errors.items():
        shown.setdefault("base" if field != key and saved.get(field) == error else key, error)
    return shown


def _open_page(key: str) -> Any:
    async def step(self: Any, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._load_saved()
        self._page_key = key
        return cast(ConfigFlowResult, self._async_show_options_dashboard_pages_form(None, {}))

    step.__name__ = f"async_step_{key}"
    return step


class DisplayMenuSteps:
    """The Display submenu, the page list and the entry of each page."""

    _page_key: str | None = None
    _return_step = "init"

    async def async_step_display(
        self: Any, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the display areas; an area saved from here returns here."""

        self._page_key = None
        self._return_step = DISPLAY_STEP
        return cast(ConfigFlowResult, self.async_show_menu(
            step_id=DISPLAY_STEP,
            menu_options=[*display_menu(self._config_entry), "init"],
        ))

    async def async_step_dashboard_page_list(
        self: Any, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """List the pages of the display; a page saved from here returns here."""

        self._dashboard_options.clear()
        self._load_saved()
        self._page_key = None
        self._return_step = PAGE_LIST_STEP
        return cast(ConfigFlowResult, self.async_show_menu(
            step_id=PAGE_LIST_STEP,
            menu_options=[*page_list(self._dashboard_options), DISPLAY_STEP],
            description_placeholders=dashboard_pages_placeholders(self._dashboard_options),
        ))

    async def async_step_page_new(
        self: Any, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Open the first free page section."""

        self._load_saved()
        used = len(dashboard_page_layout(self._dashboard_options))
        if used >= DASHBOARD_PAGE_MAX_COUNT:
            return cast(ConfigFlowResult, await self.async_step_dashboard_page_list())
        self._page_key = page_section_key(used + 1)
        return cast(ConfigFlowResult, self._async_show_options_dashboard_pages_form(None, {}))


for _key in (
    *(page_section_key(slot) for slot in range(1, DASHBOARD_PAGE_MAX_COUNT + 1)),
    "energy_page", "agenda_page", "leave_home_page", "situations_page",
):
    setattr(DisplayMenuSteps, f"async_step_{_key}", _open_page(_key))
