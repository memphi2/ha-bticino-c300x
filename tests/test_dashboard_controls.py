"""Exercise advertised capabilities and the display command allowlist."""

from __future__ import annotations

import asyncio
import itertools
import json
import math
import re
import runpy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.util.percentage import (
    percentage_to_ordered_list_item,
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from custom_components.bticino_c300x.dashboard import async_dashboard_payload
from custom_components.bticino_c300x.dashboard_controls import (
    CHOICE_MAX_OPTION_LENGTH,
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


def test_a_choice_offers_its_first_options_that_fit_a_button():
    """A list of hundreds of favourites is cut to its first options.

    A name too long for a button is skipped, not cut, because a cut name is not
    an option Home Assistant accepts. The executor checks against the same list,
    so an option the display was not offered does not run either.
    """

    at_limit = "y" * CHOICE_MAX_OPTION_LENGTH
    names = ["x" * (CHOICE_MAX_OPTION_LENGTH + 1), at_limit] + [
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


def test_one_long_source_list_leaves_the_dashboard_readable():
    """The display reads the whole dashboard in one response the agent buffers.

    A larger response shows every page as Home Assistant unavailable, so one
    player with thousands of favourites must stay a small part of it.
    """

    agent = (Path(__file__).resolve().parents[1] / "native_agent/src/http.c").read_text(
        encoding="utf-8"
    )
    buffer = int(re.search(r"#define C300X_LARGE_RESPONSE_SIZE (\d+)", agent).group(1))
    favourites = [f"Favourite radio station {number:04d}" for number in range(2000)]
    player = state(
        "playing", supported_features=2048 | 65536, friendly_name="Living room",
        source=favourites[0], source_list=favourites, sound_mode_list=favourites,
    )
    hass = SimpleNamespace(
        states=SimpleNamespace(get={"media_player.room": player}.get),
        config=SimpleNamespace(language="en"),
    )
    entry = SimpleNamespace(
        entry_id="entry", title="Door", data={},
        options={"device_ui_enabled": True, "dashboard_entities": ["media_player.room"]},
    )
    payload = asyncio.run(async_dashboard_payload(hass, entry))
    items = [item for page in payload["data"]["pages"] for item in page.get("items", [])]
    assert [item["entity_id"] for item in items] == ["media_player.room"]
    assert len(json.dumps(payload)) < buffer // 4


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
