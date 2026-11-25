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

from custom_components.bticino_c300x import identity_migration, unit_entity
from custom_components.bticino_c300x._api_calls import normalize_outdoor_units
from custom_components.bticino_c300x.call_registry import C300XCallRegistry
from custom_components.bticino_c300x.const import (
    CONF_OUTDOOR_UNITS,
    CONF_STATION_ID,
    EVENT_AGENT_EVENT_RECEIVED,
)
from custom_components.bticino_c300x.event import (
    C300XStationRingEventEntity,
    C300XUnitDoorbellEventEntity,
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


def _setup(entry: _Entry) -> list[Any]:
    added: list[Any] = []
    asyncio.run(event_setup(SimpleNamespace(), entry, added.extend))  # type: ignore[arg-type]
    for entity in added:
        entity.fired = []
        entity.hass = None
    return added


def _send(entities: list[Any], entry: _Entry, key: str, **data: Any) -> None:
    registry = entry.runtime_data.calls
    registry.apply_event(key, {"call_id": data.get("call_id"), "unit": data.get("unit_id"),
                               "attribution": data.get("attribution")})
    call = registry.call(data.get("call_id"))
    event = SimpleNamespace(data={
        "entry_id": entry.entry_id, "event_key": key, "event_at": "now",
        "call_id": data.get("call_id"),
        "unit_id": call.unit if call is not None else data.get("unit_id"),
    })
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


def test_one_unit_rings_at_once_on_station_and_unit() -> None:
    entry = _entry(ONE)
    entities = _setup(entry)
    assert [type(entity) for entity in entities] == [C300XStationRingEventEntity, C300XUnitDoorbellEventEntity]

    _send(entities, entry, "doorbell_pressed", call_id="0badc0de-1")
    assert _fired(entities) == {
        "c300x-0123456789ab_ring": ["0badc0de-1"],
        "c300x-0123456789ab_unit_20_doorbell": ["0badc0de-1"],
    }
    # The caller frame that follows does not ring the unit a second time.
    _send(entities, entry, "call_caller_identified", call_id="0badc0de-1", unit_id="20")
    assert _fired(entities)["c300x-0123456789ab_unit_20_doorbell"] == ["0badc0de-1"]


def test_with_several_units_the_unit_rings_when_the_caller_is_known() -> None:
    entry = _entry(THREE)
    entities = _setup(entry)
    station, gate, garden, garage = entities

    _send(entities, entry, "doorbell_pressed", call_id="0badc0de-1")
    assert _fired(entities) == {
        station.unique_id: ["0badc0de-1"], gate.unique_id: [], garden.unique_id: [], garage.unique_id: [],
    }
    _send(entities, entry, "call_caller_identified", call_id="0badc0de-1", unit_id="22_1",
          attribution="caller_frame")
    assert garage.fired[0][1] == {
        "call_id": "0badc0de-1", "unit": "22_1", "unit_name": "Garage", "attribution": "caller_frame",
    }
    # A second unit within a second: the agent opens its call with the unit bound.
    _send(entities, entry, "doorbell_pressed", call_id="0badc0de-2", unit_id="21")
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
    registry.apply_event("call_ended", {"call_id": "0badc0de-1", "reason": "hangup_frame"})
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
    assert fired[0][1]["unit_id"] == "22_1"
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


class _Registry:
    """Entity and device registry stand-ins recording what the migration does."""

    def __init__(self, unique_ids: list[tuple[str, str]]) -> None:
        self.entities = {
            f"{domain}.e{index}": SimpleNamespace(entity_id=f"{domain}.e{index}", domain=domain,
                                                  platform="bticino_c300x", unique_id=unique_id, device_id="station")
            for index, (domain, unique_id) in enumerate(unique_ids)
        }
        self.devices: dict[str, SimpleNamespace] = {
            "station": SimpleNamespace(id="station", identifiers={("bticino_c300x", "entry-1")}),
        }
        self.removed: list[str] = []

    # entity registry
    def async_remove(self, entity_id: str) -> None:
        self.removed.append(entity_id)
        del self.entities[entity_id]

    def async_get_entity_id(self, domain: str, platform: str, unique_id: str) -> str | None:
        return next((e.entity_id for e in self.entities.values()
                     if (e.domain, e.unique_id) == (domain, unique_id)), None)

    def async_update_entity(self, entity_id: str, *, new_unique_id: str, device_id: str | None = None) -> None:
        self.entities[entity_id].unique_id = new_unique_id
        if device_id is not None:
            self.entities[entity_id].device_id = device_id

    # device registry
    def async_get_device(self, *, identifiers: set[tuple[str, str]]) -> Any:
        return next((d for d in self.devices.values() if d.identifiers & identifiers), None)

    def async_update_device(self, device_id: str, *, new_identifiers: set[tuple[str, str]]) -> None:
        self.devices[device_id].identifiers = new_identifiers


def test_migration_moves_2x_entities_and_keeps_their_entity_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _Registry([
        ("camera", "entry-1_doorbell_camera"),
        ("event", "entry-1_doorbell_event"),
        ("button", "entry-1_door_unlock"),
        ("sensor", "entry-1_doorbell_state"),
        ("event", "entry-1_agent_event"),
        ("switch", "entry-1_ringer_mute"),
        ("sensor", "other-entry_device_cpu"),
    ])
    monkeypatch.setattr(identity_migration.er, "async_get", lambda _hass: registry)
    monkeypatch.setattr(identity_migration.dr, "async_get", lambda _hass: registry)
    monkeypatch.setattr(identity_migration.er, "async_entries_for_config_entry",
                        lambda reg, _entry_id: list(reg.entities.values()))

    def register(_hass: Any, entry: Any, unit: Any) -> None:
        registry.devices["unit"] = SimpleNamespace(id="unit", identifiers={
            ("bticino_c300x", f"{entry.data[CONF_STATION_ID]}:unit:{unit.id}")})

    monkeypatch.setattr(unit_entity, "async_register_unit_device", register)

    entry = _Entry(data={"host": "door"}, version=1)

    def update_entry(target: Any, *, data: dict[str, Any], version: int) -> None:
        target.data, target.version = data, version

    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update_entry))
    unit = normalize_outdoor_units(THREE).units[0]
    assert identity_migration.identity_migration_needed(entry, "c300x-0123456789ab")  # type: ignore[arg-type]
    result = identity_migration.async_migrate_identity(hass, entry, "c300x-0123456789ab", unit)  # type: ignore[arg-type]

    by_id = {e.entity_id: (e.unique_id, e.device_id) for e in registry.entities.values()}
    assert by_id == {
        "camera.e0": ("c300x-0123456789ab_unit_20_camera", "unit"),
        "event.e1": ("c300x-0123456789ab_unit_20_doorbell", "unit"),
        "button.e2": ("c300x-0123456789ab_unit_20_door", "unit"),
        "switch.e5": ("c300x-0123456789ab_ringer_mute", "station"),
        "sensor.e6": ("other-entry_device_cpu", "station"),
    }
    assert result == {"moved": ["camera.e0", "event.e1", "button.e2"], "removed": ["sensor.e3", "event.e4"]}
    assert registry.devices["station"].identifiers == {("bticino_c300x", "c300x-0123456789ab")}
    assert (entry.version, entry.data[CONF_STATION_ID], entry.data["host"]) == (2, "c300x-0123456789ab", "door")
    # Done once: the next setup has nothing to do.
    assert not identity_migration.identity_migration_needed(entry, "c300x-0123456789ab")  # type: ignore[arg-type]
    again = identity_migration.async_migrate_identity(hass, entry, "c300x-0123456789ab", unit)  # type: ignore[arg-type]
    assert again == {"moved": [], "removed": []}


def test_a_fresh_entry_takes_the_station_id_without_moving_anything() -> None:
    entry = _Entry(data={}, version=2)
    assert identity_migration.identity_migration_needed(entry, "c300x-0123456789ab")  # type: ignore[arg-type]
    assert not identity_migration.identity_migration_needed(entry, None)  # type: ignore[arg-type]
    assert not identity_migration.identity_migration_needed(entry, "../bad")  # type: ignore[arg-type]


def test_ring_entities_listen_to_the_agent_event_bus() -> None:
    entry = _entry(ONE)
    station = C300XStationRingEventEntity(entry)  # type: ignore[arg-type]
    listened: list[str] = []
    station.hass = SimpleNamespace(bus=SimpleNamespace(async_listen=lambda kind, _cb: listened.append(kind) or (lambda: None)))
    asyncio.run(station.async_added_to_hass())
    assert EVENT_AGENT_EVENT_RECEIVED in listened
