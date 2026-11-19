"""The pages form follows the display order without changing what is saved."""

import json
from copy import deepcopy
from itertools import permutations, product
from pathlib import Path

import pytest
from test_dashboard_page_order import form_input, slots_for_saved
from test_display_settings import post_pages_like_home_assistant

from custom_components.bticino_c300x.config_flow_dashboard_pages import (
    dashboard_page_layout,
    dashboard_pages_input,
    dashboard_pages_placeholders,
    dashboard_pages_schema,
)
from custom_components.bticino_c300x.dashboard_page_order import SPECIAL_PAGE_ORDER


@pytest.mark.parametrize("positions", list(permutations((1, 3, 5))))
@pytest.mark.parametrize("enabled", list(product((False, True), repeat=3)))
def test_saved_headings_and_section_order_match_resolved_slots(positions, enabled):
    saved, errors = dashboard_pages_input({}, form_input((6, 2, 4), positions, enabled))
    assert not errors
    original = deepcopy(saved)
    schema = dashboard_pages_schema(saved)
    placeholders = dashboard_pages_placeholders(saved)
    keys = [str(key) for key in schema.schema]
    regular = {page["name"]: f"page_{i}" for i, page in enumerate(dashboard_page_layout(saved), 1)}
    active = []
    for position, (kind, name) in enumerate(slots_for_saved(saved), 1):
        key = regular[name] if kind == "regular" else name
        active.append(key)
        assert placeholders[f"{key}_position"] == f" {position}"
    # Shown pages in display order, then the built-in pages that are off, then the free sections.
    off = [key for key in SPECIAL_PAGE_ORDER if key not in active]
    assert keys == [*active, *off, *[f"page_{i}" for i in range(4, 9)]]
    assert "situations_page" in off
    assert [key for key, is_enabled in zip(SPECIAL_PAGE_ORDER[:3], enabled, strict=True) if not is_enabled] == off[:-1]
    assert all(placeholders[f"{key}_position"] == "" for key in off)
    assert all(placeholders[f"page_{i}_position"] == "" for i in range(4, 9))
    assert all(placeholders[f"page_{i}_name"] == " +" for i in range(4, 9))
    reopened, errors = dashboard_pages_input(saved, post_pages_like_home_assistant(schema))
    assert not errors
    assert reopened == saved == original


def test_retry_orders_requested_positions_and_keeps_section_identity_and_fields():
    saved, _ = dashboard_pages_input({}, form_input())
    posted = post_pages_like_home_assistant(dashboard_pages_schema(saved), {
        "page_1": {"position": 8, "enabled": False},
        "page_2": {"position": 7, "name": "Renamed"},
        "page_3": {"position": 2, "entities": ["light.duplicate"]},
        "page_7": {"position": 4, "entities": ["light.duplicate"]},
        "energy_page": {"position": 6},
        "agenda_page": {"position": 1},
        "leave_home_page": {"position": 3},
    })
    unchanged, errors = dashboard_pages_input(saved, posted)
    assert errors and unchanged == saved
    schema = dashboard_pages_schema(saved, posted)
    assert [str(key) for key in schema.schema] == [
        "agenda_page", "page_3", "leave_home_page", "page_7", "energy_page", "page_2", "page_1",
        "situations_page", "page_4", "page_5", "page_6", "page_8",
    ]
    placeholders = dashboard_pages_placeholders(saved, posted)
    assert placeholders["page_2_name"] == ": Renamed"
    assert posted["situations_page"]["enabled"] is False and placeholders["situations_page_position"] == ""
    for key, values in posted.items():
        if key != "situations_page":
            assert placeholders[f"{key}_position"] == (f" {int(values['position'])}" if "position" in values else "")
    assert post_pages_like_home_assistant(schema) == posted


def test_default_form_lists_the_off_built_in_pages_above_the_seven_free_sections():
    schema = dashboard_pages_schema({})
    keys = [str(key) for key in schema.schema]
    assert keys == ["page_1", *SPECIAL_PAGE_ORDER, *[f"page_{i}" for i in range(2, 9)]]
    placeholders = dashboard_pages_placeholders({})
    assert placeholders["page_1_position"] == " 1"
    posted = post_pages_like_home_assistant(schema)
    for key, position in zip(SPECIAL_PAGE_ORDER, (2, 10, 11, 12), strict=True):
        # No number in the title while the page is off; its position stays in its section.
        assert placeholders[f"{key}_position"] == ""
        assert posted[key]["enabled"] is False
        assert posted[key]["position"] == position


def test_hidden_logical_pages_keep_their_number_and_inactive_energy_its_position():
    saved, _ = dashboard_pages_input({}, form_input())
    saved["dashboard_status_page_enabled"] = False
    saved["dashboard_entities"] = []
    saved["energy_page"].update(position=11, views=[])
    placeholders = dashboard_pages_placeholders(saved)
    assert placeholders["page_1_position"] == " 1"
    assert placeholders["page_2_position"] == " 2"
    # Switched on without a view, the energy page is not shown: no number in the title.
    assert placeholders["energy_page_position"] == ""
    posted = post_pages_like_home_assistant(dashboard_pages_schema(saved))
    assert posted["page_1"]["enabled"] is False
    assert posted["energy_page"]["enabled"] is True
    assert posted["energy_page"]["position"] == 11
    assert not any(value for key, value in posted["energy_page"].items() if key.startswith("view_"))


@pytest.mark.parametrize("key", ["agenda_page", "leave_home_page"])
@pytest.mark.parametrize("omit_enabled", [False, True])
def test_disabled_optional_retry_with_cleared_position_matches_saved_fallback(key, omit_enabled):
    saved, _ = dashboard_pages_input({}, form_input())
    saved[key].update(enabled=False, position=3)
    if key == "agenda_page":
        saved[key]["calendars"] = ["calendar.work"]
    else:
        saved[key].update(contacts=["binary_sensor.door"], lights=["light.room"], show_alarm=True)
    posted = post_pages_like_home_assistant(dashboard_pages_schema(saved), {
        key: {"position": None},
        "page_2": {"name": None},
    })
    if omit_enabled:
        posted[key].pop("enabled")
    unchanged, errors = dashboard_pages_input(saved, posted)
    assert unchanged == saved and errors == {"page_2": "dashboard_page_name_missing"}

    placeholders = dashboard_pages_placeholders(saved, posted)
    assert placeholders[f"{key}_position"] == ""
    retry = dashboard_pages_schema(saved, posted)
    keys = [str(marker) for marker in retry.schema]
    assert keys.index("page_3") < keys.index(key) < keys.index("page_4")
    corrected = post_pages_like_home_assistant(retry, {"page_2": {"name": "Room 2"}})
    assert "position" not in corrected[key]
    result, errors = dashboard_pages_input(saved, corrected)
    assert not errors
    assert result[key] == saved[key]
    assert result[key]["position"] == 3


@pytest.mark.parametrize("name", ["strings.json", *[f"translations/{lang}.json" for lang in ("en", "de", "fr", "it")]])
def test_every_page_title_renders_its_position_in_all_flows_and_languages(name):
    saved, _ = dashboard_pages_input({}, form_input((6, 2, 4), (1, 3, 5)))
    placeholders = dashboard_pages_placeholders(saved)
    catalog = json.loads((Path(__file__).resolve().parents[1] / "custom_components/bticino_c300x" / name).read_text())
    for flow, step in [("config", "user_dashboard_pages"), ("config", "reconfigure_dashboard_pages"), ("options", "dashboard_pages")]:
        for key, section in catalog[flow]["step"][step]["sections"].items():
            assert "{" + key + "_position}" in section["name"]
            title = section["name"].format_map(placeholders)
            assert "{" not in title and "}" not in title
            assert placeholders[f"{key}_position"] in title
            if key.startswith("page_") and int(key[5:]) >= 4:
                assert not any(char.isdigit() for char in title)


@pytest.mark.parametrize("name,built_in,custom", [
    ("strings.json", "five built-in pages", "seven custom pages"),
    ("translations/en.json", "five built-in pages", "seven custom pages"),
    ("translations/de.json", "fünf vordefinierte Seiten", "sieben eigene Seiten"),
    ("translations/fr.json", "cinq pages", "sept pages"),
    ("translations/it.json", "cinque pagine", "sette pagine"),
])
def test_page_descriptions_distinguish_built_in_and_custom_pages(name, built_in, custom):
    catalog = json.loads((Path(__file__).resolve().parents[1] / "custom_components/bticino_c300x" / name).read_text())
    descriptions = [catalog[flow]["step"][step]["description"] for flow, step in (
        ("config", "user_dashboard_pages"), ("config", "reconfigure_dashboard_pages"),
        ("options", "dashboard_pages"),
    )]
    assert len(set(descriptions)) == 1
    assert built_in in descriptions[0] and custom in descriptions[0]
    keys = [str(marker) for marker in dashboard_pages_schema({}).schema]
    assert keys[:5] == ["page_1", *SPECIAL_PAGE_ORDER]
    assert len(keys[5:]) == 7
