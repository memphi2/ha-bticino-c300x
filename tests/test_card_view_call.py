"""An on-demand view is the current call, and the card can end it by that call."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.bticino_c300x._api_calls import normalize_outdoor_units
from custom_components.bticino_c300x.call_registry import C300XCallRegistry
from custom_components.bticino_c300x.camera_units import current_call_attributes

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
