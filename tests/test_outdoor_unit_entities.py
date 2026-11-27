"""Outdoor unit devices and entities, the station ring, and the 2.x migration."""

from __future__ import annotations

# ruff: noqa: E402
import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

pytestmark = pytest.mark.usefixtures("entity_ha_boundary")

from homeassistant.components.event import EventEntity

from custom_components.bticino_c300x import call_sync, identity_migration, unit_entity
from custom_components.bticino_c300x._api_calls import normalize_outdoor_units
from custom_components.bticino_c300x.call_registry import C300XCallRegistry
from custom_components.bticino_c300x.const import (
    CONF_OUTDOOR_UNITS,
    CONF_STATION_ID,
    EVENT_AGENT_EVENT_RECEIVED,
)
from custom_components.bticino_c300x.event import (
    C300XStairLightEventEntity,
    C300XStationRingEventEntity,
    C300XUnitDoorbellEventEntity,
    C300XUnitDoorEventEntity,
)
from custom_components.bticino_c300x.event import async_setup_entry as event_setup
from custom_components.bticino_c300x.identity import (
    media_camera_unique_id,
    station_mac,
    station_unique_id,
    unit_unique_id,
)
from custom_components.bticino_c300x.unit_platforms import (
    C300XUnitCallSensor,
    C300XUnitDoorButton,
)

ONE = {"default_unit": "20", "units": [{"id": "20", "where": "20", "name": "Gate", "default": True}]}
THREE = {"default_unit": "20", "units": [
    {"id": "20", "where": "20", "name": "Gate", "default": True},
    {"id": "21", "where": "21", "name": ""},
    {"id": "22_1", "where": "22#1", "name": "Garage"},
]}


@pytest.fixture(autouse=True)
def quiet_entities(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(EventEntity, "_trigger_event", lambda self, kind, attrs: self.fired.append((kind, attrs)), raising=False)
    monkeypatch.setattr(unit_entity, "async_dispatcher_connect", lambda *_: lambda: None)
    monkeypatch.setattr(unit_entity, "async_register_unit_device", lambda *_: None)
    monkeypatch.setattr(call_sync, "async_dispatcher_send", lambda *_: None)


@dataclass
class _Runtime:
    calls: C300XCallRegistry = field(default_factory=C300XCallRegistry)
    capabilities: dict[str, Any] = field(default_factory=lambda: {"doorbell_events": True, "locks": True})
    connection_state: Any = field(default_factory=lambda: SimpleNamespace(available=True))
    agent_info: dict[str, Any] = field(default_factory=dict)
    api: Any = None


@dataclass
class _Entry:
    entry_id: str = "entry-1"
    title: str = "Door"
    data: dict[str, Any] = field(default_factory=lambda: {CONF_STATION_ID: "c300x-0123456789ab"})
    options: dict[str, Any] = field(default_factory=dict)
    version: int = 2
    runtime_data: _Runtime = field(default_factory=_Runtime)
    unloads: list[Any] = field(default_factory=list)

    def async_on_unload(self, cancel: Any) -> None:
        self.unloads.append(cancel)


def _entry(units: dict[str, Any]) -> _Entry:
    entry = _Entry()
    entry.runtime_data.calls.set_units(normalize_outdoor_units(units))
    return entry


def _added(entity: Any) -> Any:
    """The entity as Home Assistant adds it, listening on a stand-in bus."""

    entity.fired = []
    entity.hass = SimpleNamespace(bus=SimpleNamespace(async_listen=lambda *_: lambda: None))
    asyncio.run(entity.async_added_to_hass())
    entity.hass = None
    return entity


def _setup(entry: _Entry, *, rings_only: bool = True) -> list[Any]:
    added: list[Any] = []
    asyncio.run(event_setup(SimpleNamespace(), entry, added.extend))  # type: ignore[arg-type]
    if rings_only:
        added = [entity for entity in added if isinstance(entity, (C300XStationRingEventEntity, C300XUnitDoorbellEventEntity))]
    return [_added(entity) for entity in added]


def _send(entities: list[Any], entry: _Entry, key: str, scheduled: list[str] | None = None, **data: Any) -> None:
    """The agent event as the webhook puts it on the bus, with the call fields of call_sync."""

    def schedule(work: Any, name: str) -> None:
        work.close()
        if scheduled is not None:
            scheduled.append(name)

    hass = SimpleNamespace(async_create_background_task=schedule)
    fields = call_sync.async_apply_call_event(hass, entry, key, {  # type: ignore[arg-type]
        "call_id": data.get("call_id"), "unit": data.get("unit_id"), "attribution": data.get("attribution"),
    })
    event = SimpleNamespace(data={"entry_id": entry.entry_id, "event_type": key, "event_at": "now",
                                  "call_id": data.get("call_id"), **fields})
    for entity in entities:
        entity._agent_event(event)


def _fired(entities: list[Any]) -> dict[str, list[Any]]:
    return {
        entity.unique_id: [attrs["call_id"] for _kind, attrs in entity.fired]
        for entity in entities
    }


def test_identity_is_the_station_not_the_entry() -> None:
    entry = _Entry()
    assert station_unique_id(entry, "ringer_mute") == "c300x-0123456789ab_ringer_mute"
    assert unit_unique_id(entry, "22_1", "door") == "c300x-0123456789ab_unit_22_1_door"
    assert station_mac(entry) == "01:23:45:67:89:ab"
    # Before the first setup with an API 2 agent the entry id stands in (the 2.x ids).
    legacy = _Entry(data={}, version=1)
    assert station_unique_id(legacy, "doorbell_camera") == "entry-1_doorbell_camera"
    assert media_camera_unique_id(legacy) == "entry-1_doorbell_camera"
    assert station_mac(legacy) is None
    legacy.data = {CONF_STATION_ID: "c300x-0123456789ab", CONF_OUTDOOR_UNITS: ONE}
    assert media_camera_unique_id(legacy) == "c300x-0123456789ab_unit_20_camera"


def test_one_unit_rings_on_the_station_at_once_and_on_the_unit_when_it_is_named() -> None:
    entry = _entry(ONE)
    entities = _setup(entry)
    assert [type(entity) for entity in entities] == [C300XStationRingEventEntity, C300XUnitDoorbellEventEntity]

    _send(entities, entry, "doorbell_pressed", call_id="0badc0de-1", attribution="pending")
    assert _fired(entities) == {
        "c300x-0123456789ab_ring": ["0badc0de-1"],
        "c300x-0123456789ab_unit_20_doorbell": [],
    }
    _send(entities, entry, "call_caller_identified", call_id="0badc0de-1", unit_id="20",
          attribution="caller_frame")
    assert _fired(entities)["c300x-0123456789ab_unit_20_doorbell"] == ["0badc0de-1"]
    # The same identification again does not ring the unit a second time.
    _send(entities, entry, "call_caller_identified", call_id="0badc0de-1", unit_id="20",
          attribution="default_fallback")
    assert _fired(entities)["c300x-0123456789ab_unit_20_doorbell"] == ["0badc0de-1"]


def _bus(entities: list[Any], entry: _Entry, key: str, **data: Any) -> None:
    """A station frame as the webhook puts it on the bus."""

    event = SimpleNamespace(data={
        "event_type": key, "entry_id": entry.entry_id, "unit": data.get("unit"),
        "call_id": data.get("call_id"), "event_at": "now", "data": data,
    })
    for entity in entities:
        entity._agent_event(event)


def test_a_door_frame_fires_its_units_door_and_the_stair_light_fires_on_the_station() -> None:
    entry = _entry(THREE)
    entry.runtime_data.capabilities["stair_light"] = True
    entities = _setup(entry, rings_only=False)
    doors = {entity.unit_id: entity for entity in entities if isinstance(entity, C300XUnitDoorEventEntity)}
    (stair,) = [entity for entity in entities if isinstance(entity, C300XStairLightEventEntity)]
    assert set(doors) == {"20", "21", "22_1"}
    assert doors["21"].unique_id == "c300x-0123456789ab_unit_21_door_event"
    assert doors["21"].event_types == ["opened"] and stair.event_types == ["activated"]
    assert stair.unique_id == "c300x-0123456789ab_stair_light_event"

    # Whatever opened it: in a call, and outside one (from the station or the app).
    _bus(entities, entry, "door_unlock_started", unit="21", call_id="0badc0de-1", address="21")
    _bus(entities, entry, "door_unlock_started", unit="20", call_id=None, address="20")
    # The release of the lock, another station, or a lock of no unit fire nothing.
    _bus(entities, entry, "door_unlock_ended", unit="21", call_id=None, address="21")
    _bus(entities, entry, "door_unlock_started", unit=None, call_id=None, address="4")
    _bus(entities, _Entry(entry_id="entry-2"), "door_unlock_started", unit="21", address="21")
    assert {unit: door.fired for unit, door in doors.items()} == {
        "20": [("opened", {"call_id": None})],
        "21": [("opened", {"call_id": "0badc0de-1"})],
        "22_1": [],
    }
    _bus(entities, entry, "stair_light_activated", address="0")
    _bus(entities, entry, "stair_light_released", address="0")
    assert stair.fired == [("activated", {"address": "0"})]


def test_the_door_and_stair_light_events_follow_the_capabilities() -> None:
    entry = _entry(ONE)
    entry.runtime_data.capabilities = {"doorbell_events": True}
    assert [type(entity) for entity in _setup(entry, rings_only=False)] == [
        C300XStationRingEventEntity, C300XUnitDoorbellEventEntity,
    ]
    entry.runtime_data.capabilities = {"locks": True, "stair_light": True}
    assert [type(entity) for entity in _setup(entry, rings_only=False)] == [
        C300XStairLightEventEntity, C300XUnitDoorEventEntity,
    ]


def test_a_ring_at_a_unit_the_station_had_not_listed_rings_that_unit() -> None:
    # The station listed one unit; a visitor rings at another one.
    entry = _entry(ONE)
    entities = _setup(entry)
    station, gate = entities
    registry = entry.runtime_data.calls

    _send(entities, entry, "doorbell_pressed", call_id="0badc0de-1", attribution="pending")
    scheduled: list[str] = []
    _send(entities, entry, "call_caller_identified", scheduled, call_id="0badc0de-1", unit_id="21",
          attribution="caller_frame")
    # Not the default unit: its visitor is at unit 21.
    assert _fired(entities) == {station.unique_id: ["0badc0de-1"], gate.unique_id: []}
    # The units are read again, also when outdoor_units.changed was lost.
    assert any("units" in name for name in scheduled), scheduled

    # The read adds unit 21; its event fires for the call when its entity is added.
    registry.set_units(normalize_outdoor_units({"default_unit": "20", "units": [
        *ONE["units"], {"id": "21", "where": "21", "name": "Garden"}]}))
    garden = _added(C300XUnitDoorbellEventEntity(entry, registry.units["21"]))  # type: ignore[arg-type]
    assert garden.fired == [("ring", {
        "call_id": "0badc0de-1", "unit": "21", "unit_name": "Garden", "attribution": "caller_frame",
    })]
    # Once only, and the next ring of unit 21 fires at once.
    garden._claim_rings()
    assert len(garden.fired) == 1
    _send([station, gate, garden], entry, "doorbell_pressed", call_id="0badc0de-2", unit_id="21",
          attribution="caller_frame")
    assert [attrs["call_id"] for _kind, attrs in garden.fired] == ["0badc0de-1", "0badc0de-2"]
    assert registry.waiting_rings == {}


def test_with_several_units_the_unit_rings_when_the_caller_is_known() -> None:
    entry = _entry(THREE)
    entities = _setup(entry)
    station, gate, garden, garage = entities

    _send(entities, entry, "doorbell_pressed", call_id="0badc0de-1", attribution="pending")
    assert _fired(entities) == {
        station.unique_id: ["0badc0de-1"], gate.unique_id: [], garden.unique_id: [], garage.unique_id: [],
    }
    _send(entities, entry, "call_caller_identified", call_id="0badc0de-1", unit_id="22_1",
          attribution="caller_frame")
    assert garage.fired[0][1] == {
        "call_id": "0badc0de-1", "unit": "22_1", "unit_name": "Garage", "attribution": "caller_frame",
    }
    # A second unit within a second: the agent opens its call with the unit bound.
    _send(entities, entry, "doorbell_pressed", call_id="0badc0de-2", unit_id="21", attribution="caller_frame")
    assert _fired(entities) == {
        station.unique_id: ["0badc0de-1", "0badc0de-2"], gate.unique_id: [],
        garden.unique_id: ["0badc0de-2"], garage.unique_id: ["0badc0de-1"],
    }
    # Another entry's events and events without a call change nothing.
    for entity in entities:
        entity._agent_event(SimpleNamespace(data={"entry_id": "other", "event_key": "doorbell_pressed",
                                                  "call_id": "0badc0de-3"}))
        entity._agent_event(SimpleNamespace(data={"entry_id": "entry-1", "event_key": "doorbell_pressed"}))
    assert len(station.fired) == 2


def test_a_later_press_of_the_same_ring_rings_again() -> None:
    entry = _entry(THREE)
    entities = _setup(entry)
    station, gate, garden, garage = entities
    _send(entities, entry, "doorbell_pressed", call_id="0badc0de-1", attribution="pending")
    _send(entities, entry, "call_caller_identified", call_id="0badc0de-1", unit_id="21",
          attribution="caller_frame")
    _send(entities, entry, "call_answered", call_id="0badc0de-1")

    # The visitor presses again during the answered call: the agent keeps the call id.
    _send(entities, entry, "doorbell_pressed", call_id="0badc0de-1", unit_id="21", attribution="caller_frame")
    _send(entities, entry, "call_caller_identified", call_id="0badc0de-1", unit_id="21",
          attribution="caller_frame")
    assert _fired(entities) == {
        station.unique_id: ["0badc0de-1", "0badc0de-1"], gate.unique_id: [],
        garden.unique_id: ["0badc0de-1", "0badc0de-1"], garage.unique_id: [],
    }
    assert entry.runtime_data.calls.unit_state("21") == ("answered", "0badc0de-1")


def test_a_late_caller_frame_rings_the_real_unit_after_the_default() -> None:
    entry = _entry(THREE)
    entities = _setup(entry)
    station, gate, garden, garage = entities
    _send(entities, entry, "doorbell_pressed", call_id="0badc0de-1", attribution="pending")
    _send(entities, entry, "call_caller_identified", call_id="0badc0de-1", unit_id="20",
          attribution="default_fallback")
    _send(entities, entry, "call_caller_identified", call_id="0badc0de-1", unit_id="22_1",
          attribution="caller_frame")
    assert _fired(entities) == {
        station.unique_id: ["0badc0de-1"], gate.unique_id: ["0badc0de-1"],
        garden.unique_id: [], garage.unique_id: ["0badc0de-1"],
    }
    assert garage.fired[0][1]["attribution"] == "caller_frame"
    assert entry.runtime_data.calls.unit_state("20") == ("idle", None)
    assert entry.runtime_data.calls.unit_state("22_1") == ("ringing", "0badc0de-1")


def test_call_sensor_follows_the_units_call() -> None:
    entry = _entry(THREE)
    sensor = C300XUnitCallSensor(entry, entry.runtime_data.calls.units["21"])  # type: ignore[arg-type]
    assert (sensor.native_value, sensor.extra_state_attributes["call_id"]) == ("idle", None)
    registry = entry.runtime_data.calls
    registry.apply_event("doorbell_pressed", {"call_id": "0badc0de-1", "unit": "21"})
    assert (sensor.native_value, sensor.extra_state_attributes["call_id"]) == ("ringing", "0badc0de-1")
    registry.apply_event("call_answered", {"call_id": "0badc0de-1", "answered_by": "station"})
    assert sensor.native_value == "answered"
    assert sensor.extra_state_attributes["answered_by"] == "station"
    registry.apply_event("call_ended", {"call_id": "0badc0de-1", "reason": "hangup"})
    assert sensor.native_value == "idle"
    assert sensor.options == ["idle", "ringing", "answered", "viewing"]


def test_door_button_opens_its_own_unit() -> None:
    calls: list[tuple[str, str | None]] = []

    class Api:
        async def async_unlock_outdoor_unit(self, unit_id: str, call_id: str | None = None) -> dict[str, Any]:
            calls.append((unit_id, call_id))
            return {"ok": True}

    entry = _entry(THREE)
    entry.runtime_data.api = Api()
    fired: list[Any] = []
    button = C300XUnitDoorButton(entry, entry.runtime_data.calls.units["22_1"])  # type: ignore[arg-type]
    button.hass = SimpleNamespace(bus=SimpleNamespace(async_fire=lambda *args: fired.append(args)))
    asyncio.run(button.async_press())
    assert calls == [("22_1", None)]
    # The station's frame fires the Door event; no action_received.
    assert fired == []
    assert button.unique_id == "c300x-0123456789ab_unit_22_1_door"
    assert button.device_info["identifiers"] == {("bticino_c300x", "c300x-0123456789ab:unit:22_1")}


def test_units_learned_later_get_their_entities(monkeypatch: pytest.MonkeyPatch) -> None:
    signals: list[Any] = []
    monkeypatch.setattr(unit_entity, "async_dispatcher_connect", lambda _hass, _signal, handler: signals.append(handler) or (lambda: None))
    entry = _entry(ONE)
    added: list[Any] = []
    unit_entity.async_track_outdoor_units(
        SimpleNamespace(), entry, added.extend, lambda unit: [unit.id],  # type: ignore[arg-type]
    )
    assert added == ["20"]
    entry.runtime_data.calls.set_units(normalize_outdoor_units(THREE))
    signals[0]("other-entry")
    assert added == ["20"]
    signals[0]("entry-1")
    signals[0]("entry-1")
    assert added == ["20", "21", "22_1"]


# --- Migration -----------------------------------------------------------------


def test_a_fresh_entry_takes_the_station_id_without_moving_anything() -> None:
    entry = _Entry(data={}, version=2)
    assert identity_migration.identity_migration_needed(entry, "c300x-0123456789ab")  # type: ignore[arg-type]
    assert not identity_migration.identity_migration_needed(entry, None)  # type: ignore[arg-type]
    assert not identity_migration.identity_migration_needed(entry, "../bad")  # type: ignore[arg-type]


def test_a_station_event_belongs_to_its_unit_device_else_to_the_station(monkeypatch: pytest.MonkeyPatch) -> None:
    devices = {
        ("bticino_c300x", "c300x-0123456789ab:unit:21"): "device-21",
        ("bticino_c300x", "c300x-0123456789ab"): "device-station",
    }

    def get_device(*, identifiers: set[tuple[str, str]]) -> Any:
        (identifier,) = identifiers
        return SimpleNamespace(id=devices[identifier]) if identifier in devices else None

    monkeypatch.setattr(unit_entity.dr, "async_get", lambda _hass: SimpleNamespace(async_get_device=get_device))
    entry = _entry(THREE)
    assert unit_entity.event_device_id(None, entry, "21") == "device-21"  # type: ignore[arg-type]
    # A unit that rang for the first time has no device yet.
    assert unit_entity.event_device_id(None, entry, "22_1") == "device-station"  # type: ignore[arg-type]
    assert unit_entity.event_device_id(None, entry, None) == "device-station"  # type: ignore[arg-type]


def test_ring_entities_listen_to_the_agent_event_bus() -> None:
    entry = _entry(ONE)
    station = C300XStationRingEventEntity(entry)  # type: ignore[arg-type]
    listened: list[str] = []
    station.hass = SimpleNamespace(bus=SimpleNamespace(async_listen=lambda kind, _cb: listened.append(kind) or (lambda: None)))
    asyncio.run(station.async_added_to_hass())
    assert EVENT_AGENT_EVENT_RECEIVED in listened


def test_only_a_unit_the_station_no_longer_reports_can_be_deleted() -> None:
    import custom_components.bticino_c300x as integration

    entry = _entry(THREE)

    def device(*identifiers: str) -> Any:
        return SimpleNamespace(identifiers={("bticino_c300x", value) for value in identifiers})

    def removable(item: Any) -> bool:
        return asyncio.run(integration.async_remove_config_entry_device(SimpleNamespace(), entry, item))  # type: ignore[arg-type]

    gone = device("c300x-0123456789ab:unit:23")
    assert removable(gone)
    # The station, a unit it still reports, a unit of another station: they stay.
    assert not removable(device("c300x-0123456789ab"))
    assert not removable(device("c300x-0123456789ab:unit:21"))
    assert not removable(device("c300x-0000000000aa:unit:23"))
    # Not loaded: the units the entry kept decide; none kept, nothing goes.
    entry.runtime_data = None  # type: ignore[assignment]
    entry.data = {**entry.data, CONF_OUTDOOR_UNITS: THREE}
    assert removable(gone) and not removable(device("c300x-0123456789ab:unit:22_1"))
    entry.data = {CONF_STATION_ID: "c300x-0123456789ab"}
    assert not removable(gone)
