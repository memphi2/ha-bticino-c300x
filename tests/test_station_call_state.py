"""The station's own call state: parsed from the agent, kept per entry, shown as a sensor."""

from __future__ import annotations

# ruff: noqa: E402
import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

pytestmark = pytest.mark.usefixtures("entity_ha_boundary")

from homeassistant.components.sensor import SensorDeviceClass

from custom_components.bticino_c300x import call_sync, station_call_state
from custom_components.bticino_c300x._api_calls import normalize_calls
from custom_components.bticino_c300x.call_registry import (
    SIGNAL_CALLS_CHANGED,
    C300XCallRegistry,
)
from custom_components.bticino_c300x.const import CONF_STATION_ID
from custom_components.bticino_c300x.station_call_state import (
    C300XStationCallStateSensor,
)

STATES = [
    "idle", "setup", "ringing", "viewing", "waiting",
    "conversation", "answering_machine", "greeting", "recording",
]


def _entry() -> Any:
    return SimpleNamespace(
        entry_id="entry-1", title="Door", data={CONF_STATION_ID: "c300x-0123456789ab"}, options={},
        runtime_data=SimpleNamespace(
            calls=C300XCallRegistry(), capabilities={"calls": True},
            connection_state=SimpleNamespace(available=True),
        ),
    )


def _apply(entry: Any, key: str, data: dict[str, Any]) -> None:
    hass = SimpleNamespace(async_create_background_task=lambda work, _name: work.close())
    call_sync.async_apply_call_event(hass, entry, key, data)


def test_get_calls_reports_the_station_state_or_null() -> None:
    payload = normalize_calls({"calls": [], "station_state": {"code": 6, "state": "conversation", "age_ms": 1500}})
    assert (payload.station_state.code, payload.station_state.state, payload.station_state.age_ms) == (
        6, "conversation", 1500)
    # Codes 10-12 have no known meaning: the code stays, the state is unknown.
    payload = normalize_calls({"calls": [], "station_state": {"code": 11, "state": None, "age_ms": 0}})
    assert (payload.station_state.code, payload.station_state.state) == (11, None)
    assert normalize_calls({"calls": []}).station_state is None
    assert normalize_calls({"calls": [], "station_state": None}).station_state is None
    for malformed in ({"code": "6", "state": "conversation"}, {"code": True}, {"state": "idle"}, [6]):
        assert normalize_calls({"calls": [], "station_state": malformed}).station_state is None
    assert normalize_calls({"calls": [], "station_state": {"code": 2, "state": "bogus"}}).station_state.state is None


def test_the_sensor_follows_the_seed_the_events_and_an_agent_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[Any, ...]] = []
    monkeypatch.setattr(call_sync, "async_dispatcher_send", lambda _hass, *args: sent.append(args))
    entry = _entry()
    sensor = C300XStationCallStateSensor(entry)
    assert sensor.unique_id == "c300x-0123456789ab_station_call_state"
    assert sensor.device_class == SensorDeviceClass.ENUM
    assert sensor.options == STATES
    assert sensor.translation_key == "station_call_state"
    assert (sensor.native_value, sensor.extra_state_attributes) == (None, {"code": None})

    entry.runtime_data.calls.set_calls(normalize_calls({"calls": [], "station_state": {"code": 0, "state": "idle"}}))
    assert (sensor.native_value, sensor.extra_state_attributes) == ("idle", {"code": 0})

    _apply(entry, "station_call_state", {"code": 2, "state": "ringing"})
    assert sensor.native_value == "ringing"
    assert (SIGNAL_CALLS_CHANGED, "entry-1") in sent
    _apply(entry, "station_call_state", {"code": 7, "state": "answering_machine"})
    assert sensor.native_value == "answering_machine"
    _apply(entry, "station_call_state", {"code": 12, "state": None})
    assert (sensor.native_value, sensor.extra_state_attributes) == (None, {"code": 12})

    _apply(entry, "station_call_state", {"code": 6, "state": "conversation"})
    _apply(entry, "agent_restarted", {})
    assert (sensor.native_value, sensor.extra_state_attributes) == (None, {"code": None})


def test_the_sensor_writes_its_state_when_the_calls_change(monkeypatch: pytest.MonkeyPatch) -> None:
    connected: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        station_call_state, "async_dispatcher_connect",
        lambda _hass, signal, handler: connected.append((signal, handler)) or (lambda: None),
    )
    sensor = C300XStationCallStateSensor(_entry())
    sensor.hass = SimpleNamespace()
    asyncio.run(sensor.async_added_to_hass())
    (signal, handler), = connected
    assert signal == SIGNAL_CALLS_CHANGED
    sensor.wrote_state = False
    handler("entry-2")
    assert sensor.wrote_state is False
    handler("entry-1")
    assert sensor.wrote_state is True


def test_the_station_has_the_sensor_with_the_calls_capability() -> None:
    from custom_components.bticino_c300x import sensor as sensor_platform

    for capabilities, expected in (({"calls": True}, True), ({}, False)):
        entry = _entry()
        entry.runtime_data.capabilities = capabilities
        entry.async_on_unload = lambda _cancel: None
        added: list[Any] = []
        asyncio.run(sensor_platform.async_setup_entry(SimpleNamespace(), entry, added.extend))
        assert any(isinstance(entity, C300XStationCallStateSensor) for entity in added) is expected
