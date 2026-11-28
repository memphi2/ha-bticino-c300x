"""History uses configured readings and never turns unobserved buckets into zero."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.components.energy.data import (
    ENERGY_SOURCE_SCHEMA,
    _migrate_legacy_grid_to_unified,
)

from custom_components.bticino_c300x.dashboard_energy import (
    EnergyDay,
    energy_page,
    energy_sources,
    source_power_watts,
)
from custom_components.bticino_c300x.dashboard_energy_power import (
    PowerHistory,
    power_history_from_statistics,
    power_history_payload,
)
from custom_components.bticino_c300x.dashboard_labels import ENERGY_LABELS_BY_LANGUAGE

START = datetime(2026, 11, 15, tzinfo=UTC)
END = START + timedelta(days=1)


def payload(sources, values, language="en"):
    return power_history_payload(sources, PowerHistory(START, END, values), language)


def by_id(result):
    return {series["id"]: series for series in result["series"]}


def watts(result, key, index=0):
    return by_id(result)[key]["values"][index]


def sources_with_unconfigured_power(kind, sensors=2):
    sources = [
        {"type": kind, "stat_energy_from": f"sensor.energy_{index}",
         **({"stat_rate": f"sensor.power_{index}"} if index < sensors else {})}
        for index in range(sensors + 1)
    ]
    return energy_sources({"energy_sources": sources})


def test_real_ha_migration_preserves_grid_and_home_without_partial_designation():
    legacy = {
        "type": "grid", "cost_adjustment_day": 0,
        "flow_from": [{"stat_energy_from": "sensor.tariff_a"},
                      {"stat_energy_from": "sensor.tariff_b"}],
        "flow_to": [], "power": [{"stat_rate": "sensor.grid_power"}],
    }
    migrated = ENERGY_SOURCE_SCHEMA(_migrate_legacy_grid_to_unified(legacy))
    assert len(migrated) == 2
    assert sum("stat_rate" in source for source in migrated) == 1
    sources = energy_sources({"energy_sources": migrated})
    rows = [{"start": START.timestamp() + index * 300,
             "end": START.timestamp() + (index + 1) * 300, "mean": 750}
            for index in range(3)]
    history = power_history_from_statistics(
        START, END, frozenset(sources.power_entities), {"sensor.grid_power": rows},
    )
    result = power_history_payload(sources, history, "en")
    assert set(by_id(result)) == {"grid", "home"}
    assert all("partial" not in series for series in result["series"])
    assert watts(result, "grid") == pytest.approx(750, abs=0.03)
    assert watts(result, "home") == pytest.approx(750, abs=0.03)
    assert by_id(result)["grid"]["dots"] == [0]
    assert all(value is None for value in by_id(result)["grid"]["values"][1:])
    assert source_power_watts(sources, {"sensor.grid_power": 750}) == {"grid": 750, "home": 750}
    before = payload(energy_sources({"energy_sources": [legacy]}), {"sensor.grid_power": (750,)})
    assert watts(before, "grid") == watts(result, "grid")
    assert before == result


def test_sanitized_multi_meter_shape_uses_available_sensors_and_unconfigured_zero():
    configured = ENERGY_SOURCE_SCHEMA([
        {"type": "solar", "stat_energy_from": "sensor.solar_energy"},
        {"type": "battery", "stat_energy_from": "sensor.discharge_energy",
         "stat_energy_to": "sensor.charge_energy", "stat_rate": "sensor.battery_net",
         "power_config": {"stat_rate_from": "sensor.discharge", "stat_rate_to": "sensor.charge"}},
        {"type": "grid", "cost_adjustment_day": 0,
         "stat_energy_from": "sensor.main_energy", "stat_rate": "sensor.grid_net",
         "power_config": {"stat_rate_from": "sensor.import", "stat_rate_to": "sensor.export"}},
        {"type": "grid", "cost_adjustment_day": 0,
         "stat_energy_from": "sensor.charger_energy", "stat_rate": "sensor.charger_power",
         "power_config": {"stat_rate": "sensor.charger_power"}},
        {"type": "grid", "cost_adjustment_day": 0, "stat_energy_from": "sensor.tariff_a"},
        {"type": "grid", "cost_adjustment_day": 0, "stat_energy_from": "sensor.tariff_b"},
    ])
    sources = energy_sources({"energy_sources": configured})
    result = payload(sources, {
        "sensor.grid_net": (100, 100, 0), "sensor.charger_power": (200, None, 0),
        "sensor.battery_net": (0, 0, 0),
        "sensor.import": (9999,) * 3, "sensor.export": (9999,) * 3,
    })
    assert set(by_id(result)) == {"grid", "solar", "battery", "home"}
    assert all("partial" not in series for series in result["series"])
    assert watts(result, "grid", 0) == pytest.approx(300, abs=0.03)
    assert watts(result, "grid", 1) is None
    assert watts(result, "grid", 2) == 0
    assert watts(result, "battery") == 0
    assert watts(result, "home", 0) == pytest.approx(300, abs=0.03)
    assert watts(result, "home", 1) is None
    assert watts(result, "home", 2) == 0
    assert [watts(result, "solar", index) for index in range(3)] == [0, 0, 0]
    assert all(value is None for series in result["series"] for value in series["values"][3:])
    now = energy_page(sources, EnergyDay(), {
        "sensor.grid_net": 100, "sensor.charger_power": 200, "sensor.battery_net": 0,
    }, views=["now"])["energy"]["nodes"]
    assert now["grid"]["power"] == now["home"]["power"] == "300 W"
    assert now["solar"]["power"] == "0 W"
    assert now["battery"]["power"] == "0 W"


@pytest.mark.parametrize("kind", ["grid", "battery", "solar"])
@pytest.mark.parametrize("language", ["en", "de", "fr", "it", "es", "unsupported"])
def test_groups_keep_normal_labels_and_preserve_signed_sum_zero_and_holes(kind, language):
    sources = sources_with_unconfigured_power(kind)
    result = payload(sources, {
        "sensor.power_0": (200, 0, -300, None),
        "sensor.power_1": (100, 0, 100, 100),
    }, language)
    assert set(by_id(result)) == {kind, "home"}
    series = by_id(result)[kind]
    labels = ENERGY_LABELS_BY_LANGUAGE.get(language, ENERGY_LABELS_BY_LANGUAGE["en"])
    assert "partial" not in series
    assert series["label"] == labels[kind]
    assert by_id(result)["home"]["label"] == labels["home"]
    assert [watts(result, kind, index) for index in range(3)] == pytest.approx([300, 0, -200], abs=0.03)
    assert [watts(result, "home", index) for index in range(3)] == pytest.approx([300, 0, 0], abs=0.03)
    assert len(series["values"]) == 96
    assert all(value is None for value in series["values"][3:])
    assert all(value is None for value in by_id(result)["home"]["values"][3:])
    assert all(result["axis"]["min"] <= value <= result["axis"]["max"]
               for value in series["values"] if value is not None)
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("kind", ["grid", "battery", "solar"])
@pytest.mark.parametrize("missing", [None, float("nan"), float("inf"), float("-inf"), True])
def test_group_never_substitutes_zero_for_missing_configured_readings(kind, missing):
    result = payload(sources_with_unconfigured_power(kind), {
        "sensor.power_0": (100, 0), "sensor.power_1": (missing, 0),
    })
    assert set(by_id(result)) == {kind, "home"}
    assert watts(result, kind, 0) is None
    assert watts(result, kind, 1) == 0
    assert by_id(result)[kind]["dots"] == [1]
    assert watts(result, "home", 0) is None
    assert watts(result, "home", 1) == 0


@pytest.mark.parametrize("kind", ["grid", "battery", "solar"])
def test_missing_history_and_overflow_do_not_fabricate_curve(kind):
    sources = sources_with_unconfigured_power(kind)
    assert payload(sources, {"sensor.power_0": (100,)})["series"] == []
    result = payload(sources, {"sensor.power_0": (1e308, 0), "sensor.power_1": (1e308, 0)})
    assert watts(result, kind, 0) is None
    assert watts(result, kind, 1) == 0
    assert payload(sources_with_unconfigured_power(kind, sensors=0), {})["series"] == []


@pytest.mark.parametrize("kind", ["grid", "battery", "solar"])
def test_complete_groups_keep_existing_labels_and_home(kind):
    sources = energy_sources({"energy_sources": [
        {"type": kind, "stat_energy_from": "sensor.energy", "stat_rate": "sensor.power"},
    ]})
    result = payload(sources, {"sensor.power": (300, 0)})
    assert set(by_id(result)) == {kind, "home"}
    for key, series in by_id(result).items():
        assert "partial" not in series
        assert series["label"] == ENERGY_LABELS_BY_LANGUAGE["en"][key]
        assert watts(result, key) == pytest.approx(300, abs=0.03)
        assert watts(result, key, 1) == 0


@pytest.mark.parametrize("kind", ["grid", "battery", "solar"])
def test_unconfigured_zero_and_home_exist_only_in_observed_buckets(kind):
    configured_kind = "solar" if kind == "grid" else "grid"
    sources = energy_sources({"energy_sources": [
        {"type": kind, "stat_energy_from": "sensor.unconfigured_energy"},
        {"type": configured_kind, "stat_energy_from": "sensor.configured_energy",
         "stat_rate": "sensor.configured_power"},
    ]})
    result = payload(sources, {"sensor.configured_power": (400, None, 0, None, 200)})
    assert set(by_id(result)) == {kind, configured_kind, "home"}
    for index, expected in enumerate((400, None, 0, None, 200)):
        assert watts(result, kind, index) == (None if expected is None else 0)
        assert watts(result, "home", index) == pytest.approx(expected, abs=0.03)
    for series in result["series"]:
        assert series["dots"] == [0, 2, 4]
        assert all(value is None for value in series["values"][5:])


@pytest.mark.parametrize("kind", ["grid", "battery", "solar"])
@pytest.mark.parametrize("missing", [None, float("nan"), float("inf"), float("-inf"), True])
def test_all_configured_samples_invalid_does_not_create_unconfigured_zero_curve(kind, missing):
    configured_kind = "solar" if kind == "grid" else "grid"
    sources = energy_sources({"energy_sources": [
        {"type": kind, "stat_energy_from": "sensor.energy"},
        {"type": configured_kind, "stat_energy_from": "sensor.other_energy", "stat_rate": "sensor.power"},
    ]})
    assert payload(sources, {"sensor.power": (missing,) * 96})["series"] == []
    assert payload(sources, {"sensor.unselected": (500,) * 96})["series"] == []
    assert payload(sources, {})["series"] == []


def test_all_unconfigured_power_has_zero_live_values_but_no_historical_observations():
    sources = energy_sources({"energy_sources": [
        {"type": kind, "stat_energy_from": f"sensor.{kind}_energy"}
        for kind in ("grid", "solar", "battery")
    ]})
    assert not sources.power_entities
    assert source_power_watts(sources, {}) == {"grid": 0, "solar": 0, "battery": 0, "home": 0}
    assert payload(sources, {})["series"] == []
    assert payload(sources, {"sensor.unselected": (500,) * 96})["series"] == []


def test_one_observed_group_does_not_fill_another_configured_groups_gap():
    sources = energy_sources({"energy_sources": [
        {"type": "grid", "stat_energy_from": "sensor.grid_energy", "stat_rate": "sensor.grid_power"},
        {"type": "solar", "stat_energy_from": "sensor.solar_energy", "stat_rate": "sensor.solar_power"},
        {"type": "battery", "stat_energy_from": "sensor.battery_energy"},
    ]})
    result = payload(sources, {"sensor.grid_power": (100, None, 0), "sensor.solar_power": (None, 200, 0)})
    assert [watts(result, "battery", index) for index in range(3)] == [0, 0, 0]
    assert [watts(result, "grid", index) for index in range(3)] == pytest.approx([100, None, 0], abs=0.03)
    assert [watts(result, "solar", index) for index in range(3)] == pytest.approx([None, 200, 0], abs=0.03)
    assert [watts(result, "home", index) for index in range(3)] == [None, None, 0]
    assert all(value is None for series in result["series"] for value in series["values"][3:])
