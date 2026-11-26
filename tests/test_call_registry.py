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
    # Without a ring the view is the current call: the card hangs it up.
    assert registry.current_call_id == "0badc0de-1"

    registry.apply_event("doorbell_pressed", {"call_id": "0badc0de-2", "unit": None})
    assert registry.current_call_id == "0badc0de-2"
    assert registry.current_unit() == "20_2"
    registry.apply_event("call_caller_identified", {"call_id": "0badc0de-2", "unit": "21"})
    # The same identification again changes nothing.
    assert registry.apply_event("call_caller_identified", {"call_id": "0badc0de-2", "unit": "21"}) is None
    assert registry.unit_state("21") == ("ringing", "0badc0de-2")
    assert registry.current_unit() == "21"

    registry.apply_event("call_answered", {"call_id": "0badc0de-2", "answered_by": "ha"})
    assert registry.unit_state("21") == ("answered", "0badc0de-2")
    registry.apply_event("call_ended", {"call_id": "0badc0de-2", "reason": "hangup"})
    assert registry.unit_state("21") == ("viewing", "0badc0de-1")
    assert registry.current_call_id == "0badc0de-1"
    assert registry.call("0badc0de-2").end_reason == "hangup"  # type: ignore[union-attr]

    registry.clear_calls()
    assert registry.unit_state("21") == ("idle", None)


def test_a_later_caller_frame_moves_the_call_to_its_unit() -> None:
    registry = C300XCallRegistry()
    registry.set_units(normalize_outdoor_units(UNITS))
    registry.apply_event("doorbell_pressed", {"call_id": "0badc0de-1", "unit": None, "attribution": "pending"})
    registry.apply_event("call_caller_identified", {
        "call_id": "0badc0de-1", "unit": "20_2", "attribution": "default_fallback"})
    registry.apply_event("call_answered", {"call_id": "0badc0de-1", "answered_by": "station"})
    assert registry.unit_state("20_2") == ("answered", "0badc0de-1")

    # The caller frame came late, after the answer: the call is unit 21's now.
    moved = registry.apply_event("call_caller_identified", {
        "call_id": "0badc0de-1", "unit": "21", "attribution": "caller_frame"})
    assert moved is not None and (moved.unit, moved.attribution, moved.state) == ("21", "caller_frame", "answered")
    assert registry.unit_state("20_2") == ("idle", None)
    assert registry.unit_state("21") == ("answered", "0badc0de-1")
    assert registry.current_unit() == "21"
    # An identification without a unit moves nothing.
    assert registry.apply_event("call_caller_identified", {"call_id": "0badc0de-1", "unit": None}) is None
    assert registry.call("0badc0de-1").unit == "21"  # type: ignore[union-attr]


def test_a_later_press_of_the_same_ring_keeps_the_call() -> None:
    registry = C300XCallRegistry()
    registry.set_units(normalize_outdoor_units(UNITS))
    registry.apply_event("doorbell_pressed", {"call_id": "0badc0de-1", "unit": None, "attribution": "pending"})
    registry.apply_event("call_caller_identified", {"call_id": "0badc0de-1", "unit": "21", "attribution": "caller_frame"})
    registry.apply_event("call_answered", {"call_id": "0badc0de-1", "answered_by": "ha"})

    # The visitor presses again while the call is answered: same call id.
    again = registry.apply_event("doorbell_pressed", {"call_id": "0badc0de-1", "unit": "21", "attribution": "caller_frame"})
    assert again is not None
    assert (again.state, again.unit, again.answered_by) == ("answered", "21", "ha")
    assert list(registry.calls) == ["0badc0de-1"]
    # A press that does not name the unit keeps the known one.
    again = registry.apply_event("doorbell_pressed", {"call_id": "0badc0de-1", "unit": None, "attribution": "pending"})
    assert again is not None and (again.state, again.unit, again.attribution) == ("answered", "21", "caller_frame")


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


def _calls(*calls: dict[str, Any], current: str | None) -> Any:
    return normalize_calls({"boot_id": "0badc0de", "current_call_id": current, "calls": list(calls)})


def _ring(call_id: str, state: str) -> dict[str, Any]:
    return {"call_id": call_id, "kind": "ring", "state": state, "unit": "20_2", "attribution": "caller_frame"}


def test_a_new_ring_resyncs_a_stale_answered_call(monkeypatch: pytest.MonkeyPatch) -> None:
    # The agent does not retry a callback: a lost call_ended left aaaaaaaa-1
    # "answered" in the mirror, which would shadow every later ring.
    monkeypatch.setattr(call_sync, "async_dispatcher_send", lambda *args: None)

    class Api:
        async def async_calls(self) -> Any:
            return _calls(_ring("bbbbbbbb-1", "ringing"), current="bbbbbbbb-1")

    tasks: list[Any] = []
    hass = SimpleNamespace(
        config_entries=_Entries(),
        async_create_background_task=lambda work, _name: tasks.append(work),
    )
    entry = _entry(Api())
    registry = entry.runtime_data.calls
    registry.set_units(normalize_outdoor_units(UNITS))
    registry.set_calls(_calls(_ring("aaaaaaaa-1", "answered"), current="aaaaaaaa-1"))

    call_sync.async_apply_call_event(hass, entry, "doorbell_pressed", {"call_id": "bbbbbbbb-1", "unit": "20_2"})  # type: ignore[arg-type]
    assert tasks, "a ring next to a live call must ask the agent"

    async def run() -> None:
        for work in tasks:
            await work

    asyncio.run(run())
    assert registry.current_call_id == "bbbbbbbb-1"
    assert registry.call("aaaaaaaa-1") is None


def test_a_ring_with_no_other_live_call_asks_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(call_sync, "async_dispatcher_send", lambda *args: None)
    tasks: list[Any] = []
    hass = SimpleNamespace(async_create_background_task=lambda work, _name: tasks.append(work))
    entry = _entry(SimpleNamespace())
    entry.runtime_data.calls.set_units(normalize_outdoor_units(UNITS))
    call_sync.async_apply_call_event(hass, entry, "doorbell_pressed", {"call_id": "bbbbbbbb-1", "unit": "20_2"})  # type: ignore[arg-type]
    assert tasks == []
    assert entry.runtime_data.calls.current_call_id == "bbbbbbbb-1"


def test_an_agent_restart_reads_the_calls_again(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(call_sync, "async_dispatcher_send", lambda *args: None)
    names: list[str] = []

    def schedule(work: Any, name: str) -> None:
        names.append(name)
        work.close()

    hass = SimpleNamespace(async_create_background_task=schedule)
    entry = _entry(SimpleNamespace())
    call_sync.async_apply_call_event(hass, entry, "agent_restarted", {})  # type: ignore[arg-type]
    assert any("calls" in name for name in names), names


@pytest.mark.parametrize("during_setup", [False, True])
def test_units_read_after_a_failed_setup_read_reload_for_the_migration(
    monkeypatch: pytest.MonkeyPatch, during_setup: bool,
) -> None:
    # The setup read of the units failed: the 2.x entry kept its old ids. The
    # next successful read reloads the entry, whose setup then migrates.
    monkeypatch.setattr(call_sync, "async_dispatcher_send", lambda *args: None)

    class Api:
        async def async_outdoor_units(self) -> Any:
            return normalize_outdoor_units(UNITS)

    reloads: list[str] = []
    entries = _Entries()
    entries.async_schedule_reload = reloads.append  # type: ignore[attr-defined]
    hass = SimpleNamespace(config_entries=entries)
    entry = _entry(Api())
    entry.version = 1
    entry.runtime_data.agent_info = {"device_id": "c300x-0123456789ab"}
    assert asyncio.run(call_sync.async_refresh_units(hass, entry, during_setup=during_setup))  # type: ignore[arg-type]
    assert reloads == ([] if during_setup else ["entry-1"])

    # Migrated: a later read reloads nothing.
    entry.version = 2
    entry.data = {**entry.data, "station_id": "c300x-0123456789ab"}
    reloads.clear()
    assert asyncio.run(call_sync.async_refresh_units(hass, entry))  # type: ignore[arg-type]
    assert reloads == []
