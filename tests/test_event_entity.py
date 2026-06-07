from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

homeassistant = sys.modules.setdefault(
    "homeassistant",
    types.ModuleType("homeassistant"),
)
components = sys.modules.setdefault(
    "homeassistant.components",
    types.ModuleType("homeassistant.components"),
)
event_module = types.ModuleType("homeassistant.components.event")
config_entries = sys.modules.setdefault(
    "homeassistant.config_entries",
    types.ModuleType("homeassistant.config_entries"),
)
const = sys.modules.setdefault(
    "homeassistant.const",
    types.ModuleType("homeassistant.const"),
)
core = sys.modules.setdefault(
    "homeassistant.core",
    types.ModuleType("homeassistant.core"),
)
helpers = sys.modules.setdefault(
    "homeassistant.helpers",
    types.ModuleType("homeassistant.helpers"),
)
config_validation = types.ModuleType("homeassistant.helpers.config_validation")
dispatcher = types.ModuleType("homeassistant.helpers.dispatcher")
entity = sys.modules.setdefault(
    "homeassistant.helpers.entity",
    types.ModuleType("homeassistant.helpers.entity"),
)
entity_platform = sys.modules.setdefault(
    "homeassistant.helpers.entity_platform",
    types.ModuleType("homeassistant.helpers.entity_platform"),
)


class EventEntity:  # pragma: no cover - import-time stub only
    def _trigger_event(self, event_type: str, event_attributes: dict[str, Any]) -> None:
        self.triggered_event = (event_type, event_attributes)

    def async_write_ha_state(self) -> None:
        self.wrote_state = True

    def async_on_remove(self, _callback: Any) -> None:
        pass


class ConfigEntry:  # pragma: no cover - import-time stub only
    pass


class HomeAssistant:  # pragma: no cover - import-time stub only
    pass


class Entity:  # pragma: no cover - import-time stub only
    pass


class DeviceInfo(dict):  # pragma: no cover - import-time stub only
    pass


class DoorbellEventType:  # pragma: no cover - import-time stub only
    RING = "ring"


class EventDeviceClass:  # pragma: no cover - import-time stub only
    DOORBELL = "doorbell"


class EntityCategory:  # pragma: no cover - import-time stub only
    DIAGNOSTIC = "diagnostic"


event_module.DoorbellEventType = DoorbellEventType
event_module.EventDeviceClass = EventDeviceClass
event_module.EventEntity = EventEntity
config_entries.ConfigEntry = ConfigEntry
const.EntityCategory = EntityCategory
core.HomeAssistant = HomeAssistant
core.callback = lambda func: func
config_validation.config_entry_only_config_schema = lambda _domain: dict
dispatcher.async_dispatcher_connect = lambda *args, **kwargs: lambda: None
entity.Entity = Entity
entity.DeviceInfo = DeviceInfo
entity_platform.AddEntitiesCallback = object
components.event = event_module
homeassistant.const = const
helpers.config_validation = config_validation
helpers.dispatcher = dispatcher
helpers.entity = entity
helpers.entity_platform = entity_platform
homeassistant.components = components
sys.modules["homeassistant.components.event"] = event_module
sys.modules["homeassistant.helpers.config_validation"] = config_validation
sys.modules["homeassistant.helpers.dispatcher"] = dispatcher

from homeassistant.const import EntityCategory  # noqa: E402

from custom_components.bticino_c300x.entity import C300XEntity  # noqa: E402
from custom_components.bticino_c300x.event import (  # noqa: E402
    C300XDeviceAgentEventEntity,
    C300XDoorbellEventEntity,
    _display_event_types,
)


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
    voicemail_total: int | None = None
    voicemail_unread: int | None = None


@dataclass
class _FakeRuntimeData:
    event_state: _FakeEventState = field(default_factory=_FakeEventState)
    connection_state: _FakeConnectionState = field(default_factory=_FakeConnectionState)
    agent_info: dict[str, Any] = field(default_factory=dict)


@dataclass
class _FakeEntry:
    entry_id: str = "entry-1"
    title: str = "C300X"
    runtime_data: _FakeRuntimeData = field(default_factory=_FakeRuntimeData)


def test_device_event_entity_is_diagnostic_disabled_by_default() -> None:
    assert C300XDeviceAgentEventEntity._attr_entity_category == EntityCategory.DIAGNOSTIC
    assert C300XDeviceAgentEventEntity._attr_entity_registry_enabled_default is False


def test_device_info_uses_c300x_firmware_as_software_version() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(agent_info={"firmware": "1.7.19"}),
    )
    entity = C300XEntity(entry, "test")  # type: ignore[arg-type]

    assert entity.device_info["sw_version"] == "1.7.19"


def test_device_info_omits_empty_firmware_version() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(agent_info={"firmware": ""}),
    )
    entity = C300XEntity(entry, "test")  # type: ignore[arg-type]

    assert "sw_version" not in entity.device_info


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


def test_display_event_types_remain_stable_for_ha_state_translations() -> None:
    assert _display_event_types(["door_unlock_started", "ringer_unmuted"], "de") == [
        "door_unlock_started",
        "ringer_unmuted",
    ]
