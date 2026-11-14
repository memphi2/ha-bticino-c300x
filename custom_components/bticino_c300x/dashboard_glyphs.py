"""Symbols for display tiles, drawn only from the fonts on the C300X.

The display has the fonts Ubuntu Light and DejaVu Sans (firmware 1.7.19). The
symbols below are all in DejaVu Sans, which the display falls back to for a
character Ubuntu Light lacks, as it does for the arrows of a cover. A symbol
that is in neither font would show as an empty box, so nothing outside
``DEVICE_FONT_SYMBOLS`` is used, and no image file is added to the device.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DEVICE_FONT_SYMBOLS = frozenset({
    "↕", "↺", "↻", "⌂", "▣", "▶", "◉", "◐",
    "☀", "★", "☔", "☺", "☼", "☰", "♨", "♪",
    "⚙", "⚠", "⚡",
})

_BY_DOMAIN = {
    "automation": "⚙",
    "button": "◉",
    "climate": "♨",
    "cover": "↕",
    "device_tracker": "☺",
    "fan": "↻",
    "humidifier": "☔",
    "input_boolean": "⚡",
    "input_button": "◉",
    "input_number": "◐",
    "input_select": "☰",
    "light": "☀",
    "lock": "⌂",
    "media_player": "♪",
    "number": "◐",
    "person": "☺",
    "scene": "★",
    "script": "▶",
    "select": "☰",
    "siren": "⚠",
    "switch": "⚡",
    "vacuum": "↺",
    "valve": "↕",
    "water_heater": "♨",
}
_BY_SENSOR_CLASS = {
    "battery": "◐",
    "current": "⚡",
    "energy": "⚡",
    "humidity": "☔",
    "illuminance": "☼",
    "power": "⚡",
    "temperature": "♨",
    "voltage": "⚡",
}
_BY_BINARY_SENSOR_CLASS = {
    "carbon_monoxide": "⚠",
    "door": "▣",
    "garage_door": "▣",
    "gas": "⚠",
    "moisture": "☔",
    "motion": "☺",
    "occupancy": "☺",
    "opening": "▣",
    "plug": "⚡",
    "power": "⚡",
    "presence": "☺",
    "problem": "⚠",
    "safety": "⚠",
    "smoke": "⚠",
    "tamper": "⚠",
    "window": "▣",
}


def dashboard_glyph(entity_id: str, attributes: Mapping[str, Any] | None) -> str:
    """Return the symbol of a tile, or an empty text when it has none."""

    domain = entity_id.split(".", 1)[0]
    device_class = str((attributes or {}).get("device_class") or "").lower()
    if domain == "sensor":
        return _BY_SENSOR_CLASS.get(device_class, "")
    if domain == "binary_sensor":
        return _BY_BINARY_SENSOR_CLASS.get(device_class, "")
    return _BY_DOMAIN.get(domain, "")
