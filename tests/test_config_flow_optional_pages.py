"""Independent optional-page selections survive each configuration boundary."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_display_settings import post_pages_like_home_assistant

from custom_components.bticino_c300x.config_flow import _RECONFIGURED_OPTION_KEYS
from custom_components.bticino_c300x.config_flow_dashboard import (
    dashboard_input_defaults,
)
from custom_components.bticino_c300x.config_flow_dashboard_pages import (
    dashboard_pages_input,
    dashboard_pages_schema,
)
from custom_components.bticino_c300x.config_flow_features import (
    current_feature_options,
    feature_input_defaults,
)
from custom_components.bticino_c300x.config_flow_input import _feature_input
from custom_components.bticino_c300x.dashboard_optional_config import (
    normalize_agenda_page,
    normalize_leave_home_page,
    optional_page_values,
)

SETTINGS = {
    "device_ui_enabled": True,
    "agenda_page": {"enabled": True, "calendars": ["calendar.work", "calendar.family"]},
    "leave_home_page": {"enabled": True, "contacts": ["binary_sensor.front_door"], "lights": ["light.room"],
                        "actions": ["leave"], "show_alarm": True},
    "actions": {"leave": {"domain": "script", "service": "turn_on", "target": {"entity_id": "script.leave"}}},
}


@pytest.mark.parametrize("agenda_enabled,leave_enabled", [(False, False), (False, True), (True, False), (True, True)])
def test_independent_pages_round_trip_through_form_and_feature_persistence(agenda_enabled, leave_enabled):
    settings = {**SETTINGS, "agenda_page": {**SETTINGS["agenda_page"], "enabled": agenda_enabled},
                "leave_home_page": {**SETTINGS["leave_home_page"], "enabled": leave_enabled}}
    entry = SimpleNamespace(data=settings, options={})
    defaults = current_feature_options(entry)
    shown = dashboard_input_defaults({}, defaults)
    saved, errors = dashboard_pages_input(shown, post_pages_like_home_assistant(dashboard_pages_schema(shown)))
    assert not errors
    expected = optional_page_values(settings)
    if agenda_enabled:
        expected["agenda_page"]["position"] = 2
    if leave_enabled:
        expected["leave_home_page"]["position"] = 3 if agenda_enabled else 2
    assert optional_page_values(saved) == expected
    feature, errors = _feature_input(feature_input_defaults({}, {**defaults, **saved}))
    assert not errors
    assert optional_page_values(feature) == expected
    reopened = current_feature_options(SimpleNamespace(data={}, options=feature))
    assert optional_page_values(reopened) == expected
    assert {"agenda_page", "leave_home_page"} <= _RECONFIGURED_OPTION_KEYS


def test_omitted_sections_preserve_settings_but_emptied_pickers_clear():
    saved, errors = dashboard_pages_input(SETTINGS, {})
    assert not errors
    assert optional_page_values(saved) == optional_page_values(SETTINGS)
    saved, errors = dashboard_pages_input(SETTINGS, {"agenda_page": {"enabled": True}})
    assert not errors
    assert saved["agenda_page"] == {"enabled": True, "position": 2, "calendars": []}
    assert saved["leave_home_page"] == normalize_leave_home_page(SETTINGS["leave_home_page"])
    saved, errors = dashboard_pages_input(SETTINGS, {"leave_home_page": {"enabled": True, "show_alarm": False}})
    assert not errors
    assert saved["leave_home_page"] == {"enabled": True, "position": 3, "contacts": [], "lights": [], "actions": [], "show_alarm": False}
    assert saved["agenda_page"] == normalize_agenda_page(SETTINGS["agenda_page"])


@pytest.mark.parametrize("key,field,prefix,count", [
    ("agenda_page", "calendars", "calendar.", 9),
    ("leave_home_page", "contacts", "binary_sensor.", 25),
    ("leave_home_page", "lights", "light.", 25),
    ("leave_home_page", "actions", "", 9),
])
def test_over_limit_form_is_rejected_without_losing_selections(key, field, prefix, count):
    posted = {key: {"enabled": True, field: [f"{prefix}item{i}" for i in range(count)]}}
    saved, errors = dashboard_pages_input(SETTINGS, posted)
    assert key in errors and saved == SETTINGS
    retry = dashboard_pages_schema(SETTINGS, posted)
    section = next(value for marker, value in retry.schema.items() if str(marker) == key)
    marker = next(marker for marker in section.schema.schema if str(marker) == field)
    assert marker.description["suggested_value"] == posted[key][field]


@pytest.mark.parametrize("key,field,value", [
    ("agenda_page", "calendars", "calendar.one"), ("agenda_page", "calendars", ["light.one"]),
    ("leave_home_page", "lights", ["script.leave"]), ("leave_home_page", "contacts", ["light.one"]),
    ("leave_home_page", "actions", ["../bad"]),
])
def test_invalid_domain_or_id_does_not_expand_scope(key, field, value):
    saved, errors = dashboard_pages_input(SETTINGS, {key: {field: value}})
    assert saved == SETTINGS and key in errors


def test_stored_values_are_safe_and_bounded_even_without_a_valid_form():
    assert normalize_agenda_page(None) == {"enabled": False, "position": 10, "calendars": []}
    assert normalize_leave_home_page("bad") == {"enabled": False, "position": 11, "contacts": [], "lights": [], "actions": [], "show_alarm": False}
    assert normalize_agenda_page({"enabled": "true", "calendars": ["calendar.a", "light.a", "calendar.a", None]}) == {"enabled": False, "position": 10, "calendars": ["calendar.a"]}
    assert len(normalize_agenda_page({"calendars": [f"calendar.c{i}" for i in range(99)]})["calendars"]) == 8


def test_retry_keeps_false_flags_and_cleared_fields():
    posted = {"agenda_page": {"enabled": False}, "leave_home_page": {"enabled": False, "show_alarm": False}}
    retry = post_pages_like_home_assistant(dashboard_pages_schema(SETTINGS, posted))
    saved, errors = dashboard_pages_input(SETTINGS, retry)
    assert not errors
    assert saved["agenda_page"] == {"enabled": False, "position": 10, "calendars": []}
    assert saved["leave_home_page"] == normalize_leave_home_page({})


def test_invalid_saved_action_map_still_allows_clearing_optional_selections():
    settings = {**SETTINGS, "actions_json": "not json"}
    form = dashboard_pages_schema(settings)
    assert form


@pytest.mark.parametrize("name", ["strings.json", "translations/en.json", "translations/de.json", "translations/fr.json", "translations/it.json"])
def test_all_three_flows_translate_optional_sections(name):
    path = Path(__file__).resolve().parents[1] / "custom_components/bticino_c300x" / name
    catalog = json.loads(path.read_text())
    for flow, step in [("config", "user_dashboard_pages"), ("config", "reconfigure_dashboard_pages"), ("options", "dashboard_pages")]:
        for key, fields in [("agenda_page", {"enabled", "position", "calendars"}), ("leave_home_page", {"enabled", "position", "contacts", "lights", "actions", "show_alarm"})]:
            section = catalog[flow]["step"][step]["sections"][key]
            assert set(section["data"]) == set(section["data_description"]) == fields
            assert section["name"] and section["description"]
