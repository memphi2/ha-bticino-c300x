"""All logical slots share stable configuration and display ordering."""

import asyncio
from itertools import permutations, product
from types import SimpleNamespace

import pytest
from homeassistant.core import State
from test_display_settings import post_pages_like_home_assistant

from custom_components.bticino_c300x import dashboard
from custom_components.bticino_c300x.config_flow_dashboard_pages import (
    dashboard_pages_input,
    dashboard_pages_schema,
)
from custom_components.bticino_c300x.dashboard_energy import normalize_energy_page
from custom_components.bticino_c300x.dashboard_optional_config import (
    optional_page_values,
)
from custom_components.bticino_c300x.dashboard_page_order import (
    PAGE_POSITION_MAX,
    SPECIAL_PAGE_ORDER,
    page_layout_slots,
    page_position,
    submitted_special_positions,
)


def special_settings(positions=(2, 10, 11), enabled=(True, True, True)):
    return {key: {"position": position, "enabled": active, **({"views": ["now"]} if key == "energy_page" else {})}
            for key, position, active in zip(SPECIAL_PAGE_ORDER[:len(positions)], positions, enabled, strict=True)}


def form_input(regular_positions=(1, 3, 5), positions=(2, 4, 6), enabled=(True, True, True)):
    return {**special_settings(positions, enabled), **{
        f"page_{index}": {"name": "C300X" if index == 1 else f"Room {index}",
                          "position": position, "entities": [f"sensor.room_{index}"]}
        for index, position in enumerate(regular_positions, 1)
    }}


def slots_for_saved(saved):
    return page_layout_slots([page["name"] for page in saved["dashboard_pages"]], {
        "energy_page": normalize_energy_page(saved.get("energy_page")), **optional_page_values(saved),
    })


def test_all_position_combinations_replay_normalized_form_order():
    regular = [f"Room {index}" for index in range(1, 9)]
    for positions in product(range(1, PAGE_POSITION_MAX + 1), repeat=len(SPECIAL_PAGE_ORDER)):
        special = special_settings(positions, (True,) * len(SPECIAL_PAGE_ORDER))
        saved = submitted_special_positions(list(range(1, 9)), special, set(SPECIAL_PAGE_ORDER))
        expected = [(index, len(SPECIAL_PAGE_ORDER), ("regular", name)) for index, name in enumerate(regular, 1)]
        expected += [(position, index, ("special", key)) for index, (key, position) in enumerate(zip(SPECIAL_PAGE_ORDER, positions, strict=True))]
        assert page_layout_slots(regular, saved) == [value for _, _, value in sorted(expected)]


@pytest.mark.parametrize("positions", list(permutations((1, 3, 5))))
@pytest.mark.parametrize("enabled", list(product((False, True), repeat=3)))
def test_form_save_reopen_preserves_mixed_order_and_disabled_positions(positions, enabled):
    saved, errors = dashboard_pages_input({}, form_input((2, 4, 6), positions, enabled))
    assert not errors
    before = slots_for_saved(saved)
    for _ in range(2):
        reopened, errors = dashboard_pages_input(saved, post_pages_like_home_assistant(dashboard_pages_schema(saved)))
        assert not errors
        assert slots_for_saved(reopened) == before
        assert reopened["dashboard_pages"] == saved["dashboard_pages"]
        for key in SPECIAL_PAGE_ORDER:
            assert reopened[key] == saved[key]
        saved = reopened
    for key, active, position in zip(SPECIAL_PAGE_ORDER[:len(positions)], enabled, positions, strict=True):
        if not active:
            assert saved[key]["position"] == position


def test_all_sections_offer_all_positions_and_optional_defaults_append():
    schema = dashboard_pages_schema({})
    assert PAGE_POSITION_MAX == 12
    for marker, section in schema.schema.items():
        selector = next(value for field, value in section.schema.schema.items() if str(field) == "position")
        assert selector.config["min"] == 1 and selector.config["max"] == 12 and selector.config["step"] == 1
        if str(marker) in SPECIAL_PAGE_ORDER:
            position = next(field for field in section.schema.schema if str(field) == "position")
            assert position.description["suggested_value"] == {"agenda_page": 10, "leave_home_page": 11, "energy_page": 2, "situations_page": 12}[str(marker)]


def test_equal_positions_are_energy_agenda_leave_then_regular_section_order():
    saved, errors = dashboard_pages_input({}, form_input((1, 1, 1), (1, 1, 1, 1), (True,) * 4))
    assert not errors
    assert slots_for_saved(saved) == [("special", key) for key in SPECIAL_PAGE_ORDER] + [
        ("regular", name) for name in ("C300X", "Room 2", "Room 3")
    ]
    assert [saved[key]["position"] for key in SPECIAL_PAGE_ORDER] == [1, 2, 3, 4]


def test_disabled_optional_page_preserves_position_and_selections_after_roundtrip():
    saved, _ = dashboard_pages_input({}, form_input())
    saved["agenda_page"]["calendars"] = ["calendar.work"]
    saved["leave_home_page"].update(contacts=["binary_sensor.door"], lights=["light.room"], actions=["leave"], show_alarm=True)
    before = optional_page_values(saved)
    posted = post_pages_like_home_assistant(dashboard_pages_schema(saved), {
        "agenda_page": {"enabled": False}, "leave_home_page": {"enabled": False},
    })
    result, errors = dashboard_pages_input(saved, posted)
    assert not errors
    for key, settings in before.items():
        assert result[key] == {**settings, "enabled": False}


def test_omitted_optional_sections_keep_saved_positions():
    saved, _ = dashboard_pages_input({}, form_input())
    result, errors = dashboard_pages_input(saved, {"page_1": {"position": 11}})
    assert not errors
    for key in SPECIAL_PAGE_ORDER:
        assert result[key] == saved[key]


@pytest.mark.parametrize("value,expected", [(None, 10), ("bad", 10), (float("nan"), 10), (float("inf"), 10), (-8, 1), (2.5, 3), (99, 12)])
def test_position_normalization_matches_regular_form(value, expected):
    assert page_position(value, 10) == expected
    assert optional_page_values({"agenda_page": {"position": value}})["agenda_page"]["position"] == expected


@pytest.mark.parametrize("regular_positions,positions,expected", [
    ((2, 4, 6), (3, 1, 5), ["Agenda", "C300X", "Energy", "Room 2", "Leave home", "Room 3"]),
    ((1, 2, 3), (2, 10, 11), ["C300X", "Energy", "Room 2", "Room 3", "Agenda", "Leave home"]),
    ((11, 4, 6), (7, 5, 1), ["Leave home", "Room 2", "Agenda", "Room 3", "Energy", "C300X"]),
    ((1, 1, 1), (1, 1, 1), ["Energy", "Agenda", "Leave home", "C300X", "Room 2", "Room 3"]),
])
def test_actual_payload_interleaves_every_page_type(monkeypatch, regular_positions, positions, expected):
    async def energy(*_args):
        return {"title": "Energy", "energy": {"views": [{"id": "now", "label": "Now"}]}}

    monkeypatch.setattr(dashboard, "async_energy_dashboard_page", energy)
    saved, errors = dashboard_pages_input({}, form_input(regular_positions, positions))
    assert not errors
    states = {f"sensor.room_{i}": State(f"sensor.room_{i}", "20") for i in range(1, 4)}
    hass = SimpleNamespace(data={}, config=SimpleNamespace(language="en"), states=SimpleNamespace(get=states.get))
    entry = SimpleNamespace(entry_id="one", title="Door", data={}, options={"device_ui_enabled": True, **saved})
    payload = asyncio.run(dashboard.async_dashboard_payload(hass, entry))
    assert [page["title"] for page in payload["data"]["pages"]] == expected


def test_hidden_status_and_empty_configured_pages_keep_their_logical_slots(monkeypatch):
    async def energy(*_args):
        return {"title": "Energy", "energy": {"views": [{"id": "now"}]}}

    monkeypatch.setattr(dashboard, "async_energy_dashboard_page", energy)
    saved, _ = dashboard_pages_input({}, form_input((1, 3, 5), (2, 4, 6)))
    saved["dashboard_status_page_enabled"] = False
    saved["dashboard_entities"] = ["sensor.room_3"]
    hass = SimpleNamespace(data={}, config=SimpleNamespace(language="en"), states=SimpleNamespace(get=lambda entity: State(entity, "20")))
    entry = SimpleNamespace(entry_id="one", title="Door", data={}, options={"device_ui_enabled": True, **saved})
    payload = asyncio.run(dashboard.async_dashboard_payload(hass, entry))
    assert [page["title"] for page in payload["data"]["pages"]] == ["Energy", "Agenda", "Room 3", "Leave home"]
