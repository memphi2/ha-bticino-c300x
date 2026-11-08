"""Only changes visible in the selected display projection notify the device."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from homeassistant.core import State

from custom_components.bticino_c300x.dashboard_updates import (
    dashboard_state_event_changes_display,
)


def changed(entity, old, new, overrides=None):
    hass = SimpleNamespace(config=SimpleNamespace(language="de"))
    entry = SimpleNamespace(options={"dashboard_entity_display_overrides": overrides or {}}, data={})
    return dashboard_state_event_changes_display(
        hass, entry, {"entity_id": entity, "old_state": old, "new_state": new},
    )


@pytest.mark.parametrize("entity,state,attrs,change", [
    ("light.room", "on", {"brightness": 128, "supported_color_modes": ["brightness"]}, {"brightness": 180}),
    ("cover.room", "open", {"current_position": 50}, {"current_position": 75}),
    ("climate.room", "heat", {"hvac_action": "idle"}, {"hvac_action": "heating"}),
    ("fan.room", "on", {"percentage": 50}, {"percentage": 70}),
    ("sensor.room", "20.15", {"suggested_display_precision": 1}, {"suggested_display_precision": 2}),
    ("binary_sensor.door", "on", {"device_class": "door"}, {"device_class": "smoke"}),
    ("number.room", "10", {"min": 0, "max": 100, "step": 1}, {"max": 50}),
    ("select.room", "one", {"options": ["one", "two"]}, {"options": ["one", "three"]}),
    ("light.room", "on", {"supported_color_modes": ["onoff"]}, {"supported_color_modes": ["brightness"]}),
    ("sensor.room", "20", {"friendly_name": "Room"}, {"friendly_name": "Kitchen"}),
    ("sensor.room", "20", {"battery_level": 80}, {"battery_level": 70}),
])
def test_display_changes_notify_but_unrelated_attributes_do_not(entity, state, attrs, change):
    before = State(entity, state, attrs)
    assert not changed(entity, before, State(entity, state, {**attrs, "linkquality": 44}))
    assert changed(entity, before, State(entity, state, {**attrs, **change}))


@pytest.mark.parametrize("state", [None, "unknown", "unavailable", "21"])
def test_creation_removal_availability_and_state_are_not_filtered(state):
    entity = "sensor.room"
    before = State(entity, "20")
    after = State(entity, state) if state else None
    assert changed(entity, before, after)
    assert changed(entity, after, before)


def test_configured_timestamp_is_not_filtered():
    entity = "sensor.room"
    now = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
    before = State(entity, "20", last_updated=now)
    after = State(entity, "20", last_updated=now + timedelta(minutes=1))
    assert not changed(entity, before, after)
    assert changed(entity, before, after, {entity: {"secondary": "last_updated"}})


def test_missing_event_snapshots_fail_open():
    assert dashboard_state_event_changes_display(None, None, {"entity_id": "light.room"})
