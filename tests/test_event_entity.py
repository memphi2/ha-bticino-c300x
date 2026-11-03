from __future__ import annotations

# ruff: noqa: E402, I001

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

pytestmark = pytest.mark.usefixtures("entity_ha_boundary")

from homeassistant.const import EntityCategory  # noqa: E402
from custom_components.bticino_c300x.agent_contracts import CapabilityPayload  # noqa: E402
from custom_components.bticino_c300x.const import (  # noqa: E402
    DASHBOARD_ENTITY_DOOR_UNLOCK,
    EVENT_ACTION_RECEIVED,
    EVENT_AGENT_EVENT_RECEIVED,
)
from custom_components.bticino_c300x.entity import C300XEntity  # noqa: E402
from custom_components.bticino_c300x.event import (  # noqa: E402
    C300XDeviceAgentEventEntity,
    C300XDoorbellEventEntity,
    _language,
    _nested_dict_value,
    async_setup_entry,
)


@pytest.fixture(autouse=True)
def event_entity_ha_boundary(monkeypatch):
    from custom_components.bticino_c300x import entity

    monkeypatch.setattr(entity, "async_dispatcher_connect", lambda *_: lambda: None)
    for cls in (C300XDoorbellEventEntity, C300XDeviceAgentEventEntity):
        monkeypatch.setattr(cls, "_trigger_event", lambda self, kind, attrs: setattr(self, "triggered_event", (kind, attrs)))
        monkeypatch.setattr(cls, "async_write_ha_state", lambda self: setattr(self, "wrote_state", True))


@dataclass
class _FakeConnectionState:
    available: bool = True


@dataclass
class _FakeEventState:
    last_event: str | None = None
    last_event_time: str | None = None
    last_event_data: dict[str, Any] = field(default_factory=dict)
    smartphone_forwarding_mode: str | None = None
    ringer_muted: bool | None = None
    ringer_volume: int | None = None
    voicemail_total: int | None = None
    voicemail_unread: int | None = None


@dataclass
class _FakeRuntimeData:
    event_state: _FakeEventState = field(default_factory=_FakeEventState)
    connection_state: _FakeConnectionState = field(default_factory=_FakeConnectionState)
    agent_info: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, Any] = field(default_factory=dict)


@dataclass
class _FakeEntry:
    entry_id: str = "entry-1"
    title: str = "C300X"
    runtime_data: _FakeRuntimeData = field(default_factory=_FakeRuntimeData)


class _FakeBus:
    def __init__(self) -> None:
        self.listeners: list[tuple[str, Any]] = []

    def async_listen(self, event_type: str, callback: Any) -> Any:
        self.listeners.append((event_type, callback))
        return lambda: None


class _FakeHass:
    def __init__(self, language: str = "en") -> None:
        self.bus = _FakeBus()
        self.config = SimpleNamespace(language=language)


def test_device_event_entity_is_diagnostic_enabled_by_default() -> None:
    entity = C300XDeviceAgentEventEntity(_FakeEntry(), ["doorbell_pressed"])
    assert entity.entity_category == EntityCategory.DIAGNOSTIC
    assert entity.entity_registry_enabled_default is True


def test_async_setup_entry_adds_supported_event_entities() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={
                "doorbell_events": {"supported": True},
                "stair_light": {"supported": True},
            }
        )
    )
    added: list[Any] = []

    asyncio.run(async_setup_entry(None, entry, added.extend))  # type: ignore[arg-type]

    assert [type(entity) for entity in added] == [
        C300XDoorbellEventEntity,
        C300XDeviceAgentEventEntity,
    ]
    assert "stair_light_activated" in added[1]._attr_event_types
    assert "stair_light_released" in added[1]._attr_event_types


def test_async_setup_entry_keeps_always_registered_agent_events() -> None:
    added: list[Any] = []

    asyncio.run(
        async_setup_entry(  # type: ignore[arg-type]
            None,
            _FakeEntry(runtime_data=_FakeRuntimeData(capabilities={})),
            added.extend,
        )
    )

    assert [type(entity) for entity in added] == [C300XDeviceAgentEventEntity]
    assert "agent_restarted" in added[0]._attr_event_types


def test_device_info_uses_c300x_firmware_as_software_version() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(agent_info={"firmware": "1.7.19"}),
    )
    entity = C300XEntity(entry, "test")  # type: ignore[arg-type]

    assert entity.device_info["sw_version"] == "1.7.19"


def test_device_info_uses_typed_setup_firmware_as_software_version() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            agent_info=CapabilityPayload(
                raw={"api_version": "1"},
                version="1.2.0",
                agent={"version": "1.2.0"},
                implementation="native-c",
                api_version="1",
                device_id="device",
                model="C300X",
                firmware="1.7.19",
                capabilities={},
            ),
        ),
    )
    entity = C300XEntity(entry, "test")  # type: ignore[arg-type]

    assert entity.device_info["sw_version"] == "1.7.19"


def test_device_info_omits_empty_firmware_version() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(agent_info={"firmware": ""}),
    )
    entity = C300XEntity(entry, "test")  # type: ignore[arg-type]

    assert "sw_version" not in entity.device_info


def test_base_entity_deduplicates_unchanged_connection_state_writes() -> None:
    entry = _FakeEntry()
    entity = C300XEntity(entry, "test")  # type: ignore[arg-type]
    writes: list[str] = []
    entity.async_write_ha_state = lambda: writes.append("write")  # type: ignore[method-assign]

    entity._handle_c300x_connection_state_changed(entry.entry_id)
    entry.runtime_data.connection_state.available = False
    entity._handle_c300x_connection_state_changed(entry.entry_id)
    entity._handle_c300x_connection_state_changed(entry.entry_id)
    entry.runtime_data.connection_state.available = True
    entity._handle_c300x_connection_state_changed(entry.entry_id)
    entity._handle_c300x_connection_state_changed("other-entry")

    assert writes == ["write", "write"]


def test_device_event_entity_triggers_stable_event_type_with_readable_attributes() -> None:
    entity = C300XDeviceAgentEventEntity(
        _FakeEntry(),  # type: ignore[arg-type]
        ["door_unlock_started"],
    )
    entity.hass = SimpleNamespace(config=SimpleNamespace(language="de"))

    entity._write_event_data(
        {
            "entry_id": "entry-1",
            "event_at": "2026-05-26T12:00:00+00:00",
            "event_key": "door_unlock_started",
            "event_type": "door_unlock_started",
        }
    )

    event_type, attributes = entity.triggered_event
    assert event_type == "door_unlock_started"
    assert attributes["event"] == "Türöffner gestartet"
    assert attributes["event_value"] == "Türöffner gestartet"
    assert attributes["event_key"] == "door_unlock_started"
    assert attributes["event_type"] == "Türöffner gestartet"
    assert attributes["event_type_key"] == "door_unlock_started"


def test_doorbell_event_entity_triggers_standard_ring_event() -> None:
    entity = C300XDoorbellEventEntity(_FakeEntry())  # type: ignore[arg-type]
    entity.hass = SimpleNamespace(config=SimpleNamespace(language="de"))

    assert entity._attr_device_class == "doorbell"
    assert entity._attr_event_types == ["ring"]

    entity._handle_agent_event(
        SimpleNamespace(
            data={
                "entry_id": "entry-1",
                "event_at": "2026-05-31T12:00:00+00:00",
                "event_key": "doorbell_pressed",
                "event_type": "doorbell_pressed",
                "video_available": True,
            }
        )
    )

    event_type, attributes = entity.triggered_event
    assert event_type == "ring"
    assert attributes["event"] == "Türklingel gedrückt"
    assert attributes["event_key"] == "doorbell_pressed"
    assert entity.extra_state_attributes["last_ring_at"] == "2026-05-31T12:00:00+00:00"
    assert entity.extra_state_attributes["video_available"] is True


def test_event_entities_register_bus_listeners() -> None:
    doorbell = C300XDoorbellEventEntity(_FakeEntry())  # type: ignore[arg-type]
    doorbell.hass = _FakeHass()
    device = C300XDeviceAgentEventEntity(  # type: ignore[arg-type]
        _FakeEntry(),
        ["doorbell_pressed", "stair_light_activated"],
    )
    device.hass = _FakeHass()

    asyncio.run(doorbell.async_added_to_hass())
    asyncio.run(device.async_added_to_hass())

    assert doorbell.hass.bus.listeners == [
        (EVENT_AGENT_EVENT_RECEIVED, doorbell._handle_agent_event)
    ]
    assert device.hass.bus.listeners == [
        (EVENT_AGENT_EVENT_RECEIVED, device._handle_agent_event),
        (EVENT_ACTION_RECEIVED, device._handle_action_event),
    ]


def test_doorbell_event_entity_ignores_other_entries_keys_and_duplicates() -> None:
    entity = C300XDoorbellEventEntity(_FakeEntry())  # type: ignore[arg-type]
    entity.hass = SimpleNamespace(config=SimpleNamespace(language="en"))
    valid_event = SimpleNamespace(
        data={
            "entry_id": "entry-1",
            "event_at": "2026-05-31T12:00:00+00:00",
            "event_key": "doorbell_pressed",
        }
    )

    entity._handle_agent_event(SimpleNamespace(data={**valid_event.data, "entry_id": "x"}))
    entity._handle_agent_event(
        SimpleNamespace(data={**valid_event.data, "event_key": "doorbell_media_closed"})
    )
    assert not hasattr(entity, "triggered_event")

    entity._handle_agent_event(valid_event)
    entity.triggered_event = ("unchanged", {})
    entity.wrote_state = False
    entity._handle_agent_event(valid_event)

    assert entity.triggered_event == ("unchanged", {})
    assert entity.wrote_state is False


def test_device_event_entity_ignores_unregistered_event_type() -> None:
    entity = C300XDeviceAgentEventEntity(
        _FakeEntry(),  # type: ignore[arg-type]
        ["door_unlock_started"],
    )
    entity.hass = SimpleNamespace(config=SimpleNamespace(language="de"))

    entity._write_event_data(
        {
            "entry_id": "entry-1",
            "event_at": "2026-05-26T12:00:00+00:00",
            "event_key": "system_metrics_changed",
            "event_type": "system_metrics_changed",
        }
    )

    assert not hasattr(entity, "triggered_event")
    assert not hasattr(entity, "wrote_state")


def test_device_event_entity_filters_entry_duplicate_and_action_events() -> None:
    entity = C300XDeviceAgentEventEntity(  # type: ignore[arg-type]
        _FakeEntry(),
        ["door_unlock_started"],
    )
    entity.hass = SimpleNamespace(config=SimpleNamespace(language="en"))

    entity._handle_agent_event(
        SimpleNamespace(
            data={
                "entry_id": "other",
                "event_at": "2026-06-13T12:00:00+00:00",
                "event_key": "stair_light_activated",
            }
        )
    )
    assert not hasattr(entity, "triggered_event")

    entity._handle_action_event(
        SimpleNamespace(
            data={
                "entry_id": "entry-1",
                "action_id": DASHBOARD_ENTITY_DOOR_UNLOCK,
            }
        )
    )
    assert entity.triggered_event[0] == "door_unlock_started"
    entity.triggered_event = ("unchanged", {})
    entity.wrote_state = False
    entity._write_event_data(
        {
            "entry_id": "entry-1",
            "event_at": entity._last_event_at,
            "event_key": "door_unlock_started",
        }
    )
    assert entity.triggered_event == ("unchanged", {})
    assert entity.wrote_state is False

    entity._handle_action_event(
        SimpleNamespace(data={"entry_id": "entry-1", "action_id": "unsupported"})
    )
    assert entity.triggered_event == ("unchanged", {})


def test_device_event_attributes_use_nested_message_counters() -> None:
    entity = C300XDeviceAgentEventEntity(  # type: ignore[arg-type]
        _FakeEntry(),
        ["answering_machine_messages_changed"],
    )
    entity.hass = SimpleNamespace(config=SimpleNamespace(language="en"))

    entity._write_event_data(
        {
            "entry_id": "entry-1",
            "event_at": "2026-06-13T12:00:00+00:00",
            "event_key": "answering_machine_messages_changed",
            "voicemail": {"total": 4, "unread": 2},
            "memos": {"total": 3, "text_total": 1, "voice_total": 2},
        }
    )

    attrs = entity.extra_state_attributes
    assert attrs["voicemail_total"] == 4
    assert attrs["voicemail_unread"] == 2
    assert attrs["memos_total"] == 3
    assert attrs["memos_text_total"] == 1
    assert attrs["memos_voice_total"] == 2


def test_language_and_nested_dict_helpers_handle_missing_data() -> None:
    assert _language(None) is None
    assert _language(SimpleNamespace(config=SimpleNamespace(language="de"))) == "de"
    assert _nested_dict_value({"parent": {"child": 3}}, "parent", "child") == 3
    assert _nested_dict_value({"parent": []}, "parent", "child") is None
