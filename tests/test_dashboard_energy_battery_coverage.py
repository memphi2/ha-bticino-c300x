"""Battery coverage belongs to sources, not independent meter counts."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.bticino_c300x.dashboard_energy import (
    EnergyDay,
    energy_page,
    energy_sources,
    source_power_watts,
)
from custom_components.bticino_c300x.dashboard_energy_power import (
    PowerHistory,
    power_history_payload,
)


def battery(name, direction, power=None):
    source = {"type": "battery"}
    if direction in ("from", "both"):
        source["stat_energy_from"] = f"sensor.{name}_discharge"
    if direction in ("to", "both"):
        source["stat_energy_to"] = f"sensor.{name}_charge"
    if power:
        source["stat_rate"] = power
    return source


@pytest.mark.parametrize("first", ["from", "to", "both"])
@pytest.mark.parametrize("second", ["from", "to", "both"])
@pytest.mark.parametrize("coverage", ["unconfigured", "unavailable", "complete", "shared"])
def test_all_battery_sources_need_power_for_live_and_history(first, second, coverage):
    second_sensor = None if coverage == "unconfigured" else (
        "sensor.a_power" if coverage == "shared" else "sensor.b_power"
    )
    sources = energy_sources({"energy_sources": [
        {"type": "grid", "stat_energy_from": "sensor.grid", "stat_rate": "sensor.grid_power"},
        battery("a", first, "sensor.a_power"), battery("b", second, second_sensor),
    ]})
    readings = {"sensor.grid_power": 1000.0, "sensor.a_power": 500.0,
                "sensor.b_power": None if coverage == "unavailable" else -100.0}
    expected = {"complete": 400.0, "shared": 500.0}.get(coverage)
    aggregate = source_power_watts(sources, readings)
    assert aggregate["battery"] == expected
    assert aggregate["home"] == (None if expected is None else 1000 + expected)
    page = energy_page(sources, EnergyDay(), readings, views=["now"])
    nodes = page["energy"]["nodes"]
    assert ("power" in nodes["battery"]) is (expected is not None)
    assert ("power" in nodes["home"]) is (expected is not None)
    assert nodes["grid"]["power"] == "1 kW"

    start = datetime(2026, 11, 15, tzinfo=UTC)
    history = PowerHistory(start, start + timedelta(days=1), {
        entity: (readings[entity],) for entity in sources.power_entities
    })
    payload = power_history_payload(sources, history, "en")
    series = {item["id"]: item for item in payload["series"]}
    assert ("battery" in series) is (expected is not None)
    assert ("home" in series) is (expected is not None)
    if expected is not None:
        axis = payload["axis"]
        for key, value in (("battery", expected), ("home", 1000 + expected)):
            actual = series[key]["points"][0] * (axis["max"] - axis["min"]) + axis["min"]
            assert actual == pytest.approx(value, abs=0.03)


def test_empty_battery_source_does_not_require_a_power_sensor():
    sources = energy_sources({"energy_sources": [
        battery("a", "both", "sensor.power"), {"type": "battery"},
    ]})
    assert source_power_watts(sources, {"sensor.power": 500}) == {
        "battery": 500, "home": 500,
    }
