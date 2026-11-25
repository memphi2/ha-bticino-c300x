"""The HA mirror of the agent's outdoor units and calls."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.bticino_c300x import call_sync
from custom_components.bticino_c300x._api_calls import (
    normalize_calls,
    normalize_outdoor_units,
)
from custom_components.bticino_c300x.api_errors import C300XAgentApiConnectionError
from custom_components.bticino_c300x.call_registry import (
    SIGNAL_OUTDOOR_UNITS_CHANGED,
    C300XCallRegistry,
    units_from_stored,
    units_to_stored,
)
from custom_components.bticino_c300x.const import CONF_OUTDOOR_UNITS

UNITS = {
    "default_unit": "20_2",
    "archive": "ok",
    "units": [
        {"id": "20_2", "where": "20#2", "action_where": "20", "lock_where": "20",
         "name": "Gate", "source": "archive", "default": True},
        {"id": "21", "where": "21", "action_where": "21", "lock_where": "21",
         "name": "", "source": "seen", "default": False},
    ],
}


def test_unit_states_follow_ring_view_answer_and_end() -> None:
    registry = C300XCallRegistry()
    registry.set_units(normalize_outdoor_units(UNITS))

    assert registry.unit_state("20_2") == ("idle", None)
    assert registry.current_unit() == "20_2"
    registry.apply_event("call_view_started", {"call_id": "0badc0de-1", "unit": "21"})
    assert registry.unit_state("21") == ("viewing", "0badc0de-1")
    # A view is no call that can be answered.
    assert registry.current_call_id is None

    registry.apply_event("doorbell_pressed", {"call_id": "0badc0de-2", "unit": None})
    assert registry.current_call_id == "0badc0de-2"
    assert registry.current_unit() == "20_2"
    registry.apply_event("call_caller_identified", {"call_id": "0badc0de-2", "unit": "21"})
    # A bound unit is final; a second identification does not move the call.
    assert registry.apply_event("call_caller_identified", {"call_id": "0badc0de-2", "unit": "20_2"}) is None
    assert registry.unit_state("21") == ("ringing", "0badc0de-2")
    assert registry.current_unit() == "21"

    registry.apply_event("call_answered", {"call_id": "0badc0de-2", "answered_by": "ha"})
    assert registry.unit_state("21") == ("answered", "0badc0de-2")
    registry.apply_event("call_ended", {"call_id": "0badc0de-2", "reason": "hangup"})
    assert registry.unit_state("21") == ("viewing", "0badc0de-1")
    assert registry.call("0badc0de-2").end_reason == "hangup"  # type: ignore[union-attr]

    registry.clear_calls()
    assert registry.unit_state("21") == ("idle", None)


def test_events_without_a_valid_call_id_change_nothing() -> None:
    registry = C300XCallRegistry()
    for call_id in (None, "", "../x", "0badc0de", 7):
        assert registry.apply_event("doorbell_pressed", {"call_id": call_id}) is None
    assert registry.calls == {}
    # An event for a call the registry never saw is not invented.
    assert registry.apply_event("call_answered", {"call_id": "0badc0de-9"}) is None


def test_the_registry_keeps_at_most_eight_calls() -> None:
    registry = C300XCallRegistry()
    for sequence in range(1, 12):
        registry.apply_event("doorbell_pressed", {"call_id": f"0badc0de-{sequence}"})
    assert list(registry.calls) == [f"0badc0de-{sequence}" for sequence in range(4, 12)]


def test_set_calls_takes_the_agents_list() -> None:
    registry = C300XCallRegistry()
    registry.set_calls(normalize_calls({
        "boot_id": "0badc0de", "current_call_id": "0badc0de-2",
        "calls": [
            {"call_id": "0badc0de-2", "kind": "ring", "state": "ringing", "unit": "21"},
            {"call_id": "0badc0de-1", "kind": "ring", "state": "ended", "unit": "20_2",
             "end_reason": "superseded"},
        ],
    }))
    assert registry.current_call_id == "0badc0de-2"
    assert registry.unit_state("20_2") == ("idle", None)


def test_stored_units_round_trip() -> None:
    payload = normalize_outdoor_units(UNITS)
    stored = units_to_stored(payload)
    restored = units_from_stored(stored)
    assert restored is not None
    assert (restored.units, restored.default_unit) == (payload.units, payload.default_unit)
    assert units_from_stored(None) is None
    assert units_from_stored({"units": "x"}) is None


class _Entries:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []

    def async_update_entry(self, entry: Any, *, data: dict[str, Any]) -> None:
        self.updates.append(data)
        entry.data = data


def _entry(api: Any) -> SimpleNamespace:
    return SimpleNamespace(
        entry_id="entry-1",
        data={},
        runtime_data=SimpleNamespace(
            api=api, capabilities={"calls": True, "outdoor_units": True}, calls=C300XCallRegistry(),
        ),
    )


def test_refreshed_units_are_kept_in_the_entry_and_announced(monkeypatch: pytest.MonkeyPatch) -> None:
    signals: list[tuple[Any, ...]] = []
    monkeypatch.setattr(call_sync, "async_dispatcher_send", lambda *args: signals.append(args))

    class Api:
        async def async_outdoor_units(self) -> Any:
            return normalize_outdoor_units(UNITS)

    hass = SimpleNamespace(config_entries=_Entries())
    entry = _entry(Api())
    assert asyncio.run(call_sync.async_refresh_units(hass, entry))  # type: ignore[arg-type]
    assert entry.data[CONF_OUTDOOR_UNITS]["default_unit"] == "20_2"
    assert signals == [(hass, SIGNAL_OUTDOOR_UNITS_CHANGED, "entry-1")]

    # The same answer again: no entry write, no signal.
    assert asyncio.run(call_sync.async_refresh_units(hass, entry))  # type: ignore[arg-type]
    assert len(hass.config_entries.updates) == 1 and len(signals) == 1

    # A restart with the station offline starts from the kept units.
    restarted = _entry(Api())
    restarted.data = entry.data
    call_sync.load_stored_units(restarted, restarted.runtime_data.calls)  # type: ignore[arg-type]
    assert list(restarted.runtime_data.calls.units) == ["20_2", "21"]


def test_an_unreachable_agent_keeps_the_known_units(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(call_sync, "async_dispatcher_send", lambda *args: None)

    class Api:
        async def async_outdoor_units(self) -> Any:
            raise C300XAgentApiConnectionError("offline")

    hass = SimpleNamespace(config_entries=_Entries())
    entry = _entry(Api())
    entry.runtime_data.calls.set_units(normalize_outdoor_units(UNITS))
    assert not asyncio.run(call_sync.async_refresh_units(hass, entry))  # type: ignore[arg-type]
    assert list(entry.runtime_data.calls.units) == ["20_2", "21"]
    assert hass.config_entries.updates == []
