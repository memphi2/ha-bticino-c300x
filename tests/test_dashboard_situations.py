"""Selected situations are bounded, read-only and never clear unknown state."""

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from homeassistant.core import State
from test_dashboard_optional_pages import environment
from test_display_settings import post_pages_like_home_assistant

from custom_components.bticino_c300x import dashboard, runtime_manager
from custom_components.bticino_c300x.config_flow import _RECONFIGURED_OPTION_KEYS
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
    SITUATION_DOMAINS,
    normalize_situations_page,
)
from custom_components.bticino_c300x.dashboard_response import (
    DASHBOARD_RESPONSE_MAX_BYTES,
    display_json_size,
)
from custom_components.bticino_c300x.dashboard_situations import (
    situation_state,
    situations_dashboard_page,
    situations_entity_ids,
)
from custom_components.bticino_c300x.dashboard_updates import (
    dashboard_state_event_changes_display,
)

SETTINGS = {"enabled": True, "position": 1, "contacts": ["binary_sensor.window"],
            "garages": ["cover.garage"], "lights": ["light.kitchen"], "tasks": ["todo.household"]}


@pytest.mark.parametrize("kind,raw,device_class,expected", [
    ("contacts", "on", "window", "open"), ("contacts", "off", "door", "clear"),
    ("contacts", "on", "garage_door", "open"), ("contacts", "off", "opening", "clear"),
    ("contacts", "off", "motion", "unsupported"), ("contacts", "off", None, "unsupported"),
    ("contacts", "closed", "door", "unknown"),
    ("garages", "open", "garage", "open"), ("garages", "opening", "garage", "opening"),
    ("garages", "closing", "garage", "closing"), ("garages", "closed", "garage", "clear"),
    ("garages", "closed", "shutter", "unsupported"), ("garages", "stopped", "garage", "unknown"),
    ("lights", "on", None, "on"), ("lights", "off", None, "clear"), ("lights", "idle", None, "unknown"),
    ("tasks", "0", None, "clear"), ("tasks", "3", None, "pending"),
    ("tasks", "-1", None, "unknown"), ("tasks", "0.5", None, "unknown"),
    ("tasks", "NaN", None, "unknown"), ("tasks", "{{ 0 }}", None, "unknown"),
    ("tasks", "9" * 100, None, "unknown"),
])
def test_only_supported_inactive_states_clear(kind, raw, device_class, expected):
    entity = SITUATION_DOMAINS[kind] + ".one"
    status, count = situation_state(kind, State(entity, raw, {"device_class": device_class}))
    assert status == expected
    assert count == (int(raw) if expected in ("clear", "pending") and kind == "tasks" else None)


@pytest.mark.parametrize("kind", SITUATION_DOMAINS)
@pytest.mark.parametrize("raw", [None, "unknown", "unavailable"])
def test_absent_unknown_unavailable_never_clear(kind, raw):
    state = State(SITUATION_DOMAINS[kind] + ".one", raw) if raw else None
    assert situation_state(kind, state) == (raw or "unavailable", None)


def test_disabled_performs_no_reads_and_no_services():
    hass, entry, _ = environment({"situations_page": {**SETTINGS, "enabled": False}})
    hass.states.get = Mock(side_effect=AssertionError("disabled page read state"))
    assert situations_dashboard_page(hass, entry) is None
    assert situations_entity_ids(entry) == ()
    hass.services.async_call.assert_not_called()


def test_projection_reads_only_selected_entities_and_retains_unknown():
    states = {"binary_sensor.window": State("binary_sensor.window", "off", {"device_class": "window"}),
              "cover.garage": State("cover.garage", "closing", {"device_class": "garage"}),
              "light.kitchen": State("light.kitchen", "unknown"),
              "todo.household": State("todo.household", "3", {"friendly_name": "<b>Tasks</b>"})}
    hass, entry, _ = environment({"situations_page": SETTINGS}, states)
    hass.states.get = Mock(side_effect=states.get)
    page = situations_dashboard_page(hass, entry)["situations"]
    assert [check["state_label"] for check in page["checks"]] == ["Closing", "Unknown", "Pending: 3"]
    assert [check["color"] for check in page["checks"]] == ["#ff6b6b", "#ffd166", "#ff6b6b"]
    assert [call.args[0] for call in hass.states.get.call_args_list] == list(situations_entity_ids(entry))
    assert "actions" not in page and "alarm" not in page
    hass.services.async_call.assert_not_called()


@pytest.mark.parametrize("language", ["en", "de", "fr", "it"])
def test_empty_and_confirmed_clear_have_distinct_messages(language):
    hass, entry, _ = environment({"situations_page": {"enabled": True}})
    empty = situations_dashboard_page(hass, entry, language)["situations"]
    entry.options["situations_page"]["lights"] = ["light.one"]
    hass.states.get = lambda _: State("light.one", "off")
    clear = situations_dashboard_page(hass, entry, language)["situations"]
    assert not empty["checks"] and not clear["checks"]
    assert empty["empty_text"] != clear["empty_text"]


@pytest.mark.parametrize("enabled", [False, True])
def test_configuration_roundtrip_preserves_visibility_order_and_selections(enabled):
    settings = {**SETTINGS, "enabled": enabled}
    entry = SimpleNamespace(data={"device_ui_enabled": True, "situations_page": settings}, options={})
    defaults = current_feature_options(entry)
    saved, errors = dashboard_pages_input(defaults, post_pages_like_home_assistant(dashboard_pages_schema(defaults)))
    assert not errors and saved["situations_page"] == settings
    features, errors = _feature_input(feature_input_defaults({}, saved))
    assert not errors and features["situations_page"] == settings
    assert "situations_page" in _RECONFIGURED_OPTION_KEYS
    assert not normalize_situations_page(None)["enabled"]


@pytest.mark.parametrize("field", SITUATION_DOMAINS)
@pytest.mark.parametrize("values", [["lock.front"], ["{{ states }}"], "light.kitchen", ["light.kitchen"] * 25])
def test_invalid_form_keeps_original_and_retry_input(field, values):
    original = {"situations_page": SETTINGS}
    posted = {"situations_page": {"enabled": True, field: values}}
    saved, errors = dashboard_pages_input(original, posted)
    assert saved == original and errors == {"situations_page": "invalid_dashboard_entities"}
    schema = dashboard_pages_schema(original, posted)
    section = next(value for key, value in schema.schema.items() if str(key) == "situations_page")
    marker = next(key for key in section.schema.schema if str(key) == field)
    assert marker.description["suggested_value"] == values


def test_total_selection_budget_and_unicode_payload():
    values = {field: [f"{domain}.item{i}" for i in range(24)] for field, domain in SITUATION_DOMAINS.items()}
    saved, errors = dashboard_pages_input({}, {"situations_page": {"enabled": True, **values}})
    assert errors and not saved
    normalized = normalize_situations_page({"enabled": True, **values})
    assert sum(len(normalized[field]) for field in SITUATION_DOMAINS) == 24
    hass, entry, _ = environment({"situations_page": normalized})
    hass.states.get = lambda entity: State(entity, "unavailable", {"friendly_name": "\U0001f3e0" * 300})
    assert display_json_size(situations_dashboard_page(hass, entry)) < DASHBOARD_RESPONSE_MAX_BYTES // 2


def test_form_omitted_section_retained_and_cleared_pickers_removed():
    original = {"situations_page": SETTINGS}
    assert dashboard_pages_input(original, {})[0]["situations_page"] == SETTINGS
    result, errors = dashboard_pages_input(original, {"situations_page": {"enabled": False}})
    assert not errors and result["situations_page"] == {"enabled": False, "position": 1, **dict.fromkeys(SITUATION_DOMAINS, [])}


def test_situations_can_be_only_page_and_ordered_without_replacing_existing_pages():
    hass, entry, _ = environment({"device_ui_enabled": True, "dashboard_status_page_enabled": False,
                                 "situations_page": SETTINGS})
    assert asyncio.run(dashboard.async_status(hass, entry))["dashboard_available"]
    payload = asyncio.run(dashboard.async_dashboard_payload(hass, entry))
    assert [page["title"] for page in payload["data"]["pages"]] == ["Situations"]
    assert "situations" in payload["data"]["pages"][0]
    entry.options.update(dashboard_status_page_enabled=True, agenda_page={"enabled": True, "position": 2},
                         leave_home_page={"enabled": True, "position": 3})
    payload = asyncio.run(dashboard.async_dashboard_payload(hass, entry))
    assert [page["title"] for page in payload["data"]["pages"]] == ["Situations", "Agenda", "Leave home", "C300X"]
    hass.services.async_call.assert_not_called()


@pytest.mark.parametrize("enabled", [False, True])
def test_subscription_is_selected_and_display_only(monkeypatch, enabled):
    import homeassistant.helpers.dispatcher as dispatcher

    hass, entry, _ = environment({"device_ui_enabled": True, "dashboard_status_page_enabled": False,
                                 "situations_page": {**SETTINGS, "enabled": enabled}})
    listeners = []
    unsubscribe = Mock()
    hass.bus = SimpleNamespace(async_listen=lambda _, cb: (listeners.append(cb), unsubscribe)[1])
    monkeypatch.setattr(dispatcher, "async_dispatcher_connect", lambda *_: unsubscribe)
    notify = Mock()
    monkeypatch.setattr(runtime_manager, "_async_schedule_display_bridge_notify", notify)
    stop = runtime_manager._async_track_display_bridge_updates(hass, entry)
    for entity in ("todo.household", "todo.unselected"):
        listeners[0](SimpleNamespace(data={"entity_id": entity, "old_state": State(entity, "1"), "new_state": State(entity, "0")}))
    assert notify.call_count == int(enabled)
    if enabled:
        assert dashboard_state_event_changes_display(hass, entry, {"entity_id": "cover.garage", "old_state": State("cover.garage", "closed", {"device_class": "garage"}), "new_state": State("cover.garage", "closed", {"device_class": "shutter"})})
    stop()
    assert unsubscribe.call_count == 2
    hass.services.async_call.assert_not_called()


def test_page_data_holds_only_what_the_display_reads():
    """Each row had an entity id and a status, and the page three counts, that no display file reads."""

    root = Path(__file__).resolve().parents[1] / "device_qml"
    rows = set(re.findall(r"modelData\.(\w+)", (root / "C300XChecks.qml").read_text(encoding="utf-8")))
    page_fields = set(re.findall(r"root\.situations\.(\w+)", (root / "C300XSituations.qml").read_text(encoding="utf-8")))
    assert rows == {"name", "state_label", "color"} and page_fields == {"checks", "empty_text"}
    states = {"cover.garage": State("cover.garage", "open", {"device_class": "garage"}),
              "light.kitchen": State("light.kitchen", "unavailable")}
    hass, entry, _ = environment({"situations_page": SETTINGS}, states)
    page = situations_dashboard_page(hass, entry)["situations"]
    assert len(page["checks"]) >= 2
    assert set(page) == page_fields
    assert all(set(check) == rows for check in page["checks"])
