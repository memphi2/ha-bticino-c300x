"""Small, read-only display summaries derived from selected HA snapshots."""

from __future__ import annotations

from typing import Any

from .dashboard_controls import finite_number

DETAIL_DOMAINS = frozenset({
    "light", "cover", "climate", "fan", "sensor", "binary_sensor", "media_player",
})
_CLIMATE_ACTIVITIES = frozenset({
    "off", "idle", "heating", "cooling", "drying", "fan", "defrosting", "preheating",
})


def _percentage(value: Any) -> float | None:
    number = finite_number(value)
    return number if number is not None and 0 <= number <= 100 else None


def _display_number(value: Any, precision: Any = None) -> str:
    number = finite_number(value)
    if number is None:
        return "?"
    if isinstance(precision, int) and not isinstance(precision, bool) and 0 <= precision <= 6:
        display = f"{number:.{precision}f}"
    else:
        display = value.strip() if isinstance(value, str) else f"{number:.12g}"
    return display if len(display) <= 60 else f"{number:.6g}"


def entity_details(
    entity_id: str, state: Any, state_label: str, temperature_unit: str,
) -> dict[str, Any]:
    """Expose bounded display values, never arbitrary entity attributes."""
    domain = entity_id.split(".", 1)[0]
    details: dict[str, Any] = {
        "type": domain, "value": state_label, "unit": "", "label": "",
        "state_label": state_label, "fields": [],
    }
    if state is None or state.state in {"unknown", "unavailable"}:
        return details
    attrs = state.attributes
    if domain == "cover":
        position = _percentage(attrs.get("current_position"))
        details.update(
            position=position, value=_display_number(position), unit="%", label="position",
            activity=state.state if state.state in {"opening", "closing", "open", "closed"} else "",
        )
    elif domain == "climate":
        activity = attrs.get("hvac_action")
        details.update(
            value=_display_number(attrs.get("current_temperature")),
            unit=temperature_unit, label="current_temperature",
            activity=activity if isinstance(activity, str) and activity in _CLIMATE_ACTIVITIES else "unknown",
        )
    elif domain in {"light", "fan"}:
        value = (
            finite_number(attrs.get("brightness")) if domain == "light"
            else _percentage(attrs.get("percentage"))
        )
        if value is not None and 0 <= value <= (255 if domain == "light" else 100) and state.state == "on":
            if domain == "light":
                value = round(max(0, min(255, value)) * 100 / 255)
            details.update(value=_display_number(value), unit="%", label="brightness" if domain == "light" else "percentage")
    elif domain == "media_player":
        # Play/pause is confirmed on this; its button comes and goes with the
        # features a player reports in each state.
        details["playing"] = state.state == "playing"
        # What is playing is the reading; without a title the state stands.
        title = attrs.get("media_title")
        title = " ".join(title.split()) if isinstance(title, str) else ""
        if title and state.state in {"playing", "paused", "buffering"}:
            details.update(value=title[:60])
    elif domain in {"sensor", "binary_sensor"}:
        if domain == "sensor" and finite_number(state.state) is not None:
            details.update(
                value=_display_number(state.state, attrs.get("suggested_display_precision")),
                unit=str(attrs.get("unit_of_measurement") or "")[:20],
            )
        for attribute, label, unit, maximum in (
            ("battery_level", "battery_level", "%", 100),
            ("humidity", "humidity", "%", 100),
            ("illuminance", "illuminance", "lx", None),
        ):
            if attrs.get("device_class") == label.removesuffix("_level"):
                continue
            value = finite_number(attrs.get(attribute))
            if value is not None and value >= 0 and (maximum is None or value <= maximum):
                details["fields"].append({"label": label, "value": _display_number(value), "unit": unit})
    return details
