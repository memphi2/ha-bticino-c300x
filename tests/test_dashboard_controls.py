"""Exercise advertised capabilities and the display command allowlist."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.bticino_c300x.dashboard_controls import (
    async_execute_control,
    entity_controls,
    finite_number,
)
from custom_components.bticino_c300x.executor import async_execute_dashboard_action


def state(value="on", **attributes):
    return SimpleNamespace(state=value, attributes=attributes)


def hass_for(snapshot):
    return SimpleNamespace(
        states=SimpleNamespace(get=lambda _: snapshot),
        services=SimpleNamespace(async_call=AsyncMock()),
        bus=SimpleNamespace(async_fire=lambda *_: None),
    )


@pytest.mark.parametrize("value", [None, True, "unknown", "NaN", "inf", "-inf", {}, []])
def test_non_finite_values_never_become_zero(value):
    assert finite_number(value) is None


def test_light_exposes_only_reported_color_capabilities():
    plain = entity_controls("light.a", state(supported_color_modes=["onoff"]))
    assert [item["command"] for item in plain] == ["toggle"]
    rich = entity_controls(
        "light.a",
        state(
            supported_color_modes=["hs", "color_temp"],
            brightness=128,
            hs_color=(32, 80),
            color_temp_kelvin=3000,
            min_color_temp_kelvin=2000,
            max_color_temp_kelvin=6500,
        ),
    )
    assert [item["command"] for item in rich] == [
        "toggle",
        "brightness",
        "color_temp_kelvin",
        "color",
        "hue",
        "saturation",
    ]
    assert rich[1]["value"] == 50


@pytest.mark.parametrize("snapshot", [None, state("unavailable"), state("unknown")])
def test_unavailable_entities_have_no_controls(snapshot):
    assert entity_controls("light.a", snapshot) == []


@pytest.mark.parametrize(
    "features,expected",
    [
        (0, []),
        (1, ["open_cover"]),
        (2, ["close_cover"]),
        (8, ["stop_cover"]),
        (4, ["position"]),
        (128, ["tilt_position"]),
    ],
)
def test_cover_flags_are_respected(features, expected):
    assert [
        item["command"]
        for item in entity_controls(
            "cover.a", state("open", supported_features=features)
        )
    ] == expected


def test_climate_controls_preserve_units_limits_and_step():
    controls = entity_controls(
        "climate.a",
        state(
            "heat",
            supported_features=19,
            temperature=21,
            target_temp_low=19,
            target_temp_high=23,
            min_temp=5,
            max_temp=30,
            target_temp_step=0.5,
            hvac_modes=["off", "heat"],
            preset_modes=["eco"],
            preset_mode="eco",
        ),
        "C",
    )
    assert [item["command"] for item in controls] == [
        "temperature",
        "target_temp_low",
        "target_temp_high",
        "hvac_mode",
        "preset_mode",
    ]
    assert controls[0] == {
        "command": "temperature",
        "kind": "number",
        "value": 21,
        "min": 5,
        "max": 30,
        "step": 0.5,
        "unit": "C",
    }


@pytest.mark.parametrize(
    "attrs",
    [
        {"min": 5, "max": 5},
        {"min": "NaN", "max": 10},
        {"min": 0, "max": 10, "step": 0},
        {"min": 0, "max": 10, "step": "inf"},
    ],
)
def test_invalid_numeric_capabilities_are_hidden(attrs):
    assert entity_controls("number.a", state("3", **attrs)) == []


@pytest.mark.parametrize(
    "entity,snapshot,command,option,service,data",
    [
        ("light.a", state(), "toggle", None, "toggle", {}),
        (
            "light.a",
            state(supported_color_modes=["brightness"]),
            "brightness",
            "0",
            "turn_on",
            {"brightness_pct": 0},
        ),
        (
            "light.a",
            state(
                supported_color_modes=["color_temp"],
                min_color_temp_kelvin=2000,
                max_color_temp_kelvin=6500,
            ),
            "color_temp_kelvin",
            "3000",
            "turn_on",
            {"color_temp_kelvin": 3000},
        ),
        (
            "light.a",
            state(supported_color_modes=["rgb"], hs_color=(20, 80)),
            "hue",
            "100",
            "turn_on",
            {"hs_color": [100, 80]},
        ),
        (
            "light.a",
            state(supported_color_modes=["hs"]),
            "saturation",
            "60",
            "turn_on",
            {"hs_color": [0, 60]},
        ),
        (
            "cover.a",
            state("open", supported_features=1),
            "open_cover",
            None,
            "open_cover",
            {},
        ),
        (
            "cover.a",
            state("open", supported_features=8),
            "stop_cover",
            None,
            "stop_cover",
            {},
        ),
        (
            "cover.a",
            state("open", supported_features=2),
            "close_cover",
            None,
            "close_cover",
            {},
        ),
        (
            "cover.a",
            state("open", supported_features=4),
            "position",
            "70",
            "set_cover_position",
            {"position": 70},
        ),
        (
            "cover.a",
            state("open", supported_features=128),
            "tilt_position",
            "25",
            "set_cover_tilt_position",
            {"tilt_position": 25},
        ),
        (
            "climate.a",
            state(
                "heat", supported_features=1, temperature=21, min_temp=5, max_temp=30
            ),
            "temperature",
            "21.5",
            "set_temperature",
            {"temperature": 21.5},
        ),
        (
            "climate.a",
            state("heat", hvac_modes=["heat", "off"]),
            "hvac_mode",
            "off",
            "set_hvac_mode",
            {"hvac_mode": "off"},
        ),
        (
            "climate.a",
            state("heat", supported_features=16, preset_modes=["eco"]),
            "preset_mode",
            "eco",
            "set_preset_mode",
            {"preset_mode": "eco"},
        ),
        (
            "climate.a",
            state(
                "heat_cool",
                supported_features=2,
                min_temp=5,
                max_temp=30,
                target_temp_low=18,
                target_temp_high=24,
            ),
            "target_temp_low",
            "19",
            "set_temperature",
            {"target_temp_low": 19, "target_temp_high": 24},
        ),
        (
            "number.a",
            state("5", min=0, max=10, step=0.5),
            "value",
            "4.5",
            "set_value",
            {"value": 4.5},
        ),
        (
            "select.a",
            state("a", options=["a", "b"]),
            "option",
            "b",
            "select_option",
            {"option": "b"},
        ),
    ],
)
def test_control_calls_only_the_matching_ha_service(
    entity, snapshot, command, option, service, data
):
    hass = hass_for(snapshot)
    asyncio.run(async_execute_control(hass, entity, command, option))
    hass.services.async_call.assert_awaited_once_with(
        entity.split(".")[0], service, {"entity_id": entity, **data}, blocking=True
    )


@pytest.mark.parametrize(
    "command,value",
    [
        ("position", "NaN"),
        ("position", "inf"),
        ("position", "101"),
        ("position", "-1"),
        ("position", "1.5"),
        ("position", None),
        ("open_cover", "injected"),
        ("turn_on", None),
    ],
)
def test_cover_rejects_invalid_values_and_services(command, value):
    hass = hass_for(state("open", supported_features=5))
    with pytest.raises(ValueError):
        asyncio.run(async_execute_control(hass, "cover.a", command, value))
    hass.services.async_call.assert_not_awaited()


def test_stale_capabilities_unselected_entities_and_invalid_options_fail_closed():
    hass = hass_for(state("unavailable"))
    with pytest.raises(ValueError):
        asyncio.run(async_execute_control(hass, "cover.a", "open_cover", None))
    hass = hass_for(state("a", options=["a", "b"]))
    with pytest.raises(ValueError):
        asyncio.run(async_execute_control(hass, "select.a", "option", "delete"))
    entry = SimpleNamespace(data={}, options={}, entry_id="entry")
    with pytest.raises((ValueError, KeyError)):
        asyncio.run(
            async_execute_dashboard_action(hass, entry, "select.a:option", option="b")
        )
    hass.services.async_call.assert_not_awaited()
    entry.options["dashboard_entities"] = ["select.a"]
    asyncio.run(
        async_execute_dashboard_action(hass, entry, "select.a:option", option="b")
    )
    hass.services.async_call.assert_awaited_once()


@pytest.mark.parametrize("entity,command", [("light.a", "increment"), ("button.a", "next"), ("cover.a", "reboot")])
def test_unrelated_action_suffixes_cannot_fall_back_to_default(entity, command):
    hass = hass_for(state())
    entry = SimpleNamespace(data={}, options={"dashboard_entities": [entity]}, entry_id="entry")
    with pytest.raises(ValueError):
        asyncio.run(async_execute_dashboard_action(hass, entry, entity + ":" + command))
    hass.services.async_call.assert_not_awaited()


@pytest.mark.parametrize("other", [None, 18])
def test_range_temperature_rejects_unknown_or_crossed_other_limit(other):
    hass = hass_for(
        state(
            "heat_cool",
            supported_features=2,
            min_temp=5,
            max_temp=30,
            target_temp_high=other,
        )
    )
    with pytest.raises(ValueError):
        asyncio.run(async_execute_control(hass, "climate.a", "target_temp_low", "19"))
    hass.services.async_call.assert_not_awaited()


@pytest.mark.parametrize("features,commands", [
    (0, []), (1, ["percentage"]),
    (2, ["oscillating"]), (4, ["direction"]),
    (8, ["preset_mode"]), (48, ["toggle"]),
    (63, ["toggle", "percentage", "oscillating", "preset_mode", "direction"]),
])
def test_fan_capabilities_are_independent(features, commands):
    controls = entity_controls("fan.office", state(
        supported_features=features, percentage=66, oscillating=True,
        preset_modes=["auto", "sleep"], preset_mode="auto", direction="forward",
    ))
    assert [control["command"] for control in controls] == commands


@pytest.mark.parametrize("domain,attrs,command,value,service,data", [
    ("fan", {"supported_features": 1}, "percentage", "100", "set_percentage", {"percentage": 100}),
    ("fan", {"supported_features": 1}, "percentage", "0", "set_percentage", {"percentage": 0}),
    ("fan", {"supported_features": 2}, "oscillating", "true", "oscillate", {"oscillating": True}),
    ("fan", {"supported_features": 2}, "oscillating", "false", "oscillate", {"oscillating": False}),
    ("fan", {"supported_features": 4}, "direction", "reverse", "set_direction", {"direction": "reverse"}),
    ("fan", {"supported_features": 8, "preset_modes": ["sleep"]}, "preset_mode", "sleep", "set_preset_mode", {"preset_mode": "sleep"}),
    ("fan", {"supported_features": 48}, "toggle", None, "toggle", {}),
    ("climate", {"supported_features": 8, "fan_modes": ["auto", "quiet"]}, "fan_mode", "quiet", "set_fan_mode", {"fan_mode": "quiet"}),
    ("climate", {"supported_features": 32, "swing_modes": ["off", "vertical"]}, "swing_mode", "vertical", "set_swing_mode", {"swing_mode": "vertical"}),
    ("climate", {"supported_features": 512, "swing_horizontal_modes": ["off", "on"]}, "swing_horizontal_mode", "on", "set_swing_horizontal_mode", {"swing_horizontal_mode": "on"}),
    ("light", {"supported_color_modes": ["rgb"]}, "color", "green", "turn_on", {"hs_color": [120, 100]}),
    ("light", {"supported_color_modes": ["rgbw"]}, "color", "white", "turn_on", {"hs_color": [0, 0]}),
])
def test_new_controls_make_one_explicit_service_call(domain, attrs, command, value, service, data):
    hass = hass_for(state(**attrs))
    asyncio.run(async_execute_control(hass, domain + ".room", command, value))
    hass.services.async_call.assert_awaited_once_with(
        domain, service, {"entity_id": domain + ".room", **data}, blocking=True,
    )


@pytest.mark.parametrize("command,value", [
    ("percentage", "101"), ("percentage", "33.3333333333"), ("percentage", "NaN"),
    ("oscillating", "1"), ("oscillating", "yes"), ("oscillating", None),
    ("direction", "toggle"), ("preset_mode", "unknown"), ("reboot", None),
])
def test_new_fan_controls_reject_invalid_input(command, value):
    hass = hass_for(state(supported_features=15, preset_modes=["auto"]))
    with pytest.raises(ValueError):
        asyncio.run(async_execute_control(hass, "fan.room", command, value))
    hass.services.async_call.assert_not_awaited()


@pytest.mark.parametrize("value,features,allowed", [
    ("on", 16, True), ("on", 32, False), ("off", 16, False), ("off", 32, True),
    ("on", 0, False), ("off", 0, False),
])
def test_fan_toggle_respects_current_state_and_capability(value, features, allowed):
    hass = hass_for(state(value, supported_features=features))
    if allowed:
        asyncio.run(async_execute_control(hass, "fan.room", "toggle", None))
        hass.services.async_call.assert_awaited_once()
    else:
        with pytest.raises(ValueError):
            asyncio.run(async_execute_control(hass, "fan.room", "toggle", None))
        hass.services.async_call.assert_not_awaited()


def test_climate_choices_require_capability_and_reported_options():
    assert entity_controls("climate.room", state(fan_modes=["auto"], swing_modes=["on"])) == []
    assert entity_controls("climate.room", state(supported_features=552)) == []
    hass = hass_for(state(supported_features=8, fan_modes=["auto"]))
    with pytest.raises(ValueError):
        asyncio.run(async_execute_control(hass, "climate.room", "fan_mode", "max"))
    hass.services.async_call.assert_not_awaited()


@pytest.mark.parametrize("minimum,maximum,expected", [
    (2000, 6500, [2700, 4000, 6500]), (3000, 5000, [3000, 4000, 5000]),
    (2000, 2500, [2500]), (7000, 8000, [7000]), (2700.5, 4000.5, [2701, 4000]),
])
def test_white_presets_are_unique_and_within_device_limits(minimum, maximum, expected):
    snapshot = state(supported_color_modes=["color_temp"], min_color_temp_kelvin=minimum,
                     max_color_temp_kelvin=maximum, color_mode="hs")
    control = next(c for c in entity_controls("light.room", snapshot) if c["command"] == "color_temp_kelvin")
    assert [preset["value"] for preset in control["presets"]] == expected
    assert control["active"] is False
    for preset in control["presets"]:
        hass = hass_for(snapshot)
        asyncio.run(async_execute_control(hass, "light.room", "color_temp_kelvin", str(preset["value"])))


@pytest.mark.parametrize("hs,mode,selected", [
    ((120, 100), "hs", "green"), ((359.9, 100), "rgb", "red"),
    ((200, 0), "hs", "white"), ((120, 100), "color_temp", None),
    ((32, 80), "hs", None), (("NaN", 50), "hs", None),
])
def test_palette_selects_only_the_reported_color(hs, mode, selected):
    control = next(c for c in entity_controls("light.room", state(
        supported_color_modes=["hs"], hs_color=hs, color_mode=mode,
    )) if c["command"] == "color")
    assert control["value"] == selected
    assert len(control["options"]) == len(control["swatches"]) == 8


@pytest.mark.parametrize("attrs,value", [
    ({"supported_color_modes": ["hs"]}, "#ff0000"),
    ({"supported_color_modes": ["onoff"]}, "red"),
])
def test_palette_cannot_bypass_color_capabilities(attrs, value):
    hass = hass_for(state(**attrs))
    with pytest.raises(ValueError):
        asyncio.run(async_execute_control(hass, "light.room", "color", value))
    hass.services.async_call.assert_not_awaited()
