"""The Display submenu of the settings and its list of pages."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from custom_components.bticino_c300x.const import (
    CONF_ACTIONS,
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_DASHBOARD_ENTITIES,
    CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
    CONF_DASHBOARD_PAGES,
    CONF_DEVICE_UI_ENABLED,
    CONF_ENERGY_PAGE,
    CONF_VIDEO_ENABLED,
    CONF_WEATHER_ENTITY_ID,
)
from custom_components.bticino_c300x.dashboard_entities import DASHBOARD_STATUS_PAGE
from tests.test_config_flow_helpers import _options_flow


def _entry(**options: Any) -> SimpleNamespace:
    return SimpleNamespace(
        data={
            CONF_AGENT_HOST: "agent.local", CONF_AGENT_PORT: 8091, CONF_AGENT_TOKEN: "token",
            CONF_VIDEO_ENABLED: False, CONF_DEVICE_UI_ENABLED: True, CONF_ACTIONS: {},
        },
        options=options,
        runtime_data=None,
    )


def _pages_entry() -> SimpleNamespace:
    return _entry(**{
        CONF_WEATHER_ENTITY_ID: "weather.home",
        CONF_DASHBOARD_ENTITIES: ["switch.entry", "light.hall", "sensor.garden"],
        CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: {
            "switch.entry": {"page": "Doors", "secondary": "last_changed"},
            "light.hall": {"page": "Doors"},
            "sensor.garden": {"page": "Garden"},
        },
        CONF_DASHBOARD_PAGES: [
            {"name": DASHBOARD_STATUS_PAGE, "order": 1}, {"name": "Doors", "order": 2},
            {"name": "Garden", "order": 3},
        ],
    })


def _step(flow: Any, step_id: str, user_input: dict[str, Any] | None = None) -> dict[str, Any]:
    return asyncio.run(getattr(flow, f"async_step_{step_id}")(user_input))


def _section_fields(form: dict[str, Any]) -> dict[str, list[str]]:
    return {
        str(key): [str(field) for field in value.schema.schema]
        for key, value in form["data_schema"].schema.items()
    }


def test_the_settings_menu_has_one_display_entry() -> None:
    menu = _step(_options_flow(_pages_entry()), "init")
    assert menu["menu_options"] == [
        "connection", "features", "device_activations", "display", "done",
    ]


def test_the_display_submenu_lists_its_areas_and_the_way_back() -> None:
    menu = _step(_options_flow(_pages_entry()), "display")
    assert (menu["type"], menu["step_id"]) == ("menu", "display")
    assert menu["menu_options"] == [
        "dashboard", "dashboard_page_list", "dashboard_entity_display", "dashboard_alarm", "init",
    ]
    # Without the Display patch there are no pages or tiles to set up.
    entry = _pages_entry()
    entry.data[CONF_DEVICE_UI_ENABLED] = False
    assert _step(_options_flow(entry), "display")["menu_options"] == [
        "dashboard", "dashboard_alarm", "init",
    ]


def test_the_page_list_shows_the_pages_in_display_order_and_one_entry_to_add() -> None:
    menu = _step(_options_flow(_pages_entry()), "dashboard_page_list")
    assert (menu["type"], menu["step_id"]) == ("menu", "dashboard_page_list")
    assert menu["menu_options"] == [
        "page_1", "page_2", "page_3",
        "energy_page", "agenda_page", "leave_home_page", "situations_page",
        "page_new", "display",
    ]
    placeholders = menu["description_placeholders"]
    assert (placeholders["page_2_name"], placeholders["page_2_position"]) == (": Doors", " 2")
    assert placeholders["energy_page_position"] == ""


def test_a_page_entry_opens_a_form_with_that_page_only() -> None:
    flow = _options_flow(_pages_entry())
    _step(flow, "dashboard_page_list")
    form = _step(flow, "page_2")
    assert form["step_id"] == "dashboard_pages"
    assert _section_fields(form) == {"page_2": ["name", "position", "entities"]}
    section = next(iter(form["data_schema"].schema.values()))
    assert section.options == {"collapsed": False}
    energy = _step(flow, "energy_page")
    assert list(_section_fields(energy)) == [CONF_ENERGY_PAGE]


def test_saving_one_page_keeps_the_other_pages_and_returns_to_the_list() -> None:
    entry = _pages_entry()
    flow = _options_flow(entry)
    _step(flow, "dashboard_page_list")
    _step(flow, "page_2")
    result = _step(flow, "dashboard_pages", {
        "page_2": {"name": "Entrance", "position": 2, "entities": ["light.hall", "switch.entry"]},
    })
    assert (result["type"], result["step_id"]) == ("menu", "dashboard_page_list")
    assert result["description_placeholders"]["page_2_name"] == ": Entrance"
    assert entry.options[CONF_DASHBOARD_PAGES] == [
        {"name": DASHBOARD_STATUS_PAGE, "order": 1}, {"name": "Entrance", "order": 2},
        {"name": "Garden", "order": 3},
    ]
    assert entry.options[CONF_DASHBOARD_ENTITIES] == ["light.hall", "switch.entry", "sensor.garden"]
    overrides = entry.options[CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES]
    # The tile setting of a kept entity survives, and the other page is untouched.
    assert overrides["switch.entry"] == {"secondary": "last_changed", "page": "Entrance"}
    assert overrides["sensor.garden"] == {"page": "Garden"}
    assert entry.options[CONF_WEATHER_ENTITY_ID] == "weather.home"


def test_a_page_form_sent_as_it_opens_changes_nothing() -> None:
    entry = _pages_entry()
    flow = _options_flow(entry)
    _step(flow, "dashboard_page_list")
    form = _step(flow, "page_3")
    before = dict(entry.options)
    fields = next(iter(form["data_schema"].schema.values())).schema.schema
    unchanged = {
        str(field): (field.description or {}).get("suggested_value") for field in fields
    }
    result = _step(flow, "dashboard_pages", {"page_3": unchanged})
    assert result["step_id"] == "dashboard_page_list"
    assert entry.options == before


def test_the_add_entry_opens_the_first_free_page_and_saves_it() -> None:
    entry = _pages_entry()
    flow = _options_flow(entry)
    _step(flow, "dashboard_page_list")
    form = _step(flow, "page_new")
    assert list(_section_fields(form)) == ["page_4"]
    result = _step(flow, "dashboard_pages", {
        "page_4": {"name": "Cellar", "entities": ["light.cellar"]},
    })
    assert result["step_id"] == "dashboard_page_list"
    assert "page_4" in result["menu_options"]
    assert [page["name"] for page in entry.options[CONF_DASHBOARD_PAGES]] == [
        DASHBOARD_STATUS_PAGE, "Doors", "Garden", "Cellar",
    ]


def test_an_emptied_page_is_removed() -> None:
    entry = _pages_entry()
    flow = _options_flow(entry)
    _step(flow, "dashboard_page_list")
    _step(flow, "page_3")
    result = _step(flow, "dashboard_pages", {"page_3": {}})
    assert "page_3" not in result["menu_options"]
    assert [page["name"] for page in entry.options[CONF_DASHBOARD_PAGES]] == [DASHBOARD_STATUS_PAGE, "Doors"]
    assert entry.options[CONF_DASHBOARD_ENTITIES] == ["switch.entry", "light.hall"]


def test_a_page_error_comes_back_on_the_same_single_page_form() -> None:
    entry = _pages_entry()
    flow = _options_flow(entry)
    _step(flow, "dashboard_page_list")
    _step(flow, "page_3")
    before = dict(entry.options)
    # The name of another page, and an entity that page already shows.
    refused = _step(flow, "dashboard_pages", {
        "page_3": {"name": "doors", "entities": ["sensor.garden"]},
    })
    assert refused["step_id"] == "dashboard_pages"
    assert refused["errors"] == {"page_3": "dashboard_page_name_duplicate"}
    assert list(_section_fields(refused)) == ["page_3"]
    assert refused["description_placeholders"]["page_3_name"] == ": doors"
    assert entry.options == before
    taken = _step(flow, "dashboard_pages", {
        "page_3": {"name": "Garden", "entities": ["switch.entry"]},
    })
    assert taken["errors"] == {"page_3": "dashboard_entity_on_several_pages"}


def test_a_built_in_page_is_switched_on_from_the_list() -> None:
    entry = _pages_entry()
    flow = _options_flow(entry)
    _step(flow, "dashboard_page_list")
    _step(flow, "energy_page")
    result = _step(flow, "dashboard_pages", {
        CONF_ENERGY_PAGE: {"enabled": True, "position": 2, "view_today": True},
    })
    assert result["step_id"] == "dashboard_page_list"
    assert entry.options[CONF_ENERGY_PAGE]["enabled"] is True
    assert result["menu_options"].index("energy_page") == 1
    assert [page["name"] for page in entry.options[CONF_DASHBOARD_PAGES]] == [
        DASHBOARD_STATUS_PAGE, "Doors", "Garden",
    ]


def test_a_display_area_returns_to_the_display_submenu() -> None:
    entry = _pages_entry()
    flow = _options_flow(entry)
    _step(flow, "display")
    result = _step(flow, "dashboard_alarm", {"alarm_entity_id": "alarm_control_panel.home"})
    assert (result["type"], result["step_id"]) == ("menu", "display")
    # From the settings menu an area returns there, as before.
    _step(flow, "init")
    result = _step(flow, "dashboard_alarm", {"alarm_entity_id": ""})
    assert (result["type"], result["step_id"]) == ("menu", "init")
