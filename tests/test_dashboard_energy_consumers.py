"""Configured HA device power only: exact watts, stable Top10 and no inference."""

import json
import sys
from types import SimpleNamespace

import pytest

from custom_components.bticino_c300x.dashboard_energy import (
    ENERGY_DAY_VIEWS,
    ENERGY_LIVE_VIEWS,
    ENERGY_VIEWS,
    EnergyDay,
    EnergySources,
    energy_page,
    energy_sources,
    energy_views,
)
from custom_components.bticino_c300x.dashboard_energy_consumers import (
    EnergyConsumer,
    consumer_color,
    consumer_power_watts,
    consumer_sources,
    consumers_payload,
)
from custom_components.bticino_c300x.dashboard_labels import ENERGY_LABELS_BY_LANGUAGE


def state(value, unit="W", name="Measured device"):
    return SimpleNamespace(state=value, attributes={"unit_of_measurement": unit, "friendly_name": name})


def test_actual_installed_ha_schema_has_direct_power_mapping_not_assigned_color():
    from homeassistant.components.energy.data import (
        DEVICE_CONSUMPTION_SCHEMA,
        DeviceConsumption,
    )

    raw = {"stat_consumption": "sensor.energy", "stat_rate": "sensor.actual_watts", "name": "Desk",
           "included_in_stat": "sensor.parent_energy"}
    assert DEVICE_CONSUMPTION_SCHEMA(raw) == raw
    assert "stat_rate" in DeviceConsumption.__optional_keys__
    assert "color" not in DeviceConsumption.__annotations__
    parsed = consumer_sources({"device_consumption": [raw]})
    assert parsed == (EnergyConsumer("sensor.actual_watts", "Desk"),)


def test_only_configured_electric_sensor_stat_rates_are_considered_and_deduplicated():
    preferences = {"device_consumption": [
        {"stat_consumption": "sensor.energy_only"},
        {"stat_consumption": "sensor.energy", "stat_rate": "sensor.real_power", "name": " First "},
        {"stat_consumption": "sensor.energy2", "stat_rate": "sensor.real_power", "name": "Duplicate"},
        {"stat_consumption": "external:meter", "stat_rate": "external:power"},
        {"stat_rate": "switch.power"}, {"stat_rate": "sensor.bad-name"}, {"stat_rate": None}, None,
        {"stat_consumption": "sensor.child_energy", "stat_rate": "sensor.child_power", "included_in_stat": "sensor.energy"},
    ], "device_consumption_water": [{"stat_rate": "sensor.water_rate"}],
        "energy_sources": [{"type": "solar", "stat_rate": "sensor.solar"}]}
    assert consumer_sources(preferences) == (EnergyConsumer("sensor.real_power", "First"), EnergyConsumer("sensor.child_power"))
    assert energy_sources(preferences).consumers == ()
    sources = energy_sources(preferences, include_consumers=True)
    assert sources.any
    assert sources.power_entities == {"sensor.solar"}
    assert sources.energy_stats == sources.cost_stats == set()
    assert sources.live_power_entities(["consumers"]) == {"sensor.real_power", "sensor.child_power"}
    assert sources.live_power_entities(["now"]) == {"sensor.solar"}
    assert sources.live_power_entities(["today", "power"]) == set()


@pytest.mark.parametrize("raw", [None, [], "bad", {}, {"device_consumption": None}, {"device_consumption": "bad"}])
def test_invalid_preferences_never_invent_sources(raw):
    assert consumer_sources(raw) == ()


@pytest.mark.parametrize(("value", "unit", "expected"), [
    ("0", "W", 0), ("-0", "W", 0), ("1.234", "kW", 1234), ("250", "mW", .25),
    ("1", "MW", 1e6), ("1", "GW", 1e9), ("3.1", "W", 3.1),
    ("unavailable", "W", None), ("unknown", "W", None), (None, "W", None), (True, "W", None),
    ("nan", "W", None), ("inf", "W", None), ("-1", "W", None), ("-1e-100", "W", None),
    ("1", "kWh", None), ("1", "L/min", None), ("1", None, None), ("1", "", None),
    ("1e308", "GW", None),
])
def test_actual_power_units_unknowns_and_negative_consumption(value, unit, expected):
    assert consumer_power_watts(state(value, unit)) == expected


def test_top10_is_sorted_before_limiting_and_ties_use_entity_id():
    devices = tuple(EnergyConsumer(f"sensor.device_{index:02d}") for index in range(15))
    states = {device.entity_id: state(index * 100) for index, device in enumerate(devices)}
    result = consumers_payload(devices, states, "en")
    assert [item["watts"] for item in result["items"]] == list(range(1400, 400, -100))
    assert all(item["value"] == f'{item["watts"]:.0f} W' for item in result["items"])
    assert all(set(item) == {"entity_id", "label", "watts", "value", "color"} for item in result["items"])
    assert result["unit"] == "W" and result["status"] == ""
    tied = consumers_payload(tuple(reversed(devices)), dict.fromkeys(states, state(1)), "en")
    assert [item["entity_id"] for item in tied["items"]] == sorted(states)[:10]


def test_unavailable_is_excluded_and_actual_zero_remains_zero():
    sources = (EnergyConsumer("sensor.missing"), EnergyConsumer("sensor.zero"), EnergyConsumer("sensor.negative"))
    result = consumers_payload(sources, {"sensor.zero": state(0), "sensor.negative": state(-1)}, "en")
    assert len(result["items"]) == 1
    assert result["items"][0]["entity_id"] == "sensor.zero"
    assert result["items"][0]["value"] == "0 W" and result["items"][0]["watts"] == 0
    assert result["status"] == ENERGY_LABELS_BY_LANGUAGE["en"]["consumers_incomplete"]
    empty = consumers_payload((), {}, "en")
    assert empty["items"] == [] and empty["status"] == ""


def test_colors_follow_entity_identity_not_power_rank_or_preferences_order():
    first, second = EnergyConsumer("sensor.first"), EnergyConsumer("sensor.second")
    before = consumers_payload((first, second), {first.entity_id: state(10), second.entity_id: state(20)}, "en")
    after = consumers_payload((second, first), {first.entity_id: state(30), second.entity_id: state(10)}, "en")
    assert [item["entity_id"] for item in before["items"]] != [item["entity_id"] for item in after["items"]]
    assert {item["entity_id"]: item["color"] for item in before["items"]} == {
        item["entity_id"]: item["color"] for item in after["items"]}
    assert consumer_color(first.entity_id) == before["items"][1]["color"]


@pytest.mark.parametrize(("value", "unit", "watts", "display"), [
    (0, "W", 0, "0 W"), (-0.0, "W", 0, "0 W"),
    (0.00123456, "W", 0.00123456, "0 W"), (1e-200, "W", 1e-200, "0 W"),
    (0.5, "W", 0.5, "0 W"), (1.5, "W", 1.5, "2 W"),
    (2.5, "W", 2.5, "2 W"), (3.5, "W", 3.5, "4 W"),
    (0.49999999999999994, "W", 0.49999999999999994, "0 W"),
    (0.5000000000000001, "W", 0.5000000000000001, "1 W"),
    (1234.5678912345, "W", 1234.5678912345, "1235 W"),
    (22000.5, "W", 22000.5, "22000 W"), (22001.5, "W", 22001.5, "22002 W"),
    (1.2345, "kW", 1234.5, "1234 W"), (1.2355, "kW", 1235.5, "1236 W"),
    (0.0005, "kW", 0.5, "0 W"), (1e20, "W", 1e20, "100000000000000000000 W"),
    (999999999999999900000, "W", 999999999999999900000.0, "999999999999999868928 W"),
    (1e21, "W", 1e21, "1e+21 W"),
])
@pytest.mark.parametrize("language", ["de", "en", "fr", "it", "unknown"])
def test_value_text_is_whole_watts_without_changing_measurement(value, unit, watts, display, language):
    item = consumers_payload((EnergyConsumer("sensor.power"),),
                             {"sensor.power": state(value, unit)}, language)["items"][0]
    assert item["value"] == display
    assert item["watts"] == watts


def test_display_rounding_does_not_change_top10_ranking():
    devices = tuple(EnergyConsumer(f"sensor.device_{index:02d}") for index in range(12))
    states = {device.entity_id: state(1 + index / 100) for index, device in enumerate(devices)}
    items = consumers_payload(devices, states, "en")["items"]
    assert [item["entity_id"] for item in items] == [device.entity_id for device in reversed(devices[2:])]
    assert [item["watts"] for item in items] == [1 + index / 100 for index in range(11, 1, -1)]
    assert all(item["value"] == "1 W" for item in items)


@pytest.mark.parametrize("language", ["de", "en", "fr", "it", "unknown"])
def test_names_units_localization_and_extremes_stay_bounded(language):
    devices = (EnergyConsumer("sensor.first", "My custom name"), EnergyConsumer("sensor.second"),
               EnergyConsumer("sensor.third"), EnergyConsumer("sensor.tiny"), EnergyConsumer("sensor.huge"))
    result = consumers_payload(devices, {"sensor.first": state(1.25, "kW", "Ignore me"),
        "sensor.second": state(1.25, name="  Friendly\nname  "), "sensor.third": state(0, name=""),
        "sensor.tiny": state(1e-100), "sensor.huge": state(1e300)}, language)
    items = {item["entity_id"]: item for item in result["items"]}
    assert items["sensor.first"]["label"] == "My custom name"
    assert items["sensor.second"]["label"] == "Friendly name"
    assert items["sensor.third"]["label"] == "sensor.third"
    assert items["sensor.first"]["value"] == "1250 W"
    assert items["sensor.second"]["value"] == "1 W"
    assert items["sensor.tiny"]["value"] == "0 W"
    assert items["sensor.tiny"]["watts"] == 1e-100
    assert items["sensor.huge"]["watts"] == 1e300
    assert items["sensor.huge"]["value"] == "1e+300 W"
    assert all(len(item["value"]) <= 25 and item["value"].endswith(" W") for item in items.values())
    assert len(json.dumps(result, allow_nan=False)) < 2048


@pytest.mark.parametrize("watts", [1e21, 1.0000000000000001e21, 1.2345678901234567e200, sys.float_info.max])
def test_extreme_display_round_trips_without_clamping_the_measurement(watts):
    item = consumers_payload((EnergyConsumer("sensor.power"),),
                             {"sensor.power": state(watts)}, "en")["items"][0]
    assert item["watts"] == watts
    assert len(item["value"]) <= 25
    assert "e+" in item["value"] and item["value"].endswith(" W")
    assert float(item["value"].removesuffix(" W")) == watts


def test_consumer_page_is_independent_of_daily_energy_and_allows_no_aggregate_sources():
    sources = EnergySources(consumers=(EnergyConsumer("sensor.power"),))
    kwargs = {"views": ["consumers"], "consumer_states": {"sensor.power": state(123)}}
    before = energy_page(sources, EnergyDay(), {}, **kwargs)
    after = energy_page(sources, EnergyDay(hours={"sensor.energy": [999] * 24}), {}, **kwargs)
    assert before == after and set(before["energy"]) == {"views", "consumers"}
    assert before["energy"]["consumers"]["items"][0]["watts"] == 123
    assert energy_page(EnergySources(), EnergyDay(), {}, views=["consumers"])["energy"]["consumers"]["items"] == []
    assert "consumers" not in energy_page(sources, EnergyDay(), {}, views=["now"])["energy"]


def test_retired_and_unknown_lists_never_default_to_recorder_views():
    assert ENERGY_VIEWS == ("now", "today", "power", "consumers", "balance")
    assert ENERGY_DAY_VIEWS == ("now", "today", "balance")
    assert ENERGY_LIVE_VIEWS == ("now", "consumers")
    for value in (["distribution"], ["unknown"], [], [False], [None]):
        assert energy_views(value) == ()
    assert energy_views(["now", "distribution", "balance"]) == ("now", "balance")
