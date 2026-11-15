from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.bticino_c300x.dashboard_energy import (
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
)


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
    assert [len(series["values"]) for series in hours["series"]] == [24, 24, 24]
    assert hours["series"][0]["values"][3] == 20.0
    assert hours["series"][1]["values"][12] == 0.19
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


def test_power_sensors_add_live_values_and_directions() -> None:
    power = {"sensor.house_power": 850.0, "sensor.pv_power": 120.0, "sensor.bat_power": -200.0}

    nodes = energy_page(energy_sources(PREFERENCES), DAY, power, language="de")["energy"]["nodes"]

    assert (nodes["grid"]["power"], nodes["grid"]["flow"]) == ("850 W", 1)
    assert (nodes["solar"]["power"], nodes["solar"]["flow"]) == ("120 W", 1)
    # The battery is charging: energy flows away from the home's supply.
    assert (nodes["battery"]["power"], nodes["battery"]["flow"]) == ("200 W", -1)
    assert (nodes["home"]["power"], nodes["home"]["flow"]) == ("770 W", 1)


def test_home_power_needs_every_kind_of_source_to_report() -> None:
    power = {"sensor.house_power": 850.0, "sensor.pv_power": None}

    nodes = energy_page(energy_sources(PREFERENCES), DAY, power)["energy"]["nodes"]

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

    assert sums == [{"label": "Grid total", "value": "2.5 kWh", "color": "#8fd0ff", "cost": "0.75 EUR"}]


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
        "label": "Net from grid", "value": "-0.5 kWh", "ratio": 0.0, "color": "#c9a6ff",
    }


def test_a_meter_correction_cannot_stretch_or_shrink_the_hour_bars() -> None:
    sources = EnergySources(grid_from=(EnergyMeter("sensor.g"),), solar=(EnergyMeter("sensor.s"),))
    grid = _hours(2.0, 8)
    grid[9] = -1.5
    day = EnergyDay(hours={"sensor.g": grid, "sensor.s": _hours(1.0, 9)})

    hours = energy_page(sources, day, {})["energy"]["hours"]

    assert hours["series"][0]["values"][9] == 0.0
    assert hours["max"] == 2.0 and hours["label"] == "2 kWh"


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

    assert [series["color"] for series in hours["series"]] == ["#ff9800"]


@pytest.mark.parametrize(("value", "expected"), [
    (None, ENERGY_VIEWS), ([], ENERGY_VIEWS), (["today"], ("today",)),
    (["balance", "bogus", "now"], ("now", "balance")), ("now", ENERGY_VIEWS),
])
def test_views_keep_display_order_and_default_to_all(value, expected) -> None:
    assert energy_views(value) == expected


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
    assert set(labels) == {"de", "en", "fr", "it"}
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


def test_a_kind_with_a_source_lacking_its_power_sensor_shows_no_power() -> None:
    preferences = {"energy_sources": [
        {"type": "grid", "stat_energy_from": "sensor.house", "stat_rate": "sensor.house_power"},
        {"type": "solar", "stat_energy_from": "sensor.roof", "stat_rate": "sensor.roof_power"},
        {"type": "solar", "stat_energy_from": "sensor.balcony"},
    ]}
    power = {"sensor.house_power": 300.0, "sensor.roof_power": 500.0}

    nodes = energy_page(energy_sources(preferences), EnergyDay(), power, language="en")["energy"]["nodes"]

    # One inverter's power is not the solar power, and the home's would be too low.
    assert "power" not in nodes["solar"]
    assert "power" not in nodes["home"]
    assert nodes["grid"]["power"] == "300 W"


@pytest.mark.parametrize(("value", "language", "expected"), [
    ("21.5", "de", "21,5"), (21.5, "fr", "21,5"), ("-0.25", "it", "-0,25"), ("21.5", "en", "21.5"),
    (7, "de", "7"), ("1.2.3", "de", "1.2.3"), ("2026-11-15", "de", "2026-11-15"), ("12.5 kW", "de", "12.5 kW"),
])
def test_one_helper_sets_the_decimal_sign_of_the_display_language(value, language, expected) -> None:
    from custom_components.bticino_c300x.dashboard_labels import decimal_text

    assert decimal_text(value, language) == expected
