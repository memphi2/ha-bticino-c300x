"""Native summaries stay bounded, read-only and truthful about missing data."""

import json
from types import SimpleNamespace

import pytest

from custom_components.bticino_c300x.dashboard import _dashboard_item_for_entity
from custom_components.bticino_c300x.dashboard_details import entity_details


def snapshot(value="on", **attrs):
    return SimpleNamespace(state=value, attributes=attrs)


@pytest.mark.parametrize("value", [None, "unknown", True, float("nan"), float("inf"), -1, 101])
def test_missing_or_invalid_cover_position_is_never_shown_closed(value):
    details = entity_details("cover.room", snapshot("opening", current_position=value), "Opening", "C")
    assert details["position"] is None
    assert details["value"] == "?"
    assert details["activity"] == "opening"
    json.dumps(details, allow_nan=False)


@pytest.mark.parametrize("value", [0, 25, 100])
def test_read_only_cover_position_does_not_require_set_position_feature(value):
    details = entity_details("cover.room", snapshot("open", current_position=value), "Open", "C")
    assert details["position"] == value
    assert details["value"] == str(value)


@pytest.mark.parametrize("value", [None, "unknown", "unavailable"])
def test_unavailable_details_do_not_leak_old_values(value):
    state = snapshot(value, current_temperature=23, battery_level=60) if value else None
    details = entity_details("climate.room", state, "Offline", "C")
    assert details["value"] == "Offline"
    assert details["fields"] == []


@pytest.mark.parametrize("action,expected", [("idle", "idle"), ("heating", "heating"),
    ("cooling", "cooling"), (None, "unknown"), ([], "unknown"), ("invalid", "unknown")])
def test_climate_activity_is_not_inferred_from_operating_mode(action, expected):
    details = entity_details("climate.room", snapshot("heat", current_temperature=20.5, hvac_action=action), "Heat", "C")
    assert details["value"] == "20.5"
    assert details["activity"] == expected
    assert details["state_label"] == "Heat"


def test_sensor_precision_units_and_attribute_allowlist():
    state = snapshot("1234567.25", unit_of_measurement="kWh", suggested_display_precision=2,
                     battery_level=75, humidity=41.5, illuminance=300,
                     access_token="private", arbitrary={"secret": "private"})
    details = entity_details("sensor.meter", state, "1234567.25 kWh", "C")
    assert details["value"] == "1234567.25"
    assert details["unit"] == "kWh"
    assert details["fields"] == [
        {"label": "battery_level", "value": "75", "unit": "%"},
        {"label": "humidity", "value": "41.5", "unit": "%"},
        {"label": "illuminance", "value": "300", "unit": "lx"},
    ]
    assert "private" not in json.dumps(details)
    assert len(json.dumps(details)) < 800
    state.attributes.pop("suggested_display_precision")
    assert entity_details("sensor.meter", state, "Value", "C")["value"] == "1234567.25"


def test_sensor_rejects_invalid_secondary_values_and_duplicate_main_reading():
    details = entity_details("sensor.humidity", snapshot("40", device_class="humidity", humidity=40,
                             battery_level=101, illuminance=-1), "40 %", "C")
    assert details["fields"] == []


@pytest.mark.parametrize("precision", [None, True, -1, 7, "2"])
def test_invalid_precision_preserves_reported_value(precision):
    details = entity_details("sensor.meter", snapshot("1234567.25", suggested_display_precision=precision), "Value", "C")
    assert details["value"] == "1234567.25"


def test_extreme_sensor_value_is_not_truncated_to_a_different_number():
    details = entity_details("sensor.meter", snapshot("1e100", suggested_display_precision=2), "Value", "C")
    assert float(details["value"]) == 1e100
    assert len(details["value"]) < 60


@pytest.mark.parametrize("entity,value,attrs,expected,unit", [
    ("light.room", "on", {"brightness": 128}, "50", "%"),
    ("light.room", "off", {"brightness": 128}, "Off", ""),
    ("light.room", "on", {"brightness": -1}, "On", ""),
    ("fan.room", "on", {"percentage": 66}, "66", "%"),
    ("fan.room", "off", {"percentage": 66}, "Off", ""),
])
def test_light_and_fan_summaries_preserve_off_and_unknown_levels(entity, value, attrs, expected, unit):
    details = entity_details(entity, snapshot(value, **attrs), value.title(), "C")
    assert (details["value"], details["unit"]) == (expected, unit)


def test_payload_includes_fan_controls_and_read_only_sensor_details():
    states = {
        "fan.room": snapshot(supported_features=63, percentage=50, preset_modes=["sleep"]),
        "binary_sensor.door": snapshot(device_class="door", battery_level=80),
    }
    hass = SimpleNamespace(states=SimpleNamespace(get=states.get))
    fan = _dashboard_item_for_entity(hass, "fan.room", 0)
    assert len(fan["controls"]) == 5
    assert fan["details"]["value"] == "50"
    door = _dashboard_item_for_entity(hass, "binary_sensor.door", 1, language="de")
    assert "controls" not in door
    assert door["details"]["value"] == "Offen"
    assert door["color"] == "#ff6b6b"
