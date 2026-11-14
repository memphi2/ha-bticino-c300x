"""Capability-derived display controls and their server-side command validation."""

from __future__ import annotations

import json
import math
from typing import Any

from homeassistant.components.climate.const import ClimateEntityFeature
from homeassistant.components.cover.const import CoverEntityFeature
from homeassistant.components.fan import const as fan_const
from homeassistant.components.light.const import (
    COLOR_MODES_BRIGHTNESS,
    COLOR_MODES_COLOR,
)
from homeassistant.components.media_player.const import MediaPlayerEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

HA_FAN_FEATURE_IN_CONST = hasattr(fan_const, "FanEntityFeature")
if HA_FAN_FEATURE_IN_CONST:
    from homeassistant.components.fan.const import FanEntityFeature
else:
    from homeassistant.components.fan import FanEntityFeature

COLOR_PRESETS = {
    "red": (0, 100, "#ff4545"),
    "yellow": (60, 100, "#ffe04a"),
    "green": (120, 100, "#53d96a"),
    "cyan": (180, 100, "#4ddddd"),
    "blue": (240, 100, "#557dff"),
    "violet": (285, 100, "#bc63ee"),
    "pink": (330, 100, "#f568b0"),
    "white": (0, 0, "#ffffff"),
}
# Plain state strings: the media player state enum deprecates members between
# HA versions, and merely reading a deprecated one is reported.
_MEDIA_PLAYER_OFF_STATES = frozenset({"off", "standby"})
# The display reads the whole dashboard in one response of at most 32 KiB, so
# one list of hundreds of favourites must not push every other tile out. The
# response escapes every non-ASCII character to six bytes, so options are
# measured in the bytes they are sent as. Escaped, an option is never shorter
# than the UTF-8 the agent accepts back, which is at most 1024 bytes.
CHOICE_MAX_OPTIONS = 50
CHOICE_MAX_OPTION_BYTES = 1024
CHOICE_MAX_BYTES = 2048


def _white_presets(control: dict[str, Any] | None, color_mode: Any) -> dict[str, Any] | None:
    if control is None:
        return None
    presets = []
    seen = set()
    low, high = math.ceil(control["min"]), math.floor(control["max"])
    if low >= high:
        return None
    control["min"], control["max"] = low, high
    for label, kelvin in (("warm_white", 2700), ("neutral_white", 4000), ("cool_white", 6500)):
        value = max(low, min(high, kelvin))
        if value not in seen:
            presets.append({"label": label, "value": value})
            seen.add(value)
    control["presets"] = presets
    control["active"] = color_mode is None or color_mode == "color_temp"
    return control


def _color_control(attrs: dict[str, Any]) -> dict[str, Any]:
    selected = None
    hs = attrs.get("hs_color")
    if attrs.get("color_mode") != "color_temp" and isinstance(hs, (list, tuple)) and len(hs) == 2:
        hue, saturation = map(finite_number, hs)
        for name, (h, s, _) in COLOR_PRESETS.items():
            if (hue is not None and saturation is not None and abs(saturation - s) < 1
                    and (s == 0 or abs((hue - h + 180) % 360 - 180) < 1)):
                selected = name
                break
    return {
        "command": "color", "kind": "choice", "value": selected,
        "options": list(COLOR_PRESETS),
        "swatches": [value[2] for value in COLOR_PRESETS.values()],
    }


def finite_number(value: Any) -> float | None:
    """Accept finite numbers only; unknown states never become zero."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except TypeError, ValueError, OverflowError:
        return None
    return number if math.isfinite(number) else None


def _number(
    command: str, value: Any, minimum: Any, maximum: Any, step: Any, unit: str = ""
) -> dict[str, Any] | None:
    low, high, increment = map(finite_number, (minimum, maximum, step))
    if (
        low is None
        or high is None
        or increment is None
        or low >= high
        or increment <= 0
    ):
        return None
    return {
        "command": command,
        "kind": "number",
        "value": finite_number(value),
        "min": low,
        "max": high,
        "step": increment,
        "unit": unit,
    }


def _fan_speed_count(attrs: Any) -> int | None:
    """Return how many speeds the fan has, when that is fewer than 100."""

    step = finite_number(attrs.get("percentage_step"))
    if step is None or not 1 < step <= 100:
        return None
    count = round(100 / step)
    return count if 1 <= count < 100 else None


def _fan_speed_control(attrs: Any, *, off: bool = False) -> dict[str, Any] | None:
    """Offer a fan's speed in percent, on the grid of its own speeds.

    A fan rounds a requested percentage up to its next speed and reports a
    speed truncated (2 of 3 is 66 %), so neither 1 % steps nor the reported
    value step it reliably. With fewer than 100 speeds the step is one speed
    and the value is the current speed on that grid. The step is rounded down
    to six decimals because the display finds the last step as
    floor(100 / step), which the exact quotient misses for some fans.

    A fan that is off stands still, whatever percentage it reports or leaves
    out; without this the display shows an unknown speed.
    """

    percentage = 0 if off else finite_number(attrs.get("percentage"))
    count = _fan_speed_count(attrs)
    if count is None:
        return _number("percentage", percentage, 0, 100, 1, "%")
    step = math.floor(100 / count * 1_000_000) / 1_000_000
    value = None
    if percentage is not None and 0 <= percentage <= 100:
        speed = (
            math.ceil(percentage_to_ranged_value((1, count), percentage))
            if percentage
            else 0
        )
        value = round(speed * step, 6)
    return _number("percentage", value, 0, 100, step, "%")


def _fan_percentage(attrs: Any, value: float) -> int:
    """Return the percentage Home Assistant itself uses for the chosen speed."""

    count = _fan_speed_count(attrs)
    if count is None:
        return int(value)
    speed = round(value * count / 100)
    return ranged_value_to_percentage((1, count), speed) if speed else 0


def choice_options(options: Any) -> list[str]:
    """Return the first options of a list that fit the display's response.

    An option the display could not send back is skipped, not cut, because a
    cut name is not an option Home Assistant accepts; the executor checks a
    command against this same list. The list ends before it would take more
    than CHOICE_MAX_BYTES of the response, separators included.
    """
    if not isinstance(options, (list, tuple)):
        return []
    values: list[str] = []
    size = 0
    for item in options:
        if not isinstance(item, str) or not item:
            continue
        item_size = len(json.dumps(item))
        if item_size > CHOICE_MAX_OPTION_BYTES:
            continue
        size += item_size + 2
        if len(values) == CHOICE_MAX_OPTIONS or size > CHOICE_MAX_BYTES:
            break
        values.append(item)
    return values


def _choice(command: str, value: Any, options: Any) -> dict[str, Any] | None:
    values = choice_options(options)
    if not values:
        return None
    # The display only compares the value with the offered options.
    if not isinstance(value, (str, int, float)) or str(value) not in values:
        value = None
    return {"command": command, "kind": "choice", "value": value, "options": values}


def entity_controls(entity_id: str, state: Any, unit: str = "") -> list[dict[str, Any]]:
    """Describe only controls supported by the current HA entity snapshot."""
    if state is None or state.state in {"unknown", "unavailable"}:
        return []
    domain = entity_id.split(".", 1)[0]
    attrs = state.attributes
    features = int(finite_number(attrs.get("supported_features")) or 0)
    controls: list[dict[str, Any] | None] = []
    if domain == "light":
        controls.append({"command": "toggle", "kind": "button"})
        modes = set(attrs.get("supported_color_modes") or ())
        if modes & COLOR_MODES_BRIGHTNESS:
            # Home Assistant reports no brightness for a light that is off;
            # it is at 0 %, not at an unknown brightness.
            brightness = 0 if state.state == "off" else finite_number(attrs.get("brightness"))
            controls.append(
                _number(
                    "brightness",
                    None if brightness is None else round(brightness * 100 / 255),
                    0,
                    100,
                    1,
                    "%",
                )
            )
        if "color_temp" in modes:
            controls.append(
                _white_presets(_number(
                    "color_temp_kelvin",
                    attrs.get("color_temp_kelvin"),
                    attrs.get("min_color_temp_kelvin"),
                    attrs.get("max_color_temp_kelvin"),
                    1,
                    "K",
                ), attrs.get("color_mode"))
            )
        if modes & COLOR_MODES_COLOR:
            controls.append(_color_control(attrs))
            hs = attrs.get("hs_color")
            hs = hs if isinstance(hs, (list, tuple)) and len(hs) == 2 else (None, None)
            controls.extend(
                (
                    _number("hue", hs[0], 0, 360, 1),
                    _number("saturation", hs[1], 0, 100, 1, "%"),
                )
            )
    elif domain == "cover":
        for command, feature in (
            ("open_cover", CoverEntityFeature.OPEN),
            ("stop_cover", CoverEntityFeature.STOP),
            ("close_cover", CoverEntityFeature.CLOSE),
        ):
            if features & feature:
                controls.append({"command": command, "kind": "button"})
        if features & CoverEntityFeature.SET_POSITION:
            controls.append(
                _number("position", attrs.get("current_position"), 0, 100, 1, "%")
            )
        if features & CoverEntityFeature.SET_TILT_POSITION:
            controls.append(
                _number(
                    "tilt_position", attrs.get("current_tilt_position"), 0, 100, 1, "%"
                )
            )
    elif domain == "climate":
        if features & ClimateEntityFeature.TARGET_TEMPERATURE:
            controls.append(
                _number(
                    "temperature",
                    attrs.get("temperature"),
                    attrs.get("min_temp"),
                    attrs.get("max_temp"),
                    attrs.get("target_temp_step", 0.5),
                    unit,
                )
            )
        if features & ClimateEntityFeature.TARGET_TEMPERATURE_RANGE:
            for key in ("target_temp_low", "target_temp_high"):
                controls.append(
                    _number(
                        key,
                        attrs.get(key),
                        attrs.get("min_temp"),
                        attrs.get("max_temp"),
                        attrs.get("target_temp_step", 0.5),
                        unit,
                    )
                )
        controls.append(_choice("hvac_mode", state.state, attrs.get("hvac_modes")))
        if features & ClimateEntityFeature.PRESET_MODE:
            controls.append(
                _choice(
                    "preset_mode", attrs.get("preset_mode"), attrs.get("preset_modes")
                )
            )
        for command, climate_feature in (
            ("fan_mode", ClimateEntityFeature.FAN_MODE),
            ("swing_mode", ClimateEntityFeature.SWING_MODE),
            ("swing_horizontal_mode", ClimateEntityFeature.SWING_HORIZONTAL_MODE),
        ):
            if features & climate_feature:
                controls.append(_choice(command, attrs.get(command), attrs.get(command + "s")))
    elif domain == "fan":
        toggle_feature = FanEntityFeature.TURN_OFF if state.state == "on" else FanEntityFeature.TURN_ON
        if features & toggle_feature:
            controls.append({"command": "toggle", "kind": "button"})
        if features & FanEntityFeature.SET_SPEED:
            controls.append(_fan_speed_control(attrs, off=state.state == "off"))
        if features & FanEntityFeature.OSCILLATE:
            oscillating = attrs.get("oscillating")
            controls.append({
                "command": "oscillating", "kind": "boolean",
                "value": oscillating if isinstance(oscillating, bool) else None,
            })
        if features & FanEntityFeature.PRESET_MODE:
            controls.append(_choice("preset_mode", attrs.get("preset_mode"), attrs.get("preset_modes")))
        if features & FanEntityFeature.DIRECTION:
            controls.append(_choice("direction", attrs.get("direction"), ["forward", "reverse"]))
    elif domain == "media_player":
        # Each button is offered only with the feature its next step needs.
        powered = state.state not in _MEDIA_PLAYER_OFF_STATES
        power_feature = (
            MediaPlayerEntityFeature.TURN_OFF if powered else MediaPlayerEntityFeature.TURN_ON
        )
        if features & power_feature:
            controls.append({"command": "toggle", "kind": "button"})
        if features & MediaPlayerEntityFeature.PREVIOUS_TRACK:
            controls.append({"command": "media_previous_track", "kind": "button"})
        playing = state.state == "playing"
        play_feature = (
            MediaPlayerEntityFeature.PAUSE if playing else MediaPlayerEntityFeature.PLAY
        )
        if features & play_feature:
            controls.append({
                "command": "media_play_pause", "kind": "button", "playing": playing,
            })
        if features & MediaPlayerEntityFeature.NEXT_TRACK:
            controls.append({"command": "media_next_track", "kind": "button"})
        if features & MediaPlayerEntityFeature.VOLUME_SET:
            volume = finite_number(attrs.get("volume_level"))
            controls.append(_number(
                "volume_level",
                None if volume is None or not 0 <= volume <= 1 else round(volume * 100),
                0, 100, 1, "%",
            ))
        if features & MediaPlayerEntityFeature.VOLUME_MUTE:
            muted = attrs.get("is_volume_muted")
            controls.append({
                "command": "volume_mute", "kind": "boolean",
                "value": muted if isinstance(muted, bool) else None,
            })
        if features & MediaPlayerEntityFeature.SELECT_SOURCE:
            controls.append(_choice("source", attrs.get("source"), attrs.get("source_list")))
        if features & MediaPlayerEntityFeature.SELECT_SOUND_MODE:
            controls.append(
                _choice("sound_mode", attrs.get("sound_mode"), attrs.get("sound_mode_list"))
            )
    elif domain in {"number", "input_number"}:
        controls.append(
            _number(
                "value",
                state.state,
                attrs.get("min"),
                attrs.get("max"),
                attrs.get("step", 1),
                str(attrs.get("unit_of_measurement") or ""),
            )
        )
    elif domain in {"select", "input_select"}:
        controls.append(_choice("option", state.state, attrs.get("options")))
    return [control for control in controls if control is not None]


async def async_execute_control(
    hass: HomeAssistant, entity_id: str, command: str, option: str | None
) -> None:
    """Validate against fresh capabilities, never client-supplied service names."""
    state = hass.states.get(entity_id)
    if state is None:
        raise ValueError("dashboard_entity_unavailable")
    controls = entity_controls(entity_id, state)
    control = next((item for item in controls if item["command"] == command), None)
    if control is None:
        raise ValueError("unsupported_dashboard_control")
    value: Any = option
    if control["kind"] == "number":
        value = finite_number(option)
        if value is None or not control["min"] <= value <= control["max"]:
            raise ValueError("invalid_dashboard_value")
        steps = (value - control["min"]) / control["step"]
        if not math.isclose(steps, round(steps), abs_tol=1e-6):
            raise ValueError("invalid_dashboard_step")
    elif control["kind"] == "choice":
        if option not in control["options"]:
            raise ValueError("invalid_dashboard_option")
    elif control["kind"] == "boolean":
        if option not in {"true", "false"}:
            raise ValueError("invalid_dashboard_value")
        value = option == "true"
    elif option not in (None, ""):
        raise ValueError("invalid_dashboard_value")

    domain = entity_id.split(".", 1)[0]
    data: dict[str, Any] = {"entity_id": entity_id}
    if domain == "light":
        service = "toggle" if command == "toggle" else "turn_on"
        if command == "brightness":
            data["brightness_pct"] = value
        elif command == "color_temp_kelvin":
            data[command] = int(value)
        elif command == "color":
            data["hs_color"] = list(COLOR_PRESETS[value][:2])
        elif command in {"hue", "saturation"}:
            hs = state.attributes.get("hs_color")
            hs = (
                list(hs) if isinstance(hs, (list, tuple)) and len(hs) == 2 else [0, 100]
            )
            hs[0 if command == "hue" else 1] = value
            hs = [finite_number(item) for item in hs]
            if (
                hs[0] is None
                or hs[1] is None
                or not (0 <= hs[0] <= 360 and 0 <= hs[1] <= 100)
            ):
                raise ValueError("invalid_dashboard_color")
            data["hs_color"] = hs
    elif domain == "cover":
        service = {
            "position": "set_cover_position",
            "tilt_position": "set_cover_tilt_position",
        }.get(command, command)
        if command in {"position", "tilt_position"}:
            data[command] = int(value)
    elif domain == "climate":
        service = {
            "hvac_mode": "set_hvac_mode", "preset_mode": "set_preset_mode",
            "fan_mode": "set_fan_mode", "swing_mode": "set_swing_mode",
            "swing_horizontal_mode": "set_swing_horizontal_mode",
        }.get(command, "set_temperature")
        data[command] = value
        if command in {"target_temp_low", "target_temp_high"}:
            other = (
                "target_temp_high"
                if command == "target_temp_low"
                else "target_temp_low"
            )
            data[other] = finite_number(state.attributes.get(other))
            if (
                data[other] is None
                or data["target_temp_low"] > data["target_temp_high"]
            ):
                raise ValueError("invalid_dashboard_temperature_range")
    elif domain == "fan":
        service = {
            "toggle": "toggle", "percentage": "set_percentage",
            "oscillating": "oscillate", "preset_mode": "set_preset_mode",
            "direction": "set_direction",
        }[command]
        if command != "toggle":
            data[command] = (
                _fan_percentage(state.attributes, value)
                if command == "percentage"
                else value
            )
    elif domain == "media_player":
        service = {
            "volume_level": "volume_set", "volume_mute": "volume_mute",
            "source": "select_source", "sound_mode": "select_sound_mode",
        }.get(command, command)
        # Home Assistant's toggle and play/pause services demand both features
        # of their pair; the explicit service for the current state needs only
        # the one feature the control was offered for.
        if command == "toggle":
            service = "turn_on" if state.state in _MEDIA_PLAYER_OFF_STATES else "turn_off"
        elif command == "media_play_pause":
            service = "media_pause" if control.get("playing") else "media_play"
        elif command == "volume_level":
            data["volume_level"] = value / 100
        elif command == "volume_mute":
            data["is_volume_muted"] = value
        elif command in {"source", "sound_mode"}:
            data[command] = value
    elif domain in {"number", "input_number"}:
        service = "set_value"
        data["value"] = value
    else:
        service = "select_option"
        data["option"] = value
    await hass.services.async_call(domain, service, data, blocking=True)
