"""Capability-derived display controls and their server-side command validation."""

from __future__ import annotations

import math
from typing import Any

from homeassistant.components.climate.const import ClimateEntityFeature
from homeassistant.components.cover.const import CoverEntityFeature
from homeassistant.components.light.const import (
    COLOR_MODES_BRIGHTNESS,
    COLOR_MODES_COLOR,
)
from homeassistant.core import HomeAssistant


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


def _choice(command: str, value: Any, options: Any) -> dict[str, Any] | None:
    if not isinstance(options, (list, tuple)):
        return None
    values = [item for item in options if isinstance(item, str) and item]
    if not values:
        return None
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
            brightness = finite_number(attrs.get("brightness"))
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
                _number(
                    "color_temp_kelvin",
                    attrs.get("color_temp_kelvin"),
                    attrs.get("min_color_temp_kelvin"),
                    attrs.get("max_color_temp_kelvin"),
                    1,
                    "K",
                )
            )
        if modes & COLOR_MODES_COLOR:
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
        service = (
            "set_hvac_mode"
            if command == "hvac_mode"
            else "set_preset_mode"
            if command == "preset_mode"
            else "set_temperature"
        )
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
    elif domain in {"number", "input_number"}:
        service = "set_value"
        data["value"] = value
    else:
        service = "select_option"
        data["option"] = value
    await hass.services.async_call(domain, service, data, blocking=True)
