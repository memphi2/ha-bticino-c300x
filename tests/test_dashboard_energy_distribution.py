"""Current-power Sankey uses unconfigured zero and preserves configured unknowns."""

import json
import math
from dataclasses import replace
from itertools import product

import pytest

from custom_components.bticino_c300x.dashboard_energy import (
    COLOR_BATTERY,
    COLOR_EXPORT,
    COLOR_GRID,
    COLOR_HOME,
    COLOR_SOLAR,
    ENERGY_DAY_VIEWS,
    ENERGY_LIVE_VIEWS,
    ENERGY_VIEWS,
    EnergyDay,
    EnergyMeter,
    EnergySources,
    energy_page,
    energy_sources,
    format_power,
    power_watts,
)
from custom_components.bticino_c300x.dashboard_energy_distribution import (
    power_distribution_payload,
)
from custom_components.bticino_c300x.dashboard_labels import ENERGY_LABELS_BY_LANGUAGE

SOURCES = EnergySources(
    grid_from=(EnergyMeter("sensor.grid_energy"),),
    grid_to=(EnergyMeter("sensor.export_energy"),),
    solar=(EnergyMeter("sensor.solar_energy"),),
    battery_from=(EnergyMeter("sensor.discharge_energy"),),
    battery_to=(EnergyMeter("sensor.charge_energy"),),
    grid_power=("sensor.grid",), solar_power=("sensor.solar",),
    battery_power=("sensor.battery",),
)


def payload(grid=400, solar=1000, battery=100, *, sources=SOURCES, language="en"):
    return power_distribution_payload(sources, {
        "sensor.grid": grid, "sensor.solar": solar, "sensor.battery": battery,
    }, language)


def nodes(result):
    return {item["id"]: item for side in ("left", "right") for item in result[side]}


def assert_incomplete(result):
    assert result["complete"] is False
    assert result["status"] == ENERGY_LABELS_BY_LANGUAGE["en"]["distribution_incomplete"]
    assert nodes(result)["home"]["value"] == "--"
    assert nodes(result)["home"]["watts"] is None
    assert all(node["start"] == node["size"] == 0 for node in nodes(result).values())
    json.dumps(result, allow_nan=False)


def test_view_order_and_resource_sets():
    assert ENERGY_VIEWS == ("now", "today", "power", "distribution", "balance")
    assert ENERGY_DAY_VIEWS == ("now", "today", "balance")
    assert ENERGY_LIVE_VIEWS == ("now", "distribution")


@pytest.mark.parametrize(("grid", "solar", "battery"), list(product((-500, 0, 500), (0, 600, 2000), (-300, 0, 300))))
def test_signed_sources_conserve_current_power_without_attribution(grid, solar, battery):
    result = payload(grid, solar, battery)
    all_nodes = nodes(result)
    assert [item["id"] for item in result["left"]] == ["grid", "solar", "battery"]
    assert [item["id"] for item in result["right"]] == ["home", "export", "charge"]
    assert "edges" not in result
    assert result["unit"] == "W"
    assert all_nodes["grid"]["watts"] == max(0, grid)
    assert all_nodes["export"]["watts"] == max(0, -grid)
    assert all_nodes["battery"]["watts"] == max(0, battery)
    assert all_nodes["charge"]["watts"] == max(0, -battery)
    assert all_nodes["solar"]["watts"] == solar
    if grid + solar + battery < 0:
        assert_incomplete(result)
        return
    assert result["complete"] is True and result["status"] == ""
    assert all_nodes["home"]["watts"] == grid + solar + battery
    supplied = sum(item["watts"] for item in result["left"])
    assert sum(item["watts"] for item in result["right"]) == supplied
    for side in ("left", "right"):
        cursor = 0
        for item in result[side]:
            assert 0 <= item["start"] <= 1 and 0 <= item["size"] <= 1
            assert item["start"] == pytest.approx(cursor)
            assert item["size"] == pytest.approx(item["watts"] / supplied if supplied else 0)
            cursor += item["size"]
        assert cursor == pytest.approx(1 if supplied else 0)
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("kind", ["grid", "solar", "battery"])
@pytest.mark.parametrize("missing", [None, float("nan"), float("inf"), float("-inf"), True])
def test_unknown_readings_keep_measured_nodes_without_fabricating_balance(kind, missing):
    result = payload(**{kind: missing})
    assert_incomplete(result)
    assert nodes(result)[kind]["value"] == "--"
    assert nodes(result)[kind]["watts"] is None
    if kind in ("grid", "battery"):
        assert nodes(result)["export" if kind == "grid" else "charge"]["watts"] is None
    measured = "solar" if kind != "solar" else "grid"
    assert nodes(result)[measured]["watts"] == (1000 if measured == "solar" else 400)


@pytest.mark.parametrize("kind", ["grid", "solar", "battery"])
def test_unconfigured_source_power_contributes_zero_without_incomplete_status(kind):
    sources = energy_sources({"energy_sources": [
        {"type": kind, "stat_energy_from": "sensor.first_energy", "stat_rate": "sensor.first_power"},
        {"type": kind, "stat_energy_from": "sensor.second_energy"},
    ]})
    result = power_distribution_payload(sources, {"sensor.first_power": 500}, "en")
    assert result["complete"] is True and result["status"] == ""
    assert nodes(result)[kind]["watts"] == nodes(result)["home"]["watts"] == 500
    assert nodes(result)[kind]["size"] == nodes(result)["home"]["size"] == 1
    assert nodes(result)[kind]["label"] == ENERGY_LABELS_BY_LANGUAGE["en"][kind]


@pytest.mark.parametrize("kind", ["grid", "solar", "battery"])
def test_unconfigured_source_power_is_zero_even_when_no_power_entities_exist(kind):
    sources = energy_sources({"energy_sources": [
        {"type": kind, "stat_energy_from": "sensor.energy"},
    ]})
    result = power_distribution_payload(sources, {}, "en")
    assert result["complete"] is True and result["status"] == ""
    assert all(item["watts"] == 0 and item["value"] == "0 W" for item in nodes(result).values())
    assert all(item["size"] == item["start"] == 0 for item in nodes(result).values())


@pytest.mark.parametrize("kind", ["grid", "solar", "battery"])
def test_aggregation_requires_every_configured_reading(kind):
    sources = replace(SOURCES, **{f"{kind}_power": (f"sensor.{kind}", "sensor.missing")})
    result = payload(sources=sources)
    assert_incomplete(result)
    assert nodes(result)[kind]["watts"] is None


def test_negative_solar_is_invalid_even_if_other_panels_make_sum_positive():
    sources = replace(SOURCES, solar_power=("sensor.solar", "sensor.other_panel"))
    for solar in (-0.01, -100, -1000):
        result = power_distribution_payload(sources, {
            "sensor.grid": 400, "sensor.battery": 0,
            "sensor.solar": solar, "sensor.other_panel": 2000,
        }, "en")
        assert_incomplete(result)
        assert nodes(result)["solar"]["watts"] is None


def test_export_and_charging_larger_than_supply_never_clamp_home_to_zero():
    result = payload(grid=-800, solar=1000, battery=-300)
    assert_incomplete(result)
    assert nodes(result)["export"]["watts"] == 800
    assert nodes(result)["charge"]["watts"] == 300
    assert_incomplete(payload(grid=-0.001, solar=0, battery=0))


@pytest.mark.parametrize(("solar", "export", "charge"), [
    (0.3, 0.1, 0.2), (3.3, 1.1, 2.2), (3000.6, 1000.2, 2000.4),
])
def test_fractional_balanced_flows_allow_roundoff_without_negative_home(solar, export, charge):
    assert export + charge > solar  # The reproduced binary rounding deficit.
    result = payload(grid=-export, solar=solar, battery=-charge)
    assert result["complete"] is True and result["status"] == ""
    home = nodes(result)["home"]
    assert home["watts"] == 0 and math.copysign(1, home["watts"]) == 1
    assert home["value"] == "0 W" and home["size"] == 0
    assert nodes(result)["export"]["watts"] == export
    assert nodes(result)["charge"]["watts"] == charge
    for side in ("left", "right"):
        assert all(0 <= item["start"] <= 1 and 0 <= item["size"] <= 1 for item in result[side])
        assert sum(item["size"] for item in result[side]) == pytest.approx(1, rel=0, abs=math.ulp(1))
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("supplied", [1e-200, 1e-12, 1.0, 1e12, 1e300])
def test_balance_tolerance_accepts_only_one_ulp(supplied):
    one_step = math.nextafter(supplied, math.inf)
    result = payload(grid=-one_step, solar=supplied, battery=0)
    assert result["complete"] is True
    assert nodes(result)["home"]["watts"] == 0
    assert_incomplete(payload(grid=-math.nextafter(one_step, math.inf), solar=supplied, battery=0))


@pytest.mark.parametrize(("supplied", "removed"), [
    (0, math.ulp(0)), (0, 1e-12), (1e-12, 1e-12 + 1e-15),
    (1.0, 1.0 + 1e-12), (1e12, 1e12 + 0.001), (1e300, 1e300 + 1e290),
])
def test_real_deficits_are_not_hidden_by_absolute_or_relative_tolerance(supplied, removed):
    assert removed > supplied
    assert_incomplete(payload(grid=-removed, solar=supplied, battery=0))


@pytest.mark.parametrize(("grid", "solar", "battery"), [
    (1e308, 1e308, 0), (-1e308, 1e308, -1e308),
])
def test_overflowing_flow_totals_cannot_be_accepted_as_roundoff(grid, solar, battery):
    assert_incomplete(payload(grid=grid, solar=solar, battery=battery))


def test_overflow_does_not_emit_nonfinite_values_or_bands():
    assert_incomplete(payload(grid=1e308, solar=1e308, battery=0))
    sources = replace(SOURCES, grid_power=("sensor.grid", "sensor.second"))
    result = power_distribution_payload(sources, {
        "sensor.grid": 1e308, "sensor.second": 1e308,
        "sensor.solar": 0, "sensor.battery": 0,
    }, "en")
    assert_incomplete(result)
    assert nodes(result)["grid"]["watts"] is None


@pytest.mark.parametrize("kind", ["grid", "solar", "battery"])
def test_unconfigured_groups_are_absent_and_measured_zero_is_not_unknown(kind):
    sources = energy_sources({"energy_sources": [
        {"type": kind, "stat_energy_from": "sensor.energy", "stat_rate": "sensor.power"},
    ]})
    result = power_distribution_payload(sources, {"sensor.power": 0}, "en")
    assert [item["id"] for item in result["left"]] == [kind]
    assert result["complete"] is True
    assert result["empty_text"] == ENERGY_LABELS_BY_LANGUAGE["en"]["distribution_empty"]
    assert all(item["value"] == "0 W" and item["size"] == 0 for item in nodes(result).values())


@pytest.mark.parametrize("language", ["en", "de", "fr", "it", "unknown"])
def test_contract_labels_colors_and_revision(language):
    result = payload(grid=-200, solar=2000, battery=-300, language=language)
    labels = ENERGY_LABELS_BY_LANGUAGE.get(language, ENERGY_LABELS_BY_LANGUAGE["en"])
    colors = {"grid": COLOR_GRID, "solar": COLOR_SOLAR, "battery": COLOR_BATTERY,
              "home": COLOR_HOME, "export": COLOR_EXPORT, "charge": COLOR_BATTERY}
    for key, item in nodes(result).items():
        assert item["label"] == labels[key]
        assert item["color"] == colors[key]
        assert item["value"] == format_power(item["watts"], language)
        assert set(item) == {"id", "label", "value", "watts", "color", "start", "size"}
    assert result == payload(grid=-200, solar=2000, battery=-300, language=language)
    assert result["revision"] != payload(grid=-201, solar=2000, battery=-300, language=language)["revision"]
    incomplete = payload(grid=None, language=language)
    assert incomplete["status"] == labels["distribution_incomplete"]
    assert incomplete["revision"] != result["revision"]


def test_current_payload_is_independent_of_daily_kwh_and_selected_only():
    readings = {"sensor.grid": 400, "sensor.solar": 1000, "sensor.battery": -100}
    first = energy_page(SOURCES, EnergyDay(), readings, views=["distribution"])
    second = energy_page(SOURCES, EnergyDay(hours={"sensor.grid_energy": [9999] * 24}),
                         readings, views=["distribution"])
    assert first == second
    assert set(first["energy"]) == {"views", "distribution"}
    assert nodes(first["energy"]["distribution"])["home"]["watts"] == 1300
    assert "distribution" not in energy_page(SOURCES, EnergyDay(), readings, views=["now"])["energy"]


def test_no_sources_is_not_a_zero_home_reading():
    result = power_distribution_payload(EnergySources(), {}, "en")
    assert_incomplete(result)
    assert result["left"] == []
    assert energy_page(EnergySources(), EnergyDay(), {}, views=["distribution"]) is None


def test_kw_sensor_values_are_converted_before_the_watt_contract():
    from types import SimpleNamespace

    reading = power_watts(SimpleNamespace(state="1.5", attributes={"unit_of_measurement": "kW"}))
    result = payload(grid=reading, solar=0, battery=0)
    assert nodes(result)["grid"]["watts"] == 1500
    assert nodes(result)["grid"]["value"] == "1.5 kW"
