"""Page section titles and order follow positions without changing saved layout."""

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
    assert [key for key in keys if key in active] == active
    assert keys[-5:] == [f"page_{i}" for i in range(4, 9)]
    assert all(placeholders[f"page_{i}_position"] == "" for i in range(4, 9))
    for key, is_enabled in zip(SPECIAL_PAGE_ORDER, enabled, strict=True):
        if not is_enabled:
            assert placeholders[f"{key}_position"] == f" {saved[key]['position']}"
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
        "page_4", "page_5", "page_6", "page_8",
    ]
    placeholders = dashboard_pages_placeholders(saved, posted)
    assert placeholders["page_2_name"] == ": Renamed"
    for key, values in posted.items():
        assert placeholders[f"{key}_position"] == (f" {int(values['position'])}" if "position" in values else "")
    assert post_pages_like_home_assistant(schema) == posted


def test_hidden_logical_pages_and_inactive_energy_keep_configured_positions():
    saved, _ = dashboard_pages_input({}, form_input())
    saved["dashboard_status_page_enabled"] = False
    saved["dashboard_entities"] = []
    saved["energy_page"].update(position=11, views=[])
    placeholders = dashboard_pages_placeholders(saved)
    assert placeholders["page_1_position"] == " 1"
    assert placeholders["page_2_position"] == " 2"
    assert placeholders["energy_page_position"] == " 11"
    posted = post_pages_like_home_assistant(dashboard_pages_schema(saved))
    assert posted["page_1"]["enabled"] is False
    assert posted["energy_page"]["enabled"] is True
    assert posted["energy_page"]["position"] == 11
    assert not any(value for key, value in posted["energy_page"].items() if key.startswith("view_"))


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
