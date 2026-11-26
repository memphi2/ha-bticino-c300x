from __future__ import annotations

from itertools import pairwise
from types import SimpleNamespace

import pytest

from custom_components.bticino_c300x.dashboard_energy import (
    COLOR_EXPORT,
    COLOR_GRID,
    COLOR_SOLAR,
    ENERGY_VIEWS,
    EnergyDay,
    EnergyMeter,
    EnergySources,
    energy_page,
    energy_sources,
    energy_views,
    format_energy,
    format_number,
    format_power,
    power_watts,
    source_power_watts,
)
from custom_components.bticino_c300x.dashboard_energy_charts import chart_axis


def _hours(total: float, hour: int = 12) -> list[float]:
    values = [0.0] * 24
    values[hour] = total
    return values


# The setup the page was designed against: balcony solar, a battery with
# separate meters, four grid meters with prices, an export meter that stays 0.
PREFERENCES = {
    "energy_sources": [
        {"type": "grid", "stat_energy_from": "sensor.house", "stat_energy_to": "sensor.export",
         "stat_cost": None, "stat_compensation": "sensor.export_pay", "name": "Hausstrom-Bezug",
         "stat_rate": "sensor.house_power"},
        {"type": "grid", "stat_energy_from": "sensor.wallbox", "stat_energy_to": None,
         "stat_cost": "sensor.wallbox_cost", "stat_compensation": None, "name": "Wallbox"},
        {"type": "grid", "stat_energy_from": "sensor.heat_nt", "stat_energy_to": None,
         "stat_cost": "sensor.heat_nt_cost", "stat_compensation": None, "name": "Heizung NT"},
        {"type": "grid", "stat_energy_from": "sensor.heat_ht", "stat_energy_to": None,
         "stat_cost": "sensor.heat_ht_cost", "stat_compensation": None, "name": "Heizung HT"},
        {"type": "solar", "stat_energy_from": "sensor.pv", "stat_rate": "sensor.pv_power"},
        {"type": "battery", "stat_energy_from": "sensor.bat_out", "stat_energy_to": "sensor.bat_in",
         "stat_rate": "sensor.bat_power"},
        {"type": "gas", "stat_energy_from": "sensor.gas"},
    ],
}
COST_SENSORS = {"sensor.house": "sensor.house_cost"}
SINGLE_GRID_PREFERENCES = {"energy_sources": [
    source for source in PREFERENCES["energy_sources"]
    if source["type"] != "grid" or source.get("stat_rate")
]}
DAY = EnergyDay(
    hours={
        "sensor.house": _hours(5.05), "sensor.wallbox": _hours(0.0),
        "sensor.heat_nt": _hours(20.0, 3), "sensor.heat_ht": _hours(0.0),
        "sensor.export": _hours(0.0), "sensor.pv": _hours(0.19),
        "sensor.bat_out": _hours(0.01, 18), "sensor.bat_in": _hours(0.1),
    },
    costs={
        "sensor.house_cost": 1.64, "sensor.wallbox_cost": 0.0,
        "sensor.heat_nt_cost": 4.80, "sensor.heat_ht_cost": 0.0, "sensor.export_pay": 0.0,
    },
)


def test_sources_come_from_the_energy_preferences() -> None:
    sources = energy_sources(PREFERENCES, COST_SENSORS)

    assert [meter.stat for meter in sources.grid_from] == [
        "sensor.house", "sensor.wallbox", "sensor.heat_nt", "sensor.heat_ht",
    ]
    # A price instead of a cost statistic: Home Assistant's own cost sensor.
    assert sources.grid_from[0] == EnergyMeter("sensor.house", "sensor.house_cost", "Hausstrom-Bezug")
    assert sources.grid_to == (EnergyMeter("sensor.export", "sensor.export_pay", "Hausstrom-Bezug"),)
    assert sources.solar == (EnergyMeter("sensor.pv"),)
    assert sources.battery_from == (EnergyMeter("sensor.bat_out"),)
    assert sources.battery_to == (EnergyMeter("sensor.bat_in"),)
    assert sources.grid_power == ("sensor.house_power",)
    assert sources.power_entities == {"sensor.house_power", "sensor.pv_power", "sensor.bat_power"}
    assert "sensor.gas" not in sources.energy_stats
    assert sources.cost_stats == {
        "sensor.house_cost", "sensor.wallbox_cost", "sensor.heat_nt_cost",
        "sensor.heat_ht_cost", "sensor.export_pay",
    }


def test_sources_accept_the_older_grid_format_and_ignore_broken_entries() -> None:
    sources = energy_sources({"energy_sources": [
        {"type": "grid",
         "flow_from": [{"stat_energy_from": "sensor.a", "stat_cost": "sensor.a_cost"}, "broken"],
         "flow_to": [{"stat_energy_to": "sensor.b", "stat_compensation": None}],
         "power": [{"stat_rate": "sensor.p"}, {"stat_rate": "sensor.p"}]},
        "broken", {"type": "solar"}, {"type": "battery", "stat_energy_from": " "},
    ]})

    assert sources.grid_from == (EnergyMeter("sensor.a", "sensor.a_cost"),)
    assert sources.grid_to == (EnergyMeter("sensor.b"),)
    assert sources.grid_power == ("sensor.p",)
    assert sources.solar == sources.battery_from == sources.battery_to == ()


@pytest.mark.parametrize("preferences", [None, {}, {"energy_sources": None}, {"energy_sources": []}, "x"])
def test_no_energy_setup_means_no_page(preferences) -> None:
    sources = energy_sources(preferences)

    assert sources.any is False
    assert energy_page(sources, EnergyDay(), {}) is None


def test_day_totals_match_home_assistants_own_energy_dashboard() -> None:
    page = energy_page(energy_sources(PREFERENCES, COST_SENSORS), DAY, {}, language="de", currency="€")

    assert page is not None and page["title"] == "Energie"
    energy = page["energy"]
    assert energy["views"] == [
        {"id": "now", "label": "Jetzt"}, {"id": "today", "label": "Heute"},
        {"id": "power", "label": "Leistung"},
        {"id": "consumers", "label": "Verbraucher"},
        {"id": "balance", "label": "Bilanz"},
    ]
    nodes = energy["nodes"]
    assert nodes["solar"]["lines"] == ["0,19 kWh"]
    assert nodes["grid"]["lines"] == ["25,1 kWh", "0 kWh"]
    assert nodes["battery"]["lines"] == ["0,01 kWh", "-0,1 kWh"]
    # 25.05 + 0.19 + 0.01 - 0 - 0.1 = 25.15
    assert nodes["home"]["lines"] == ["25,2 kWh"]
    assert all("power" not in node and node["flow"] == 0 for node in nodes.values())
    balance = {row["label"]: row for row in energy["balance"]}
    assert balance["PV-Eigenverbrauch"]["value"] == "100 %"
    assert balance["Autarkiegrad"]["value"] == "0 %"
    assert balance["Netto vom Netz"]["value"] == "25,1 kWh"
    assert balance["Kosten heute"]["value"] == "6,44 €"


def test_today_view_has_hourly_bars_and_a_bounded_sums_table() -> None:
    energy = energy_page(
        energy_sources(PREFERENCES, COST_SENSORS), DAY, {}, language="de", currency="€",
    )["energy"]

    hours = energy["hours"]
    assert [len(series["values"]) for series in hours["series"]] == [24] * 6
    assert sum(series["values"][3] for series in hours["series"][:3]) == 20.0
    assert hours["series"][3]["values"][12] == 0.19
    assert hours["max"] == 20.0 and hours["label"] == "20 kWh"
    sums = energy["sums"]
    assert len(sums) == 8
    assert [row["label"] for row in sums] == [
        "PV", "Batterie entladen", "Batterie laden", "Einspeisung",
        "Hausstrom-Bezug", "Wallbox", "Weitere Zähler", "Netz gesamt",
    ]
    assert sums[4]["value"] == "5,05 kWh" and sums[4]["cost"] == "1,64 €"
    # The two heating meters did not fit and are shown as one row.
    assert sums[6]["value"] == "20 kWh" and sums[6]["cost"] == "4,80 €"
    assert sums[7]["value"] == "25,1 kWh" and sums[7]["cost"] == "6,44 €"
    assert sums[2]["value"] == "-0,1 kWh" and "cost" not in sums[0]
    assert [series["color"] for series in hours["series"][:3]] == [
        row["color"] for row in sums[4:7]
    ]
    assert len({series["color"] for series in hours["series"]}) == 6


def test_power_sensors_add_live_values_and_directions() -> None:
    power = {"sensor.house_power": 850.0, "sensor.pv_power": 120.0, "sensor.bat_power": -200.0}

    nodes = energy_page(energy_sources(SINGLE_GRID_PREFERENCES), DAY, power, language="de")["energy"]["nodes"]

    assert (nodes["grid"]["power"], nodes["grid"]["flow"]) == ("850 W", 1)
    assert (nodes["solar"]["power"], nodes["solar"]["flow"]) == ("120 W", 1)
    # The battery is charging: energy flows away from the home's supply.
    assert (nodes["battery"]["power"], nodes["battery"]["flow"]) == ("200 W", -1)
    assert (nodes["home"]["power"], nodes["home"]["flow"]) == ("770 W", 1)


def test_home_power_needs_every_kind_of_source_to_report() -> None:
    power = {"sensor.house_power": 850.0, "sensor.pv_power": None}

    nodes = energy_page(energy_sources(SINGLE_GRID_PREFERENCES), DAY, power)["energy"]["nodes"]

    assert nodes["grid"]["power"] == "850 W"
    assert "power" not in nodes["solar"] and "power" not in nodes["home"]
    assert nodes["home"]["flow"] == 0


def test_only_configured_sources_and_selected_views_are_sent() -> None:
    sources = EnergySources(grid_from=(EnergyMeter("sensor.g"),))
    day = EnergyDay(hours={"sensor.g": _hours(2.5)})

    energy = energy_page(sources, day, {}, views=["balance", "now"])["energy"]

    assert [view["id"] for view in energy["views"]] == ["now", "balance"]
    assert set(energy["nodes"]) == {"grid", "home"}
    assert energy["nodes"]["grid"]["lines"] == ["2.5 kWh"]
    assert "hours" not in energy and "sums" not in energy
    # No solar: no self-consumption row; no price: no cost row.
    assert [row["label"] for row in energy["balance"]] == ["Self-sufficiency", "Net from grid"]


def test_a_single_unnamed_grid_meter_is_one_row() -> None:
    sources = EnergySources(grid_from=(EnergyMeter("sensor.g", "sensor.c"),))
    day = EnergyDay(hours={"sensor.g": _hours(2.5)}, costs={"sensor.c": 0.75})

    sums = energy_page(sources, day, {}, currency="EUR")["energy"]["sums"]

    assert sums == [{"label": "Grid total", "value": "2.5 kWh", "color": COLOR_GRID, "cost": "0.75 EUR"}]


def test_export_reduces_use_and_self_consumption() -> None:
    sources = EnergySources(
        grid_from=(EnergyMeter("sensor.g"),), grid_to=(EnergyMeter("sensor.e", "sensor.pay"),),
        solar=(EnergyMeter("sensor.s"),),
    )
    day = EnergyDay(
        hours={"sensor.g": _hours(1.0, 20), "sensor.s": _hours(4.0), "sensor.e": _hours(3.0)},
        costs={"sensor.pay": 0.24},
    )

    energy = energy_page(sources, day, {})["energy"]

    assert energy["nodes"]["home"]["lines"] == ["2 kWh"]
    assert energy["nodes"]["grid"]["lines"] == ["1 kWh", "-3 kWh"]
    balance = {row["label"]: row for row in energy["balance"]}
    assert balance["Solar used at home"]["value"] == "25 %"
    assert balance["Self-sufficiency"]["value"] == "50 %"
    assert balance["Net from grid"]["value"] == "-2 kWh"
    assert balance["Net from grid"]["ratio"] == 0.0
    assert balance["Cost today"]["value"] == "-0.24"


def test_a_late_meter_cannot_make_an_hour_negative() -> None:
    sources = EnergySources(grid_from=(EnergyMeter("sensor.g"),), grid_to=(EnergyMeter("sensor.e"),))
    day = EnergyDay(hours={"sensor.g": _hours(0.0), "sensor.e": _hours(0.5)})

    energy = energy_page(sources, day, {})["energy"]

    assert energy["nodes"]["home"]["lines"] == ["0 kWh"]
    assert energy["balance"][0] == {
        "label": "Net from grid", "value": "-0.5 kWh", "ratio": 0.0, "color": COLOR_EXPORT,
    }


def test_a_meter_correction_cannot_stretch_or_shrink_the_hour_bars() -> None:
    sources = EnergySources(grid_from=(EnergyMeter("sensor.g"),), solar=(EnergyMeter("sensor.s"),))
    grid = _hours(2.0, 8)
    grid[9] = -1.5
    day = EnergyDay(hours={"sensor.g": grid, "sensor.s": _hours(1.0, 9)})

    hours = energy_page(sources, day, {})["energy"]["hours"]

    assert hours["series"][0]["values"][9] == 0.0
    assert hours["max"] == 2.0 and hours["label"] == "2 kWh"


@pytest.mark.parametrize("imported,exported", [(2.0, 3.0), (0.0, 3.0), (2.0, 0.0), (0.0, 0.0), (2.0, -1.0)])
def test_today_export_is_negative_and_does_not_cancel_import_stack(imported, exported):
    sources = EnergySources(grid_from=(EnergyMeter("grid"),), grid_to=(EnergyMeter("export"),))
    day = EnergyDay(hours={"grid": _hours(imported), "export": _hours(exported)})
    hours = energy_page(sources, day, {}, views=["today"])["energy"]["hours"]
    assert hours["series"][0]["values"][12] == imported
    assert hours["series"][-1]["color"] == COLOR_EXPORT
    assert hours["series"][-1]["values"][12] == -max(0, exported)
    assert hours["axis"]["min"] <= -max(0, exported)
    assert hours["axis"]["max"] >= imported
    assert any(tick["value"] == 0 for tick in hours["axis"]["ticks"])


def test_a_battery_that_only_charges_has_no_series_in_the_hour_bars() -> None:
    sources = EnergySources(
        grid_from=(EnergyMeter("sensor.g"),), battery_to=(EnergyMeter("sensor.c"),),
    )
    day = EnergyDay(hours={"sensor.g": [1.0] + [0.0] * 23, "sensor.c": [0.5] + [0.0] * 23})

    hours = energy_page(sources, day, {})["energy"]["hours"]

    assert len(hours["series"]) == 1


def test_hour_bars_have_no_grid_series_without_a_grid_meter() -> None:
    sources = EnergySources(solar=(EnergyMeter("sensor.s"),))
    day = EnergyDay(hours={"sensor.s": _hours(1.0)})

    hours = energy_page(sources, day, {})["energy"]["hours"]

    assert [series["color"] for series in hours["series"]] == [COLOR_SOLAR]


@pytest.mark.parametrize(("value", "expected"), [
    (None, ENERGY_VIEWS), ([], ()), (["today"], ("today",)),
    (["balance", "bogus", "now"], ("now", "balance")), ("now", ENERGY_VIEWS),
])
def test_views_keep_display_order_and_default_to_all(value, expected) -> None:
    assert energy_views(value) == expected


def test_all_energy_subpages_can_be_switched_off() -> None:
    sources = energy_sources(SINGLE_GRID_PREFERENCES)
    assert energy_page(sources, DAY, {}, views=[]) is None
    assert energy_page(sources, DAY, {}, views=["power"])["energy"]["views"] == [
        {"id": "power", "label": "Power"},
    ]


@pytest.mark.parametrize(("low", "high"), [
    (0, 0), (0, 0.19), (0, 20), (-2400, 850), (-12.4, -0.1), (0, 3_000_000),
])
def test_chart_axis_has_readable_even_ticks_and_includes_zero(low, high) -> None:
    axis = chart_axis(low, high, "de", "W")
    ticks = axis["ticks"]
    assert 2 <= len(ticks) <= 5
    assert axis["min"] <= min(low, 0) <= max(high, 0) <= axis["max"]
    assert ticks[0]["position"] == 0 and ticks[-1]["position"] == 1
    assert any(tick["value"] == 0 for tick in ticks)
    assert len({tick["label"] for tick in ticks}) == len(ticks)
    step = ticks[1]["value"] - ticks[0]["value"]
    assert all(b["value"] - a["value"] == pytest.approx(step)
               for a, b in pairwise(ticks))


def test_chart_uses_one_unit_for_all_ticks_and_locale_decimal_signs() -> None:
    axis = chart_axis(-1200, 1200, "de", "W")
    assert axis["unit"] == "kW"
    assert [tick["label"] for tick in axis["ticks"]] == ["-2", "-1", "0", "1", "2"]
    small = chart_axis(0, 0.6, "de", "kWh")
    assert small["unit"] == "kWh"
    assert any("," in tick["label"] for tick in small["ticks"])
    assert chart_axis(0, 2000, "en", "kWh")["unit"] == "MWh"


@pytest.mark.parametrize(("low", "high"), [
    (float("nan"), float("inf")), (-1e308, 1e308), (0, 1.7e308), (0, 5e-324),
])
def test_chart_axis_never_emits_nonfinite_numbers(low, high) -> None:
    import json

    json.dumps(chart_axis(low, high, "en", "W"), allow_nan=False)


def test_power_overflow_is_missing_not_a_rendering_error() -> None:
    assert power_watts(SimpleNamespace(state="1e308", attributes={"unit_of_measurement": "kW"})) is None
    sources = EnergySources(
        grid_from=(EnergyMeter("sensor.g"),), solar=(EnergyMeter("sensor.s"),),
        grid_power=("sensor.gw",), solar_power=("sensor.sw",),
    )
    assert source_power_watts(sources, {"sensor.gw": 1e308, "sensor.sw": 1e308})["home"] is None


@pytest.mark.parametrize(("state", "unit", "expected"), [
    ("850", "W", 850.0), ("1.2", "kW", 1200.0), ("-0.5", "kW", -500.0), ("3", None, 3.0),
    ("unavailable", "W", None), ("nan", "W", None), ("inf", "W", None), ("5", "A", None),
])
def test_power_states_are_read_in_watts(state, unit, expected) -> None:
    attributes = {} if unit is None else {"unit_of_measurement": unit}

    assert power_watts(SimpleNamespace(state=state, attributes=attributes)) == expected
    assert power_watts(None) is None


def test_numbers_follow_the_display_language() -> None:
    assert format_number(0.19, "de") == "0,19"
    assert format_number(25.05, "en") == "25.1"
    assert format_number(120.4, "de") == "120"
    assert format_number(-0.001, "de") == "0"
    assert format_energy(5.5, "fr") == "5,5 kWh"
    assert format_power(999.4, "de") == "999 W"
    assert format_power(1234.0, "de") == "1,23 kW"
    assert format_power(12340.0, "en") == "12.3 kW"


def test_every_energy_text_exists_in_every_display_language() -> None:
    from custom_components.bticino_c300x.dashboard_labels import (
        ENERGY_LABELS_BY_LANGUAGE,
    )

    labels = ENERGY_LABELS_BY_LANGUAGE
    assert set(labels) == {"de", "en", "es", "fr", "it"}
    for language, texts in labels.items():
        assert set(texts) == set(labels["en"]), language
        assert all(text.strip() for text in texts.values()), language


def test_milliwatts_are_not_read_as_megawatts() -> None:
    def watts(value: str, unit: str) -> float | None:
        return power_watts(SimpleNamespace(state=value, attributes={"unit_of_measurement": unit}))

    assert watts("500", "mW") == 0.5
    assert watts("2", "MW") == 2_000_000.0
    assert watts("1.5", "kW") == 1500.0
    assert watts("3", "kw") is None, "an unknown spelling is not guessed"


def test_power_just_below_a_kilowatt_does_not_read_1000_w() -> None:
    assert format_power(999.6, "de") == "1 kW"
    assert format_power(-999.6, "en") == "-1 kW"
    assert format_power(999.4, "de") == "999 W"


def test_unconfigured_solar_power_contributes_zero_to_configured_readings() -> None:
    preferences = {"energy_sources": [
        {"type": "grid", "stat_energy_from": "sensor.house", "stat_rate": "sensor.house_power"},
        {"type": "solar", "stat_energy_from": "sensor.roof", "stat_rate": "sensor.roof_power"},
        {"type": "solar", "stat_energy_from": "sensor.balcony"},
    ]}
    power = {"sensor.house_power": 300.0, "sensor.roof_power": 500.0}

    nodes = energy_page(energy_sources(preferences), EnergyDay(), power, language="en")["energy"]["nodes"]

    assert nodes["solar"]["power"] == "500 W"
    assert nodes["home"]["power"] == "800 W"
    assert nodes["grid"]["power"] == "300 W"


def test_grid_connections_without_power_do_not_hide_configured_readings() -> None:
    sources = energy_sources(PREFERENCES)
    power = {"sensor.house_power": 850.0, "sensor.pv_power": 120.0, "sensor.bat_power": -200.0}

    nodes = energy_page(sources, DAY, power)["energy"]["nodes"]

    assert nodes["grid"]["power"] == "850 W" and nodes["grid"]["flow"] == 1
    assert nodes["home"]["power"] == "770 W" and nodes["home"]["flow"] == 1
    assert nodes["grid"]["lines"] == ["25.1 kWh", "0 kWh"]
    assert nodes["solar"]["power"] == "120 W"
    assert nodes["battery"]["power"] == "200 W"


@pytest.mark.parametrize("missing_direction", ["stat_energy_from", "stat_energy_to"])
def test_unconfigured_import_or_export_power_contributes_zero(missing_direction) -> None:
    sources = energy_sources({"energy_sources": [
        {"type": "grid", "stat_energy_from": "sensor.a", "stat_rate": "sensor.a_power"},
        {"type": "grid", missing_direction: "sensor.b"},
    ]})

    nodes = energy_page(sources, EnergyDay(), {"sensor.a_power": 300.0})["energy"]["nodes"]

    assert nodes["grid"]["power"] == nodes["home"]["power"] == "300 W"


@pytest.mark.parametrize("second_power", [200.0, None])
def test_all_configured_grid_power_sensors_must_report(second_power) -> None:
    sources = energy_sources({"energy_sources": [
        {"type": "grid", "stat_energy_from": "sensor.a", "stat_rate": "sensor.a_power"},
        {"type": "grid", "stat_energy_from": "sensor.b", "stat_rate": "sensor.b_power"},
    ]})
    power = {"sensor.a_power": 300.0, "sensor.b_power": second_power}

    nodes = energy_page(sources, EnergyDay(), power)["energy"]["nodes"]

    if second_power is None:
        assert "power" not in nodes["grid"] and "power" not in nodes["home"]
    else:
        assert nodes["grid"]["power"] == nodes["home"]["power"] == "500 W"


@pytest.mark.parametrize("legacy", [False, True])
def test_tariff_meters_can_share_one_grid_power_sensor(legacy: bool) -> None:
    if legacy:
        grid_sources = [{
            "type": "grid",
            "flow_from": [{"stat_energy_from": "sensor.ht"}, {"stat_energy_from": "sensor.nt"}],
            "flow_to": [{"stat_energy_to": "sensor.export"}],
            "power": [{"stat_rate": "sensor.power"}, {"stat_rate": "sensor.power"}],
        }]
    else:
        grid_sources = [
            {"type": "grid", "stat_energy_from": "sensor.ht", "stat_rate": "sensor.power"},
            {"type": "grid", "stat_energy_from": "sensor.nt", "stat_rate": "sensor.power"},
        ]
    sources = energy_sources({"energy_sources": grid_sources})

    nodes = energy_page(sources, EnergyDay(), {"sensor.power": 300.0})["energy"]["nodes"]

    assert len(sources.grid_from) == 2
    assert sources.grid_power == ("sensor.power",)
    assert nodes["grid"]["power"] == nodes["home"]["power"] == "300 W"


@pytest.mark.parametrize("kind", ["grid", "solar", "battery"])
@pytest.mark.parametrize("stat_rate", [None, "", " "])
def test_source_without_configured_power_is_zero_without_a_subscription(kind, stat_rate):
    sources = energy_sources({"energy_sources": [
        {"type": kind, "stat_energy_from": "sensor.energy", "stat_rate": stat_rate},
    ]})
    assert not sources.power_entities
    assert source_power_watts(sources, {"sensor.unselected": 999}) == {kind: 0, "home": 0}
    nodes = energy_page(sources, EnergyDay(), {}, views=["now"])["energy"]["nodes"]
    assert nodes[kind]["power"] == nodes["home"]["power"] == "0 W"
    assert nodes[kind]["flow"] == nodes["home"]["flow"] == 0


@pytest.mark.parametrize("kind", ["grid", "solar", "battery"])
@pytest.mark.parametrize("missing", [None, float("nan"), float("inf"), float("-inf"), True])
def test_configured_invalid_power_is_unknown_even_with_unconfigured_siblings(kind, missing):
    sources = energy_sources({"energy_sources": [
        {"type": kind, "stat_energy_from": "sensor.a_energy", "stat_rate": "sensor.a_power"},
        {"type": kind, "stat_energy_from": "sensor.b_energy", "stat_rate": "sensor.b_power"},
        {"type": kind, "stat_energy_from": "sensor.c_energy"},
    ]})
    assert sources.power_entities == {"sensor.a_power", "sensor.b_power"}
    assert source_power_watts(sources, {"sensor.a_power": 500, "sensor.b_power": missing}) == {
        kind: None, "home": None,
    }
    assert source_power_watts(sources, {"sensor.a_power": 500}) == {kind: None, "home": None}


@pytest.mark.parametrize(("value", "language", "expected"), [
    ("21.5", "de", "21,5"), (21.5, "fr", "21,5"), ("-0.25", "it", "-0,25"), ("21.5", "en", "21.5"),
    (7, "de", "7"), ("1.2.3", "de", "1.2.3"), ("2026-11-15", "de", "2026-11-15"), ("12.5 kW", "de", "12.5 kW"),
])
def test_one_helper_sets_the_decimal_sign_of_the_display_language(value, language, expected) -> None:
    from custom_components.bticino_c300x.dashboard_labels import decimal_text

    assert decimal_text(value, language) == expected
