from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
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
    config_entries = types.ModuleType("homeassistant.config_entries")
    core = types.ModuleType("homeassistant.core")
    helpers = sys.modules.setdefault(
        "homeassistant.helpers",
        types.ModuleType("homeassistant.helpers"),
    )
    dispatcher = types.ModuleType("homeassistant.helpers.dispatcher")
    entity = types.ModuleType("homeassistant.helpers.entity")
    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")

    class BinarySensorEntity:  # pragma: no cover - import-time stub only
        def async_write_ha_state(self) -> None:
            self.wrote_state = True

    class ConfigEntry:  # pragma: no cover - import-time stub only
        pass

    class HomeAssistant:  # pragma: no cover - import-time stub only
        pass

    class Entity:  # pragma: no cover - import-time stub only
        def async_write_ha_state(self) -> None:
            self.wrote_state = True

        def async_on_remove(self, _callback: Any) -> None:
            pass

    class DeviceInfo(dict):  # pragma: no cover - import-time stub only
        pass

    binary_sensor.BinarySensorEntity = BinarySensorEntity
    config_entries.ConfigEntry = ConfigEntry
    core.HomeAssistant = HomeAssistant
    core.callback = lambda func: func
    dispatcher.async_dispatcher_connect = lambda *args, **kwargs: lambda: None
    entity.Entity = Entity
    entity.DeviceInfo = DeviceInfo
    entity_platform.AddEntitiesCallback = object
    components.binary_sensor = binary_sensor
    helpers.dispatcher = dispatcher
    helpers.entity = entity
    helpers.entity_platform = entity_platform
    sys.modules["homeassistant.components.binary_sensor"] = binary_sensor
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers.dispatcher"] = dispatcher
    sys.modules["homeassistant.helpers.entity"] = entity
    sys.modules["homeassistant.helpers.entity_platform"] = entity_platform


from custom_components.bticino_c300x.binary_sensor import (  # noqa: E402
    C300XDoorbellVideoAvailableBinarySensor,
)


@dataclass
class _FakeEventState:
    video_available: bool = False
    video_active_until: str | None = None
    video_stream_path: str | None = None


@dataclass
class _FakeRuntimeData:
    event_state: _FakeEventState = field(default_factory=_FakeEventState)
    connection_state: Any = field(default_factory=lambda: types.SimpleNamespace(available=True))
    capabilities: dict[str, Any] = field(
        default_factory=lambda: {"doorbell_video": {"supported": True}},
    )


@dataclass
class _FakeEntry:
    entry_id: str = "entry-1"
    title: str = "C300X"
    runtime_data: _FakeRuntimeData = field(default_factory=_FakeRuntimeData)


def test_doorbell_video_binary_sensor_clears_local_window_on_runtime_clear() -> None:
    entity = C300XDoorbellVideoAvailableBinarySensor(_FakeEntry())  # type: ignore[arg-type]
    entity._available = True
    entity._active_until = "2099-05-27T12:00:00+00:00"
    entity._stream_path = "/doorbell-video"

    entity._handle_event_state_changed("entry-1")

    assert entity.is_on is False
    assert entity.extra_state_attributes == {}
    assert entity.wrote_state is True
