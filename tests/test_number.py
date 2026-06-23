# ruff: noqa: E402

from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

homeassistant = sys.modules.setdefault(
    "homeassistant",
    types.ModuleType("homeassistant"),
)
components = sys.modules.setdefault(
    "homeassistant.components",
    types.ModuleType("homeassistant.components"),
)
number = sys.modules.setdefault(
    "homeassistant.components.number",
    types.ModuleType("homeassistant.components.number"),
)
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
exceptions = sys.modules.setdefault(
    "homeassistant.exceptions",
    types.ModuleType("homeassistant.exceptions"),
)
helpers = sys.modules.setdefault(
    "homeassistant.helpers",
    types.ModuleType("homeassistant.helpers"),
)
config_validation = sys.modules.setdefault(
    "homeassistant.helpers.config_validation",
    types.ModuleType("homeassistant.helpers.config_validation"),
)
dispatcher = sys.modules.setdefault(
    "homeassistant.helpers.dispatcher",
    types.ModuleType("homeassistant.helpers.dispatcher"),
)
entity = sys.modules.setdefault(
    "homeassistant.helpers.entity",
    types.ModuleType("homeassistant.helpers.entity"),
)
entity_platform = sys.modules.setdefault(
    "homeassistant.helpers.entity_platform",
    types.ModuleType("homeassistant.helpers.entity_platform"),
)


class NumberEntity:  # pragma: no cover - import-time stub only
    def async_write_ha_state(self) -> None:
        self.wrote_state = True


class ConfigEntry:  # pragma: no cover - import-time stub only
    pass


class HomeAssistant:  # pragma: no cover - import-time stub only
    pass


class ServiceCall:  # pragma: no cover - import-time stub only
    pass


class HomeAssistantError(Exception):  # pragma: no cover - import-time stub only
    pass


class Entity:  # pragma: no cover - import-time stub only
    pass


class DeviceInfo(dict):  # pragma: no cover - import-time stub only
    pass


number.NumberEntity = NumberEntity
config_entries.ConfigEntry = ConfigEntry
const.PERCENTAGE = "%"
core.HomeAssistant = HomeAssistant
core.ServiceCall = ServiceCall
core.callback = lambda func: func
exceptions.HomeAssistantError = HomeAssistantError
config_validation.config_entry_only_config_schema = lambda _domain: dict
dispatcher.async_dispatcher_connect = lambda *args, **kwargs: (lambda: None)
entity.Entity = Entity
entity.DeviceInfo = DeviceInfo
entity_platform.AddEntitiesCallback = object
components.number = number
homeassistant.components = components
homeassistant.const = const
helpers.config_validation = config_validation
helpers.dispatcher = dispatcher
helpers.entity = entity
helpers.entity_platform = entity_platform

from homeassistant.exceptions import HomeAssistantError  # noqa: E402

from custom_components.bticino_c300x.api import C300XAgentApiError  # noqa: E402
from custom_components.bticino_c300x.number import (  # noqa: E402
    C300XRingerVolumeNumber,
    async_setup_entry,
)


class _FakeApi:
    def __init__(self, *, volume: int | None = 30, fail_status: bool = False) -> None:
        self.volume = volume
        self.fail_status = fail_status
        self.ringer_reads = 0
        self.volume_sets: list[int] = []

    async def async_ringer_status(self) -> dict[str, Any]:
        self.ringer_reads += 1
        if self.fail_status:
            raise C300XAgentApiError("offline")
        return {"muted": False, "volume": self.volume}

    async def async_set_ringer_volume(self, volume: int) -> dict[str, Any]:
        self.volume_sets.append(volume)
        self.volume = volume
        return {"volume": volume}


@dataclass
class _FakeConnectionState:
    available: bool = True


@dataclass
class _FakeRuntimeData:
    capabilities: dict[str, Any] = field(
        default_factory=lambda: {"ringer": {"supported": True, "volume": True}}
    )
    api: _FakeApi = field(default_factory=_FakeApi)
    connection_state: _FakeConnectionState = field(default_factory=_FakeConnectionState)


@dataclass
class _FakeEntry:
    entry_id: str = "entry-1"
    title: str = "C300X"
    runtime_data: _FakeRuntimeData = field(default_factory=_FakeRuntimeData)


def test_number_setup_adds_supported_entity_after_initial_refresh() -> None:
    entry = _FakeEntry()
    added: list[list[Any]] = []

    asyncio.run(async_setup_entry("hass", entry, added.append))  # type: ignore[arg-type]

    assert len(added) == 1
    entity = added[0][0]
    assert isinstance(entity, C300XRingerVolumeNumber)
    assert entry.runtime_data.api.ringer_reads == 1
    assert entity.native_value == 30


def test_number_setup_skips_legacy_boolean_ringer_capability() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(capabilities={"ringer": True})
    )
    added: list[list[Any]] = []

    asyncio.run(async_setup_entry("hass", entry, added.append))  # type: ignore[arg-type]

    assert added == []
    assert entry.runtime_data.api.ringer_reads == 0


def test_ringer_volume_number_sets_volume() -> None:
    entry = _FakeEntry()
    entity = C300XRingerVolumeNumber(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_set_native_value(40))

    assert entry.runtime_data.api.volume_sets == [40]
    assert entity.native_value == 40
    assert entity.available is True


@pytest.mark.parametrize("value", [0, 9, 101, 10.5, "invalid"])
def test_ringer_volume_number_rejects_invalid_volume(value: Any) -> None:
    entry = _FakeEntry()
    entity = C300XRingerVolumeNumber(entry)  # type: ignore[arg-type]

    with pytest.raises(HomeAssistantError):
        asyncio.run(entity.async_set_native_value(value))  # type: ignore[arg-type]

    assert entry.runtime_data.api.volume_sets == []


def test_ringer_volume_event_updates_number() -> None:
    entity = C300XRingerVolumeNumber(_FakeEntry())  # type: ignore[arg-type]

    entity._handle_agent_event(
        SimpleNamespace(
            data={
                "entry_id": "entry-1",
                "event_type": "ringer_volume_changed",
                "volume": 70,
            }
        )
    )

    assert entity.native_value == 70
    assert entity.available is True


def test_ringer_volume_number_marks_unavailable_when_refresh_fails() -> None:
    entry = _FakeEntry(runtime_data=_FakeRuntimeData(api=_FakeApi(fail_status=True)))
    entity = C300XRingerVolumeNumber(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())

    assert entity.available is False
    assert entity.native_value is None
