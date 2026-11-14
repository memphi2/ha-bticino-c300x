"""Tile symbols come only from the fonts on the device."""

import json
from types import SimpleNamespace

import pytest

from custom_components.bticino_c300x import dashboard_glyphs
from custom_components.bticino_c300x.dashboard import _dashboard_item_for_entity
from custom_components.bticino_c300x.dashboard_glyphs import (
    DEVICE_FONT_SYMBOLS,
    dashboard_glyph,
)


def test_every_symbol_is_in_a_font_of_the_device():
    used = {
        glyph
        for table in (
            dashboard_glyphs._BY_DOMAIN,
            dashboard_glyphs._BY_SENSOR_CLASS,
            dashboard_glyphs._BY_BINARY_SENSOR_CLASS,
        )
        for glyph in table.values()
    }
    assert used
    assert used <= DEVICE_FONT_SYMBOLS
    # One character each, and no emoji: those are in neither font.
    assert all(len(glyph) == 1 and ord(glyph) < 0x10000 for glyph in DEVICE_FONT_SYMBOLS)


@pytest.mark.parametrize(
    ("entity_id", "attributes", "glyph"),
    [
        ("light.room", {}, "☀"),
        ("cover.shade", {}, "↕"),
        ("media_player.kitchen", {}, "♪"),
        ("sensor.outside", {"device_class": "temperature"}, "♨"),
        ("sensor.cpu", {"device_class": "Power"}, "⚡"),
        ("binary_sensor.hall", {"device_class": "motion"}, "☺"),
        ("binary_sensor.front", {"device_class": "door"}, "▣"),
        ("person.anna", {}, "☺"),
        ("lock.front", {}, "⌂"),
        # No class, or one without a symbol, means no symbol.
        ("sensor.note", {}, ""),
        ("sensor.note", {"device_class": "enum"}, ""),
        ("binary_sensor.thing", None, ""),
        ("calendar.family", {}, ""),
    ],
)
def test_a_tile_gets_the_symbol_of_its_type_or_none(entity_id, attributes, glyph):
    assert dashboard_glyph(entity_id, attributes) == glyph


def test_the_symbol_reaches_the_tile_as_its_own_field():
    hass = SimpleNamespace(
        states=SimpleNamespace(
            get=lambda _entity: SimpleNamespace(state="on", attributes={"supported_color_modes": ["onoff"]})
        ),
        config=SimpleNamespace(language="en"),
    )

    item = _dashboard_item_for_entity(hass, "light.room", 10)

    assert item["glyph"] == "☀"
    # The name stays the name; the display puts the two together.
    assert item["name"] == "Room"
    json.dumps(item, allow_nan=False)

    sensor = _dashboard_item_for_entity(
        SimpleNamespace(
            states=SimpleNamespace(get=lambda _entity: SimpleNamespace(state="5", attributes={})),
            config=SimpleNamespace(language="en"),
        ),
        "sensor.note",
        10,
    )
    assert "glyph" not in sensor
