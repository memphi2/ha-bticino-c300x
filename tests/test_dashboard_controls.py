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
