"""The door contact of an outdoor unit: a binary sensor fed by the agent's door events."""

from __future__ import annotations

# ruff: noqa: E402
import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

pytestmark = pytest.mark.usefixtures("entity_ha_boundary")

from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass

from custom_components.bticino_c300x import call_sync, unit_entity, unit_platforms
from custom_components.bticino_c300x._api_calls import normalize_outdoor_units
from custom_components.bticino_c300x.binary_sensor import async_setup_entry
from custom_components.bticino_c300x.call_registry import (
    SIGNAL_DOORS_CHANGED,
    SIGNAL_OUTDOOR_UNITS_CHANGED,
    C300XCallRegistry,
)
from custom_components.bticino_c300x.const import CONF_STATION_ID
from custom_components.bticino_c300x.identity import unit_unique_id
from custom_components.bticino_c300x.unit_platforms import (
    C300XUnitDoorContactBinarySensor,
)

CLOSED = {"state": "closed", "age_ms": 4000}


def _units(door_20: Any = CLOSED, door_21: Any = None) -> Any:
    return normalize_outdoor_units({"default_unit": "20", "units": [
        {"id": "20", "where": "20", "name": "Gate", "default": True, "door": door_20},
        {"id": "21", "where": "21", "name": "Garden", "door": door_21},
    ]})


@dataclass
class _Runtime:
    calls: C300XCallRegistry = field(default_factory=C300XCallRegistry)
    capabilities: dict[str, Any] = field(default_factory=lambda: {"outdoor_units": True, "calls": True})
    connection_state: Any = field(default_factory=lambda: SimpleNamespace(available=True))
    api: Any = None


@dataclass
class _Entry:
    entry_id: str = "entry-1"
    title: str = "Door"
    data: dict[str, Any] = field(default_factory=lambda: {CONF_STATION_ID: "c300x-0123456789ab"})
    options: dict[str, Any] = field(default_factory=dict)
    runtime_data: _Runtime = field(default_factory=_Runtime)
    unloads: list[Any] = field(default_factory=list)

    def async_on_unload(self, cancel: Any) -> None:
        self.unloads.append(cancel)


@pytest.fixture
def signals(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Dispatcher stand-ins: what was connected and what was sent."""

    seen: dict[str, list[Any]] = {"connected": [], "sent": []}

    def connect(_hass: Any, signal: str, handler: Any) -> Any:
        seen["connected"].append((signal, handler))
        return lambda: None

    monkeypatch.setattr(unit_entity, "async_dispatcher_connect", connect)
    monkeypatch.setattr(unit_platforms, "async_dispatcher_connect", connect)
    monkeypatch.setattr(unit_entity, "async_register_unit_device", lambda *_: None)
    monkeypatch.setattr(call_sync, "async_dispatcher_send", lambda _hass, *args: seen["sent"].append(args))
    return seen


def _setup(entry: _Entry) -> list[Any]:
    added: list[Any] = []
    asyncio.run(async_setup_entry(SimpleNamespace(), entry, added.extend))  # type: ignore[arg-type]
    return added


def _apply(entry: _Entry, key: str, data: dict[str, Any], scheduled: list[str] | None = None) -> None:
    def schedule(work: Any, name: str) -> None:
        work.close()
        if scheduled is not None:
            scheduled.append(name)

    hass = SimpleNamespace(async_create_background_task=schedule)
    call_sync.async_apply_call_event(hass, entry, key, data)  # type: ignore[arg-type]


def test_only_a_unit_with_a_door_contact_gets_the_sensor_on_its_device(signals) -> None:
    entry = _Entry()
    entry.runtime_data.calls.set_units(_units())

    sensors = [entity for entity in _setup(entry) if isinstance(entity, C300XUnitDoorContactBinarySensor)]

    assert [sensor.unit_id for sensor in sensors] == ["20"]
    sensor = sensors[0]
    assert sensor.unique_id == unit_unique_id(entry, "20", "door_contact")
    assert sensor.device_info["identifiers"] == {("bticino_c300x", "c300x-0123456789ab:unit:20")}
    assert sensor.device_class == BinarySensorDeviceClass.DOOR
    assert sensor.translation_key == "door_contact"
    assert sensor.is_on is False


def test_a_unit_whose_contact_appears_later_gets_its_sensor_then(signals) -> None:
    entry = _Entry()
    entry.runtime_data.calls.set_units(_units(door_20=None))
    added = _setup(entry)
    assert not [entity for entity in added if isinstance(entity, C300XUnitDoorContactBinarySensor)]

    # outdoor_units.changed after the unit's first door frame: the tracker adds its sensor once.
    entry.runtime_data.calls.set_units(_units(door_20=None, door_21={"state": "open", "age_ms": 0}))
    handler, = [handler for signal, handler in signals["connected"] if signal == SIGNAL_OUTDOOR_UNITS_CHANGED]
    handler(entry.entry_id)
    handler(entry.entry_id)

    sensors = [entity for entity in added if isinstance(entity, C300XUnitDoorContactBinarySensor)]
    assert [sensor.unit_id for sensor in sensors] == ["21"]
    assert sensors[0].is_on is True


def test_door_events_set_the_state_and_an_agent_restart_makes_it_unknown(signals) -> None:
    entry = _Entry()
    entry.runtime_data.calls.set_units(_units())
    sensor, = [entity for entity in _setup(entry) if isinstance(entity, C300XUnitDoorContactBinarySensor)]
    sensor.hass = SimpleNamespace()
    asyncio.run(sensor.async_added_to_hass())
    changed = [handler for signal, handler in signals["connected"] if signal == SIGNAL_DOORS_CHANGED]
    assert len(changed) == 1

    _apply(entry, "door_opened", {"unit": "20", "where": "20", "raw": "*8*66*20##"})
    assert sensor.is_on is True
    assert (SIGNAL_DOORS_CHANGED, "entry-1") in signals["sent"]
    sensor.wrote_state = False
    changed[0]("entry-1")
    assert sensor.wrote_state is True
    sensor.wrote_state = False
    changed[0]("entry-2")
    assert sensor.wrote_state is False

    _apply(entry, "door_closed", {"unit": "20", "where": "20", "raw": "*8*65*20##"})
    assert sensor.is_on is False

    signals["sent"].clear()
    _apply(entry, "agent_restarted", {}, scheduled=[])
    assert sensor.is_on is None
    assert (SIGNAL_DOORS_CHANGED, "entry-1") in signals["sent"]


def test_a_door_frame_of_a_unit_without_a_known_contact_reads_the_units_again(signals) -> None:
    entry = _Entry()
    entry.runtime_data.calls.set_units(_units())
    scheduled: list[str] = []

    _apply(entry, "door_opened", {"unit": "21", "where": "21", "raw": "*8*66*21##"}, scheduled)
    _apply(entry, "door_opened", {"unit": "23", "where": "23", "raw": "*8*66*23##"}, scheduled)

    assert scheduled == ["bticino_c300x_units_entry-1"] * 2
    assert entry.runtime_data.calls.unit("21").door is None
    # A repeated frame of a known contact changes nothing and reads nothing.
    _apply(entry, "door_closed", {"unit": "20", "where": "20", "raw": "*8*65*20##"}, scheduled)
    assert scheduled == ["bticino_c300x_units_entry-1"] * 2


def test_a_refresh_that_only_changes_a_door_state_updates_the_sensors_not_the_units(signals) -> None:
    entry = _Entry()
    entry.runtime_data.calls.set_units(_units())

    class Api:
        async def async_outdoor_units(self) -> Any:
            return _units(door_20={"state": "open", "age_ms": 10})

    entry.runtime_data.api = Api()
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=lambda *_a, **_k: None))

    assert asyncio.run(call_sync.async_refresh_units(hass, entry, during_setup=True)) is True  # type: ignore[arg-type]

    assert entry.runtime_data.calls.unit("20").door.state == "open"
    assert signals["sent"] == [(SIGNAL_DOORS_CHANGED, "entry-1")]
