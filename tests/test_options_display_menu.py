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
    CONF_DASHBOARD_STATUS_PAGE_ENABLED,
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


def _names(entry: SimpleNamespace) -> list[str]:
    return [page["name"] for page in entry.options[CONF_DASHBOARD_PAGES]]


def _save_page(entry: SimpleNamespace, key: str, values: dict[str, Any]) -> dict[str, Any]:
    flow = _options_flow(entry)
    _step(flow, "dashboard_page_list")
    _step(flow, key)
    return _step(flow, "dashboard_pages", {key: values})


def test_a_new_position_swaps_a_page_with_its_neighbour() -> None:
    later = _pages_entry()
    _save_page(later, "page_2", {
        "name": "Doors", "position": 3, "entities": ["switch.entry", "light.hall"],
    })
    assert _names(later) == [DASHBOARD_STATUS_PAGE, "Garden", "Doors"]

    earlier = _pages_entry()
    _save_page(earlier, "page_3", {"name": "Garden", "position": 2, "entities": ["sensor.garden"]})
    assert _names(earlier) == [DASHBOARD_STATUS_PAGE, "Garden", "Doors"]


def test_a_new_position_moves_only_the_pages_in_between() -> None:
    entry = _pages_entry()
    entry.options[CONF_DASHBOARD_ENTITIES].append("light.cellar")
    entry.options[CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES]["light.cellar"] = {"page": "Cellar"}
    entry.options[CONF_DASHBOARD_PAGES].append({"name": "Cellar", "order": 4})
    entry.options[CONF_ENERGY_PAGE] = {"enabled": True, "position": 2}

    _save_page(entry, "page_4", {"name": "Cellar", "position": 3, "entities": ["light.cellar"]})

    assert _names(entry) == [DASHBOARD_STATUS_PAGE, "Cellar", "Doors", "Garden"]
    assert entry.options[CONF_ENERGY_PAGE]["position"] == 2


def test_an_added_page_lands_at_the_position_it_asks_for() -> None:
    entry = _pages_entry()
    flow = _options_flow(entry)
    _step(flow, "dashboard_page_list")
    _step(flow, "page_new")
    _step(flow, "dashboard_pages", {
        "page_4": {"name": "Cellar", "position": 2, "entities": ["light.cellar"]},
    })
    assert _names(entry) == [DASHBOARD_STATUS_PAGE, "Cellar", "Doors", "Garden"]


def test_an_entity_another_page_shows_moves_with_its_tile_settings() -> None:
    entry = _pages_entry()
    result = _save_page(entry, "page_3", {
        "name": "Garden", "position": 3, "entities": ["sensor.garden", "switch.entry"],
    })
    assert result["step_id"] == "dashboard_page_list"
    overrides = entry.options[CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES]
    assert overrides["switch.entry"] == {"secondary": "last_changed", "page": "Garden"}
    assert overrides["light.hall"] == {"page": "Doors"}
    assert entry.options[CONF_DASHBOARD_ENTITIES] == ["light.hall", "sensor.garden", "switch.entry"]


def test_an_error_the_opened_page_causes_is_shown_on_that_page() -> None:
    entry = _pages_entry()
    before = dict(entry.options)
    # The check names the later page; the form shows the one that was changed.
    refused = _save_page(entry, "page_2", {
        "name": "garden", "position": 2, "entities": ["switch.entry"],
    })
    assert refused["errors"] == {"page_2": "dashboard_page_name_duplicate"}
    assert entry.options == before


def test_a_saved_error_of_another_page_is_shown_above_the_form() -> None:
    entry = _pages_entry()
    entry.options[CONF_WEATHER_ENTITY_ID] = "sensor.not_weather"
    refused = _save_page(entry, "page_2", {
        "name": "Doors", "position": 2, "entities": ["switch.entry", "light.hall"],
    })
    assert refused["errors"] == {"base": "invalid_weather_entity"}


def test_the_status_page_is_saved_from_its_own_form() -> None:
    entry = _pages_entry()
    result = _save_page(entry, "page_1", {
        "enabled": False, "position": 1, "weather_entity_id": "weather.other",
    })
    assert result["step_id"] == "dashboard_page_list"
    assert entry.options[CONF_WEATHER_ENTITY_ID] == "weather.other"
    assert entry.options[CONF_DASHBOARD_STATUS_PAGE_ENABLED] is False
    assert _names(entry) == [DASHBOARD_STATUS_PAGE, "Doors", "Garden"]


def test_the_add_entry_returns_to_the_list_when_no_page_is_free() -> None:
    entry = _pages_entry()
    for number in range(4, 9):
        entity = f"light.room_{number}"
        entry.options[CONF_DASHBOARD_ENTITIES].append(entity)
        entry.options[CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES][entity] = {"page": f"Room {number}"}
        entry.options[CONF_DASHBOARD_PAGES].append({"name": f"Room {number}", "order": number})
    flow = _options_flow(entry)
    listed = _step(flow, "dashboard_page_list")
    assert "page_new" not in listed["menu_options"]
    assert _step(flow, "page_new")["step_id"] == "dashboard_page_list"


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


def _five_pages(order: list[str] | None = None, **options: Any) -> SimpleNamespace:
    names = order or [DASHBOARD_STATUS_PAGE, "Doors", "Garden", "Cellar", "Attic"]
    custom = ["Doors", "Garden", "Cellar", "Attic"]
    return _entry(**{
        CONF_DASHBOARD_ENTITIES: [f"light.{name.lower()}" for name in custom],
        CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: {
            f"light.{name.lower()}": {"page": name} for name in custom
        },
        CONF_DASHBOARD_PAGES: [
            {"name": name, "order": number} for number, name in enumerate(names, start=1)
        ],
        **options,
    })


def _shown(entry: SimpleNamespace) -> list[str]:
    """Return the pages in display order, a built-in page by its key."""

    pages = sorted(entry.options[CONF_DASHBOARD_PAGES], key=lambda page: page["order"])
    shown = [page["name"] for page in pages]
    energy = entry.options.get(CONF_ENERGY_PAGE) or {}
    if energy.get("enabled"):
        shown.insert(energy["position"] - 1, CONF_ENERGY_PAGE)
    return shown


def _energy(position: int, *, enabled: bool) -> dict[str, Any]:
    return {
        "enabled": enabled, "position": position, "view_balance": True, "view_consumers": True,
        "view_now": True, "view_power": True, "view_today": True,
    }


def test_a_built_in_page_switched_on_lands_at_the_position_it_asks_for() -> None:
    for position in (1, 3, 4, 6):
        entry = _five_pages()
        _save_page(entry, CONF_ENERGY_PAGE, _energy(position, enabled=True))
        expected = [DASHBOARD_STATUS_PAGE, "Doors", "Garden", "Cellar", "Attic"]
        expected.insert(min(position, 6) - 1, CONF_ENERGY_PAGE)
        assert _shown(entry) == expected, position


def test_a_page_switched_off_moves_nothing_with_its_position() -> None:
    order = ["Doors", "Garden", DASHBOARD_STATUS_PAGE, "Cellar", "Attic"]
    entry = _five_pages(order)
    _save_page(entry, CONF_ENERGY_PAGE, _energy(3, enabled=False))
    assert _shown(entry) == order
    assert entry.options[CONF_ENERGY_PAGE]["position"] == 3


def test_a_move_keeps_the_position_of_the_pages_switched_off() -> None:
    entry = _five_pages(**{CONF_ENERGY_PAGE: {"enabled": False, "position": 2}})
    _save_page(entry, "page_3", {"name": "Garden", "position": 1, "entities": ["light.garden"]})
    assert _shown(entry) == ["Garden", DASHBOARD_STATUS_PAGE, "Doors", "Cellar", "Attic"]
    assert entry.options[CONF_ENERGY_PAGE]["position"] == 2


def test_a_page_moves_past_a_built_in_page_stored_beyond_the_pages() -> None:
    entry = _five_pages(**{CONF_ENERGY_PAGE: {"enabled": True, "position": 10}})
    _save_page(entry, "page_5", {"name": "Attic", "position": 6, "entities": ["light.attic"]})
    assert _shown(entry) == [
        DASHBOARD_STATUS_PAGE, "Doors", "Garden", "Cellar", CONF_ENERGY_PAGE, "Attic",
    ]


def test_an_emptied_position_keeps_the_page_where_it_is() -> None:
    order = ["Doors", DASHBOARD_STATUS_PAGE, "Garden", "Cellar", "Attic"]
    entry = _five_pages(order, **{CONF_ENERGY_PAGE: {"enabled": True, "position": 1}})
    before = _shown(entry)
    _save_page(entry, "page_2", {"name": "Doors", "entities": ["light.doors"]})
    assert _shown(entry) == before
    _save_page(entry, "page_1", {"enabled": True, "weather_entity_id": ""})
    assert _shown(entry) == before


def test_every_page_form_sent_as_it_opens_saves_what_the_whole_form_would() -> None:
    from custom_components.bticino_c300x.config_flow_display_menu import (
        page_list,
        unchanged_pages_post,
    )

    def options() -> dict[str, Any]:
        return {CONF_ENERGY_PAGE: {"enabled": True, "position": 3}}

    whole = _five_pages(["Doors", DASHBOARD_STATUS_PAGE, "Garden", "Cellar", "Attic"], **options())
    flow = _options_flow(whole)
    _step(flow, "dashboard_page_list")
    keys = [key for key in page_list(flow._dashboard_options) if key != "page_new"]
    _step(flow, "dashboard_pages", unchanged_pages_post(flow._dashboard_options))
    assert len(keys) == 9
    for key in keys:
        entry = _five_pages(["Doors", DASHBOARD_STATUS_PAGE, "Garden", "Cellar", "Attic"], **options())
        single = _options_flow(entry)
        _step(single, "dashboard_page_list")
        _step(single, key)
        post = unchanged_pages_post(single._dashboard_options)[key]
        assert _step(single, "dashboard_pages", {key: post})["step_id"] == "dashboard_page_list"
        assert entry.options == whole.options, key


def test_an_energy_page_with_every_view_off_holds_no_place() -> None:
    hidden = {"enabled": True, "position": 2, "views": []}
    entry = _five_pages(**{CONF_ENERGY_PAGE: dict(hidden)})
    _save_page(entry, "page_2", {"name": "Doors", "position": 3, "entities": ["light.doors"]})
    assert [page["name"] for page in sorted(
        entry.options[CONF_DASHBOARD_PAGES], key=lambda page: page["order"]
    )] == [DASHBOARD_STATUS_PAGE, "Garden", "Doors", "Cellar", "Attic"]
    assert entry.options[CONF_ENERGY_PAGE]["position"] == 2


def test_an_emptied_position_keeps_a_page_switched_off_where_it_is() -> None:
    entry = _five_pages(**{CONF_ENERGY_PAGE: {"enabled": False, "position": 7}})
    values = _energy(7, enabled=False)
    del values["position"]
    _save_page(entry, CONF_ENERGY_PAGE, values)
    assert entry.options[CONF_ENERGY_PAGE]["position"] == 7


def test_a_position_is_read_as_the_whole_form_reads_it() -> None:
    from custom_components.bticino_c300x.config_flow_display_menu import _position

    assert [_position(value) for value in (2.5, "2", 0, 99, 3.0)] == [3, 2, 1, 12, 3]
    assert [_position(value) for value in (None, True, float("nan"), "x", [2])] == [None] * 5
