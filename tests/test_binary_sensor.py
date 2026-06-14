from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

if "homeassistant.components.binary_sensor" not in sys.modules:
    homeassistant = sys.modules.setdefault(
        "homeassistant",
        types.ModuleType("homeassistant"),
    )
    components = sys.modules.setdefault(
        "homeassistant.components",
        types.ModuleType("homeassistant.components"),
    )
    binary_sensor = types.ModuleType("homeassistant.components.binary_sensor")
    config_entries = sys.modules.setdefault(
        "homeassistant.config_entries",
        types.ModuleType("homeassistant.config_entries"),
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
    event_helper = types.ModuleType("homeassistant.helpers.event")
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    entity = sys.modules.setdefault(
        "homeassistant.helpers.entity",
        types.ModuleType("homeassistant.helpers.entity"),
    )
    entity_platform = sys.modules.setdefault(
        "homeassistant.helpers.entity_platform",
        types.ModuleType("homeassistant.helpers.entity_platform"),
    )

    class BinarySensorEntity:  # pragma: no cover - import-time stub only
        def async_write_ha_state(self) -> None:
            self.wrote_state = True

        def async_on_remove(self, callback: Any) -> None:
            self._remove_callback = callback

    class ConfigEntry:  # pragma: no cover - import-time stub only
        pass

    class HomeAssistant:  # pragma: no cover - import-time stub only
        pass

    class Entity:  # pragma: no cover - import-time stub only
        pass

    class DeviceInfo(dict):  # pragma: no cover - import-time stub only
        pass

    binary_sensor.BinarySensorEntity = BinarySensorEntity
    config_entries.ConfigEntry = ConfigEntry
    core.HomeAssistant = HomeAssistant
    core.callback = lambda func: func
    config_validation.config_entry_only_config_schema = lambda _domain: dict
    dispatcher.async_dispatcher_connect = lambda *args, **kwargs: lambda: None
    event_helper.async_call_later = lambda *args, **kwargs: lambda: None
    entity_registry.async_get = lambda hass: None
    entity.Entity = Entity
    entity.DeviceInfo = DeviceInfo
    entity_platform.AddEntitiesCallback = object
    helpers.config_validation = config_validation
    helpers.dispatcher = dispatcher
    helpers.event = event_helper
    helpers.entity_registry = entity_registry
    helpers.entity = entity
    helpers.entity_platform = entity_platform
    components.binary_sensor = binary_sensor
    homeassistant.components = components
    homeassistant.config_entries = config_entries
    homeassistant.core = core
    homeassistant.helpers = helpers
    sys.modules["homeassistant.components.binary_sensor"] = binary_sensor
    sys.modules["homeassistant.helpers.config_validation"] = config_validation
    sys.modules["homeassistant.helpers.dispatcher"] = dispatcher
    sys.modules["homeassistant.helpers.event"] = event_helper
    sys.modules["homeassistant.helpers.entity_registry"] = entity_registry

from custom_components.bticino_c300x.binary_sensor import (  # noqa: E402
    C300XHomeCallActiveBinarySensor,
    _optional_int,
)


@dataclass
class _FakeRuntimeData:
    connection_state: Any = field(
        default_factory=lambda: SimpleNamespace(available=True)
    )
    api: Any = None


@dataclass
class _FakeEntry:
    entry_id: str = "entry-1"
    title: str = "C300X"
    runtime_data: _FakeRuntimeData = field(default_factory=_FakeRuntimeData)


def test_home_call_active_tracks_agent_state_events() -> None:
    entity = C300XHomeCallActiveBinarySensor(_FakeEntry())  # type: ignore[arg-type]
    entity.hass = SimpleNamespace()

    entity._handle_agent_event(
        SimpleNamespace(
            data={
                "entry_id": "entry-1",
                "event_key": "home_call_started",
                "data": {
                    "home_call": {
                        "running": True,
                        "active": True,
                        "answered": False,
                    }
                },
            }
        )
    )

    assert entity.is_on is True
    assert entity.extra_state_attributes["phase"] == "ringing"
    assert entity.extra_state_attributes["answered"] is False

    entity._handle_agent_event(
        SimpleNamespace(
            data={
                "entry_id": "entry-1",
                "event_key": "home_call_answered",
                "data": {
                    "home_call": {
                        "running": True,
                        "active": True,
                        "answered": True,
                        "rtp_proxy": True,
                        "target_audio_port": 41528,
                    }
                },
            }
        )
    )

    assert entity.is_on is True
    assert entity.extra_state_attributes["phase"] == "answered"
    assert entity.extra_state_attributes["answered"] is True
    assert entity.extra_state_attributes["rtp_proxy"] is True
    assert entity.extra_state_attributes["target_audio_port"] == 41528

    entity._handle_agent_event(
        SimpleNamespace(
            data={
                "entry_id": "entry-1",
                "event_key": "home_call_ended",
                "data": {"home_call": {"rtp_packets": 3, "rtcp_packets": 1}},
            }
        )
    )

    assert entity.is_on is False
    assert entity.extra_state_attributes == {
        "phase": "idle",
        "answered": False,
        "rtp_proxy": False,
        "rtp_packets": 3,
        "rtcp_packets": 1,
        "target_audio_port": 0,
    }


def test_home_call_active_ignores_unrelated_events_and_reports_errors() -> None:
    entity = C300XHomeCallActiveBinarySensor(_FakeEntry())  # type: ignore[arg-type]

    entity._handle_agent_event(
        SimpleNamespace(
            data={
                "entry_id": "other-entry",
                "event_key": "home_call_started",
                "data": {"home_call": {"running": True}},
            }
        )
    )
    entity._handle_agent_event(
        SimpleNamespace(
            data={
                "entry_id": "entry-1",
                "event_key": "doorbell_pressed",
                "data": {"home_call": {"running": True}},
            }
        )
    )

    assert entity.is_on is False
    assert not hasattr(entity, "wrote_state")

    entity._apply_status(
        {
            "running": True,
            "active": False,
            "answered": False,
            "rtp_packets": "bad",
            "rtcp_packets": "2",
            "target_audio_port": "",
            "last_error": 503,
        }
    )

    assert entity.is_on is True
    assert entity.extra_state_attributes["phase"] == "ringing"
    assert entity.extra_state_attributes["rtp_packets"] == 0
    assert entity.extra_state_attributes["rtcp_packets"] == 2
    assert entity.extra_state_attributes["last_error"] == "503"


def test_home_call_optional_int_falls_back_for_invalid_values() -> None:
    assert _optional_int("123") == 123
    assert _optional_int(None, 7) == 7
    assert _optional_int("bad", 5) == 5
