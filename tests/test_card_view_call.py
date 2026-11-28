"""The current call as the media camera tells the card: its view, its unit and that unit's door."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.bticino_c300x import call_sync, camera_units
from custom_components.bticino_c300x._api_calls import normalize_outdoor_units
from custom_components.bticino_c300x.call_registry import (
    SIGNAL_CALLS_CHANGED,
    C300XCallRegistry,
)
from custom_components.bticino_c300x.camera_units import current_call_attributes
from custom_components.bticino_c300x.const import CONF_OUTDOOR_UNITS, CONF_STATION_ID

ROOT = Path(__file__).resolve().parents[1]
UNITS = {"default_unit": "20", "units": [{"id": "20", "where": "20", "name": "Gate", "default": True}]}


def _entry() -> SimpleNamespace:
    registry = C300XCallRegistry()
    registry.set_units(normalize_outdoor_units(UNITS))
    return SimpleNamespace(entry_id="entry-1", data={}, runtime_data=SimpleNamespace(calls=registry))


def test_a_live_view_is_the_cameras_current_call() -> None:
    entry = _entry()
    registry = entry.runtime_data.calls
    registry.apply_event("call_view_started", {"call_id": "0badc0de-5", "unit": "20"})

    attributes = current_call_attributes(None, entry)  # type: ignore[arg-type]
    assert (attributes["call_id"], attributes["call_state"], attributes["call_unit"]) == (
        "0badc0de-5", "viewing", "20")
    # A ring during the view is the current call; the view is again when it ends.
    registry.apply_event("doorbell_pressed", {"call_id": "0badc0de-6", "unit": "20", "attribution": "caller_frame"})
    assert current_call_attributes(None, entry)["call_state"] == "ringing"  # type: ignore[arg-type]
    registry.apply_event("call_ended", {"call_id": "0badc0de-6", "reason": "hangup"})
    assert current_call_attributes(None, entry)["call_id"] == "0badc0de-5"  # type: ignore[arg-type]
    registry.apply_event("call_ended", {"call_id": "0badc0de-5", "reason": "hangup"})
    assert current_call_attributes(None, entry)["call_state"] is None  # type: ignore[arg-type]


def test_the_card_ends_a_view_by_its_call_without_the_stop_button() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    entry = _entry()
    entry.runtime_data.calls.apply_event("call_view_started", {"call_id": "0badc0de-5", "unit": "20"})
    result = subprocess.run(
        [node, "tests/frontend/c300x_view_call_contract.mjs"],
        input=json.dumps({"attributes": current_call_attributes(None, entry)}),  # type: ignore[arg-type]
        capture_output=True, text=True, cwd=ROOT, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


TWO_UNITS = {
    "default_unit": "20",
    "units": [
        {"id": "20", "where": "20", "name": "Gate", "default": True},
        {"id": "21", "where": "21", "name": "Garden"},
    ],
}


def test_the_card_has_no_door_while_the_ringing_unit_is_not_known(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ring of unit 21 is pending for ~300 ms: the default unit's door must not stand in.

    That button sends its own unit id ("20"), which the agent's
    call_unit_pending guard for "current" does not stop.
    """

    registry = C300XCallRegistry()
    registry.set_units(normalize_outdoor_units(TWO_UNITS))
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={CONF_STATION_ID: "c300x-0123456789ab", CONF_OUTDOOR_UNITS: TWO_UNITS},
        runtime_data=SimpleNamespace(calls=registry),
    )
    doors = {
        "c300x-0123456789ab_unit_20_door": "button.gate_door",
        "c300x-0123456789ab_unit_21_door": "button.garden_door",
    }
    entity_registry = SimpleNamespace(
        async_get_entity_id=lambda domain, platform, unique_id: doors.get(unique_id) if domain == "button" else None,
    )
    monkeypatch.setattr(camera_units.er, "async_get", lambda _hass: entity_registry)
    signals: list[tuple[str, str]] = []
    monkeypatch.setattr(call_sync, "async_dispatcher_send", lambda _hass, *args: signals.append(args))
    hass = SimpleNamespace(data={})

    def door() -> Any:
        return current_call_attributes(hass, entry)["door_entity_id"]  # type: ignore[arg-type]

    # No call: the card's door opens the default unit.
    assert door() == "button.gate_door"
    # The ring is pending: no door until the station names the unit.
    call_sync.async_apply_call_event(hass, entry, "doorbell_pressed",  # type: ignore[arg-type]
                                     {"call_id": "0badc0de-1", "unit": None, "attribution": "pending"})
    assert signals == [(SIGNAL_CALLS_CHANGED, "entry-1")]
    assert door() is None
    # Answered before the caller frame: still not known.
    call_sync.async_apply_call_event(hass, entry, "call_answered",  # type: ignore[arg-type]
                                     {"call_id": "0badc0de-1", "answered_by": "ha"})
    assert door() is None
    # The caller frame names unit 21; the camera is told and names its door.
    signals.clear()
    call_sync.async_apply_call_event(hass, entry, "call_caller_identified",  # type: ignore[arg-type]
                                     {"call_id": "0badc0de-1", "unit": "21", "attribution": "caller_frame"})
    assert signals == [(SIGNAL_CALLS_CHANGED, "entry-1")]
    assert door() == "button.garden_door"
    call_sync.async_apply_call_event(hass, entry, "call_ended",  # type: ignore[arg-type]
                                     {"call_id": "0badc0de-1", "reason": "hangup"})
    assert door() == "button.gate_door"
    # No caller frame within 1 s: the default unit stands in, and its door with it.
    call_sync.async_apply_call_event(hass, entry, "doorbell_pressed",  # type: ignore[arg-type]
                                     {"call_id": "0badc0de-2", "unit": None, "attribution": "pending"})
    assert door() is None
    signals.clear()
    call_sync.async_apply_call_event(hass, entry, "call_caller_identified",  # type: ignore[arg-type]
                                     {"call_id": "0badc0de-2", "unit": "20", "attribution": "default_fallback"})
    assert signals == [(SIGNAL_CALLS_CHANGED, "entry-1")]
    assert door() == "button.gate_door"
