"""Exercise advertised capabilities and the display command allowlist."""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import math
import re
import runpy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from homeassistant.util.percentage import (
    percentage_to_ordered_list_item,
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from custom_components.bticino_c300x.dashboard import async_dashboard_payload
from custom_components.bticino_c300x.dashboard_controls import (
    CHOICE_MAX_BYTES,
    CHOICE_MAX_OPTION_BYTES,
    CHOICE_MAX_OPTIONS,
    FanEntityFeature,
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


@pytest.mark.parametrize("in_const", [False, True])
def test_fan_feature_import_supports_both_ha_layouts(monkeypatch, in_const):
    from homeassistant.components import fan
    from homeassistant.components.fan import const as fan_const

    monkeypatch.setattr(fan, "FanEntityFeature", FanEntityFeature, raising=False)
    if in_const:
        monkeypatch.setattr(fan_const, "FanEntityFeature", FanEntityFeature, raising=False)
    else:
        monkeypatch.delattr(fan_const, "FanEntityFeature", raising=False)
    module = runpy.run_path(str(Path(__file__).resolve().parents[1] /
                               "custom_components/bticino_c300x/dashboard_controls.py"))
    assert module["HA_FAN_FEATURE_IN_CONST"] is in_const
    assert module["FanEntityFeature"] is FanEntityFeature
    assert module["entity_controls"]("fan.room", state(supported_features=48)) == [
        {"command": "toggle", "kind": "button"},
    ]


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


def _js_round(number):
    return math.floor(number + 0.5)


def _display_adjust(control, direction):
    """The value device_qml's adjustControl sends for a -/+ press."""

    steps = _js_round((control["value"] - control["min"]) / control["step"]) + direction
    last = math.floor((control["max"] - control["min"]) / control["step"])
    steps = max(0, min(last, steps))
    return f"{control['min'] + steps * control['step']:.6f}"


def _fan_after(speed_count, percentage):
    """What a fan with ``speed_count`` speeds reports after set_percentage."""

    speed_range = (1, speed_count)
    if percentage == 0:
        return 0, 0
    speed = math.ceil(percentage_to_ranged_value(speed_range, percentage))
    listed = percentage_to_ordered_list_item(list(range(1, speed_count + 1)), percentage)
    assert speed == listed
    return speed, ranged_value_to_percentage(speed_range, speed)


def test_fan_minus_and_plus_move_exactly_one_speed():
    """A fan rounds a percentage up to its next speed and reports it truncated
    (2 of 3 speeds is 66 %), so 1 % steps and the reported value could not move
    it reliably. For every fan size and speed, a submenu press must reach the
    neighbouring speed, a tile press about ten percent, and HA's resulting
    state must confirm exactly the value the display sent."""

    failures = []

    async def press_everywhere():
        for speed_count in range(1, 101):
            for speed in range(speed_count + 1):
                percentage = (
                    ranged_value_to_percentage((1, speed_count), speed) if speed else 0
                )
                attrs = {"percentage_step": 100 / speed_count}
                snapshot = state("on" if speed else "off", supported_features=1,
                                 percentage=percentage, **attrs)
                control = entity_controls("fan.room", snapshot)[0]
                tile = max(1, _js_round(10 / control["step"]))
                for direction in (1, -1, tile, -tile):
                    sent = _display_adjust(control, direction)
                    hass = hass_for(snapshot)
                    await async_execute_control(hass, "fan.room", "percentage", sent)
                    applied = hass.services.async_call.await_args.args[2]["percentage"]
                    reached, reported = _fan_after(speed_count, applied)
                    jump = abs(direction)
                    want = max(0, min(speed_count, speed + (jump if direction > 0 else -jump)))
                    confirmed = entity_controls("fan.room", state(
                        "on" if reached else "off", supported_features=1,
                        percentage=reported, **attrs,
                    ))[0]["value"]
                    if reached != want or abs(confirmed - float(sent)) >= 0.000001:
                        failures.append((speed_count, speed, direction, sent, reached, confirmed))

    asyncio.run(press_everywhere())
    assert failures == []


@pytest.mark.parametrize("attrs,step,value", [
    ({}, 1.0, 66), ({"percentage_step": 1.0}, 1.0, 66),
    ({"percentage_step": 100 / 3}, 33.333333, 66.666666),
    ({"percentage_step": 100 / 3, "percentage": 100}, 33.333333, 99.999999),
    ({"percentage_step": 100 / 3, "percentage": 0}, 33.333333, 0),
    ({"percentage_step": 100 / 3, "percentage": None}, 33.333333, None),
    ({"percentage_step": 0}, 1.0, 66), ({"percentage_step": 250}, 1.0, 66),
    ({"percentage_step": "fast"}, 1.0, 66), ({"percentage_step": 0.5}, 1.0, 66),
])
def test_fan_speed_step_comes_from_the_fan(attrs, step, value):
    attrs = {"percentage": 66, **attrs}
    control = entity_controls("fan.room", state(supported_features=1, **attrs))[0]
    assert (control["command"], control["step"], control["value"]) == ("percentage", step, value)


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


# MediaPlayerEntityFeature: PAUSE 1, VOLUME_SET 4, VOLUME_MUTE 8, PREVIOUS 16,
# NEXT 32, TURN_ON 128, TURN_OFF 256, SELECT_SOURCE 2048, PLAY 16384,
# SELECT_SOUND_MODE 65536.
@pytest.mark.parametrize("value,features,commands", [
    ("playing", 1 | 16 | 32 | 16384, ["media_previous_track", "media_play_pause", "media_next_track"]),
    ("playing", 1, ["media_play_pause"]),
    ("playing", 16384, []),
    ("paused", 16384, ["media_play_pause"]),
    ("paused", 1, []),
    ("playing", 128 | 256, ["toggle"]),
    ("off", 128, ["toggle"]),
    ("off", 256, []),
    ("standby", 256, []),
    ("idle", 256, ["toggle"]),
    ("playing", 4 | 8, ["volume_level", "volume_mute"]),
    ("playing", 0, []),
])
def test_media_player_exposes_only_reported_features(value, features, commands):
    controls = entity_controls("media_player.room", state(value, supported_features=features))
    assert [control["command"] for control in controls] == commands


def test_media_player_controls_carry_bounded_values():
    controls = {
        control["command"]: control
        for control in entity_controls("media_player.room", state(
            "paused", supported_features=1 | 4 | 8 | 2048 | 16384 | 65536,
            volume_level=0.374, is_volume_muted=False,
            source="Radio", source_list=["Radio", "TV", 7, ""],
            sound_mode="Movie", sound_mode_list=["Movie", "Music"],
        ))
    }
    assert controls["media_play_pause"] == {
        "command": "media_play_pause", "kind": "button", "playing": False,
    }
    assert controls["volume_level"] == {
        "command": "volume_level", "kind": "number", "value": 37,
        "min": 0.0, "max": 100.0, "step": 1.0, "unit": "%",
    }
    assert controls["volume_mute"]["value"] is False
    assert controls["source"]["options"] == ["Radio", "TV"]
    assert controls["sound_mode"]["value"] == "Movie"
    # A missing or impossible volume is unknown, never silent.
    for volume in (None, "loud", 1.5, -0.1):
        unknown = entity_controls(
            "media_player.room", state("playing", supported_features=4, volume_level=volume)
        )
        assert unknown[0]["value"] is None
    # No source list means no source control instead of an empty picker.
    assert entity_controls("media_player.room", state("playing", supported_features=2048)) == []


def test_a_choice_offers_its_first_options_that_fit_the_response():
    """A list of hundreds of favourites is cut to its first options.

    An option larger than the display can carry is skipped, not cut, because a
    cut name is not an option Home Assistant accepts. The executor checks
    against the same list, so an option the display was not offered does not
    run either.
    """

    at_limit = "y" * (CHOICE_MAX_OPTION_BYTES - 2)
    names = ["x" * (CHOICE_MAX_OPTION_BYTES - 1), at_limit] + [
        f"Station {number}" for number in range(400)
    ]
    offered = [at_limit] + [f"Station {number}" for number in range(CHOICE_MAX_OPTIONS - 1)]
    snapshot = state(
        "playing", supported_features=2048 | 65536,
        source="Station 0", source_list=names, sound_mode_list=names,
    )
    controls = {
        control["command"]: control
        for control in entity_controls("media_player.room", snapshot)
    }
    assert controls["source"]["options"] == offered
    assert controls["sound_mode"]["options"] == offered
    assert controls["source"]["value"] == "Station 0"
    select = entity_controls("select.station", state("Station 0", options=names))
    assert select[0]["options"] == offered
    climate = entity_controls(
        "climate.room", state("heat", supported_features=16, preset_modes=names)
    )
    assert next(c for c in climate if c["command"] == "preset_mode")["options"] == offered
    hass = hass_for(snapshot)
    with pytest.raises(ValueError, match="invalid_dashboard_option"):
        asyncio.run(async_execute_control(
            hass, "media_player.room", "source", f"Station {CHOICE_MAX_OPTIONS}",
        ))
    hass.services.async_call.assert_not_awaited()
    asyncio.run(async_execute_control(hass, "media_player.room", "source", at_limit))
    hass.services.async_call.assert_awaited_once_with(
        "media_player", "select_source",
        {"entity_id": "media_player.room", "source": at_limit}, blocking=True,
    )


@pytest.mark.parametrize("name", [
    "Радиостанция номер",
    "ラジオ局の名前です",
    "🎵🎶 Lieblingsplaylist",
])
def test_a_choice_counts_the_bytes_its_options_are_sent_as(name):
    """The display's response sends a character outside ASCII as a six-byte
    escape and an emoji as twelve, so a list is measured as it is sent."""

    names = [f"{name} {number}" for number in range(CHOICE_MAX_OPTIONS)]
    assert len(json.dumps(names)) > CHOICE_MAX_BYTES
    options = entity_controls("select.station", state(names[0], options=names))[0]["options"]
    assert options == names[: len(options)]
    assert len(json.dumps(options)) <= CHOICE_MAX_BYTES
    assert len(json.dumps(names[: len(options) + 1])) > CHOICE_MAX_BYTES


def test_a_choice_sends_its_value_only_when_it_is_offered():
    """The display only compares the value with the offered options, so a
    value no option equals is left out instead of sent at any size."""

    def source(value):
        return entity_controls("media_player.room", state(
            "playing", supported_features=2048, source=value, source_list=["Radio", "TV"],
        ))[0]["value"]

    assert source("TV") == "TV"
    assert source("Radio " * 5000) is None
    assert source({"name": "TV"}) is None
    fan_modes = entity_controls(
        "climate.room", state("heat", supported_features=8, fan_mode=2, fan_modes=["1", "2"]),
    )
    assert next(c for c in fan_modes if c["command"] == "fan_mode")["value"] == 2


def test_a_select_tile_offers_the_first_options_of_its_submenu():
    long_names = [f"{'Станция' * 14} {number}" for number in range(12)]
    snapshot = state(long_names[0], options=long_names, friendly_name="Station")
    submenu = entity_controls("select.station", snapshot)[0]["options"]
    hass = SimpleNamespace(
        states=SimpleNamespace(get={"select.station": snapshot}.get),
        config=SimpleNamespace(language="en"),
    )
    entry = SimpleNamespace(
        entry_id="entry", title="Door", data={},
        options={"device_ui_enabled": True, "dashboard_entities": ["select.station"]},
    )
    payload = asyncio.run(async_dashboard_payload(hass, entry))
    tile = next(item for page in payload["data"]["pages"] for item in page.get("items", []))
    assert len(submenu) < len(long_names)
    assert [option["value"] for option in tile["options"]] == submenu


def _light(number):
    return state(
        "on", friendly_name=f"Light {number}", supported_color_modes=["color_temp", "hs"],
        brightness=128, color_temp_kelvin=3000, min_color_temp_kelvin=2000,
        max_color_temp_kelvin=6500, hs_color=[30, 50], color_mode="hs",
    )


def _player(number, names):
    return state(
        "playing", friendly_name=f"Player {number}", supported_features=2048 | 65536,
        source=names[0], source_list=names, sound_mode=names[0], sound_mode_list=names,
    )


def _dashboard(states, *, notifications=()):
    hass = SimpleNamespace(
        states=SimpleNamespace(get=states.get), config=SimpleNamespace(language="en"),
    )
    store = SimpleNamespace(payload=lambda: list(notifications))
    entry = SimpleNamespace(
        entry_id="entry", title="Door", data={},
        runtime_data=SimpleNamespace(display_notifications=store),
        options={"device_ui_enabled": True, "dashboard_entities": list(states)},
    )
    return asyncio.run(async_dashboard_payload(hass, entry))


def _agent_response_buffer():
    agent = (Path(__file__).resolve().parents[1] / "native_agent/src/http.c").read_text(
        encoding="utf-8"
    )
    return int(re.search(r"#define C300X_LARGE_RESPONSE_SIZE (\d+)", agent).group(1))


def _sent_bytes(payload):
    """Return the body the webhook sends: aiohttp's json_response default."""

    return len(web.json_response({**payload, "revision": "0" * 16}).body)


def _choice_lists(payload):
    for page in payload["data"]["pages"]:
        for item in page.get("items", []):
            for control in item.get("controls", []):
                if control["kind"] == "choice" and "swatches" not in control:
                    yield item["entity_id"], control["command"], control["options"]


_JAPANESE = [f"お気に入りのラジオ局 第{number:02d}番 夜の音楽番組" for number in range(50)]
_CYRILLIC = [f"Любимая радиостанция номер {number:02d} с ночной музыкой и новостями" for number in range(50)]
_ASCII = [f"Favourite radio station number {number:02d} xx" for number in range(50)]
_MESSAGE = {
    "id": "m", "title": "Note", "message": "x" * 1900, "severity": "info", "actions": [],
}


@pytest.mark.parametrize("states,notifications", [
    ({f"media_player.p{n}": _player(n, _JAPANESE) for n in range(4)}, ()),
    ({"media_player.p0": _player(0, _CYRILLIC)} | {f"light.l{n}": _light(n) for n in range(10)}, ()),
    ({f"media_player.p{n}": _player(n, _ASCII) for n in range(10)}, ()),
    ({f"media_player.p{n}": _player(n, _ASCII) for n in range(4)}, [
        {**_MESSAGE, "id": f"m{n}"} for n in range(8)
    ]),
    ({"media_player.p0": _player(0, [f"Favourite radio station {n:04d}" for n in range(2000)])}, ()),
], ids=["4 players, Japanese", "1 player, Cyrillic, 10 lights", "10 players, ASCII",
        "4 players and 8 messages", "2000 favourites"])
def test_choice_lists_never_push_the_dashboard_past_the_display(states, notifications):
    """The display reads the whole dashboard in one response the agent buffers.

    A larger response shows every page as Home Assistant unavailable, so long
    choice lists, alone or added up over several players, are shortened until
    the response fits. A shortened list keeps its first options, all of which
    the executor still accepts.
    """

    payload = _dashboard(states, notifications=notifications)
    assert _sent_bytes(payload) + 1024 < _agent_response_buffer()
    lists = list(_choice_lists(payload))
    assert len(lists) == 2 * sum(entity.startswith("media_player.") for entity in states)
    for entity_id, command, options in lists:
        assert options
        full = next(
            control["options"]
            for control in entity_controls(entity_id, states[entity_id])
            if control["command"] == command
        )
        assert options == full[: len(options)]
        hass = hass_for(states[entity_id])
        asyncio.run(async_execute_control(hass, entity_id, command, options[-1]))


@pytest.mark.parametrize("lights", [23])
def test_shortening_starts_with_the_longest_lists(lights):
    """A thermostat's modes and a select's options are what the user operates.

    Favourites lists are what overflows, so the cap is applied to the longest
    list first and only goes on to a shorter one when the answer still does
    not fit.
    """

    states = {f"media_player.p{n}": _player(n, _ASCII) for n in range(2)}
    states |= {f"light.l{n}": _light(n) for n in range(lights)}
    states["climate.living"] = state(
        "heat", friendly_name="Living", supported_features=1 | 16 | 32,
        hvac_modes=["off", "heat", "cool", "heat_cool", "auto", "dry", "fan_only"],
        preset_modes=["none", "eco", "away", "boost", "comfort", "home", "sleep", "activity"],
        temperature=20, min_temp=5, max_temp=30, target_temp_step=0.5,
        current_temperature=19, preset_mode="none",
    )
    states["select.mode"] = state(
        "Normal", friendly_name="Mode",
        options=["Normal", "Away", "Night", "Vacation", "Guest", "Party", "Movie", "Dinner"],
    )
    payload = _dashboard(states)
    assert _sent_bytes(payload) + 1024 < _agent_response_buffer()
    lengths = {(entity, command): len(options) for entity, command, options in _choice_lists(payload)}
    assert lengths[("climate.living", "hvac_mode")] == 7
    assert lengths[("climate.living", "preset_mode")] == 8
    assert lengths[("select.mode", "option")] == 8
    assert all(
        length < CHOICE_MAX_OPTIONS for (entity, _), length in lengths.items() if entity.startswith("media_player.")
    )
    tile = next(
        item for page in payload["data"]["pages"] for item in page.get("items", [])
        if item.get("entity_id") == "select.mode"
    )
    assert len(tile["options"]) == 8


def test_a_dashboard_that_fits_keeps_its_lists_whole():
    names = [f"Station {number}" for number in range(CHOICE_MAX_OPTIONS)]
    payload = _dashboard({f"media_player.p{n}": _player(n, names) for n in range(2)})
    assert [len(options) for _, _, options in _choice_lists(payload)] == [CHOICE_MAX_OPTIONS] * 4


def test_a_dashboard_too_large_without_lists_is_logged_once(caplog):
    many = {f"light.l{n}": _light(n) for n in range(40)}
    caplog.set_level(logging.WARNING, logger="custom_components.bticino_c300x.dashboard")
    for _ in range(2):
        payload = _dashboard(many)
    assert len(payload["data"]["pages"][1]["items"]) == 40
    warnings = [record for record in caplog.records if "display dashboard" in record.getMessage()]
    assert len(warnings) == 1
    _dashboard({"light.l0": _light(0)})
    caplog.clear()
    _dashboard(many)
    assert [record for record in caplog.records if "display dashboard" in record.getMessage()]


@pytest.mark.parametrize("value,attrs,command,option,service,data", [
    ("playing", {"supported_features": 1 | 16384}, "media_play_pause", None, "media_pause", {}),
    ("paused", {"supported_features": 1 | 16384}, "media_play_pause", None, "media_play", {}),
    ("idle", {"supported_features": 16384}, "media_play_pause", None, "media_play", {}),
    ("playing", {"supported_features": 1}, "media_play_pause", None, "media_pause", {}),
    ("playing", {"supported_features": 16}, "media_previous_track", None, "media_previous_track", {}),
    ("playing", {"supported_features": 32}, "media_next_track", None, "media_next_track", {}),
    ("playing", {"supported_features": 256}, "toggle", None, "turn_off", {}),
    ("idle", {"supported_features": 128 | 256}, "toggle", None, "turn_off", {}),
    ("off", {"supported_features": 128}, "toggle", None, "turn_on", {}),
    ("standby", {"supported_features": 128 | 256}, "toggle", None, "turn_on", {}),
    ("playing", {"supported_features": 4}, "volume_level", "35", "volume_set", {"volume_level": 0.35}),
    ("playing", {"supported_features": 4}, "volume_level", "0", "volume_set", {"volume_level": 0.0}),
    ("playing", {"supported_features": 8}, "volume_mute", "true", "volume_mute", {"is_volume_muted": True}),
    ("playing", {"supported_features": 2048, "source_list": ["Radio", "TV"]}, "source", "TV", "select_source", {"source": "TV"}),
    ("playing", {"supported_features": 65536, "sound_mode_list": ["Movie"]}, "sound_mode", "Movie", "select_sound_mode", {"sound_mode": "Movie"}),
])
def test_media_player_control_makes_one_explicit_service_call(value, attrs, command, option, service, data):
    hass = hass_for(state(value, **attrs))
    asyncio.run(async_execute_control(hass, "media_player.room", command, option))
    hass.services.async_call.assert_awaited_once_with(
        "media_player", service, {"entity_id": "media_player.room", **data}, blocking=True,
    )


# Home Assistant's media_player service registration: a call is accepted only
# when the entity supports every feature of at least one listed set.
HA_MEDIA_SERVICE_FEATURES = {
    "turn_on": [128], "turn_off": [256], "toggle": [128 | 256],
    "media_play": [16384], "media_pause": [1], "media_play_pause": [1 | 16384],
    "media_previous_track": [16], "media_next_track": [32],
}


def test_media_player_buttons_only_call_services_home_assistant_accepts():
    """A button the display offers must never end in ServiceNotSupported.

    Toggle and play/pause need both features of their pair in Home Assistant,
    while a player may report only the one its current state needs.
    """

    pair_features = (1, 16, 32, 128, 256, 16384)
    calls = []

    async def press_every_button():
        for value in ("off", "standby", "idle", "on", "playing", "paused", "buffering"):
            for count in range(len(pair_features) + 1):
                for combo in itertools.combinations(pair_features, count):
                    features = sum(combo)
                    snapshot = state(value, supported_features=features)
                    for control in entity_controls("media_player.room", snapshot):
                        hass = hass_for(snapshot)
                        await async_execute_control(
                            hass, "media_player.room", control["command"], None,
                        )
                        service = hass.services.async_call.await_args.args[1]
                        calls.append((value, features, control["command"], service))

    asyncio.run(press_every_button())
    assert calls
    rejected = [
        call for call in calls
        if not any(call[1] & needed == needed for needed in HA_MEDIA_SERVICE_FEATURES[call[3]])
    ]
    assert rejected == []


@pytest.mark.parametrize("command,option", [
    ("volume_level", "101"), ("volume_level", "-1"), ("volume_level", "12.5"), ("volume_level", "NaN"),
    ("volume_mute", "yes"), ("volume_mute", None),
    ("source", "HDMI 9"), ("sound_mode", "Movie"),
    ("media_next_track", None), ("media_play_pause", "now"),
    ("play_media", "http://example.invalid/a.mp3"), ("media_seek", "10"),
])
def test_media_player_rejects_unsupported_or_invalid_commands(command, option):
    """Only advertised controls run; nothing can play arbitrary media."""

    hass = hass_for(state(
        "playing", supported_features=1 | 4 | 8 | 2048 | 16384, source_list=["Radio", "TV"],
    ))
    with pytest.raises(ValueError):
        asyncio.run(async_execute_control(hass, "media_player.room", command, option))
    hass.services.async_call.assert_not_awaited()


def test_media_player_states_are_compared_as_strings():
    """Reading a deprecated state enum member is reported by Home Assistant.

    That report needs a running instance, so a unit test only trips over it
    when another test happened to create one. The source must not use the enum.
    """

    source = (
        Path(__file__).resolve().parents[1]
        / "custom_components/bticino_c300x/dashboard_controls.py"
    ).read_text(encoding="utf-8")
    assert "MediaPlayerState" not in source
    off = entity_controls("media_player.room", state("standby", supported_features=128 | 256))
    assert [control["command"] for control in off] == ["toggle"]
