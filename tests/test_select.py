from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

if "homeassistant.components.select" not in sys.modules:
    homeassistant = sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
    components = sys.modules.setdefault(
        "homeassistant.components", types.ModuleType("homeassistant.components")
    )
    select = types.ModuleType("homeassistant.components.select")
    config_entries = sys.modules.setdefault(
        "homeassistant.config_entries", types.ModuleType("homeassistant.config_entries")
    )
    core = sys.modules.setdefault("homeassistant.core", types.ModuleType("homeassistant.core"))
    const = sys.modules.setdefault("homeassistant.const", types.ModuleType("homeassistant.const"))
    helpers = sys.modules.setdefault("homeassistant.helpers", types.ModuleType("homeassistant.helpers"))
    entity = sys.modules.setdefault("homeassistant.helpers.entity", types.ModuleType("homeassistant.helpers.entity"))
    entity_platform = sys.modules.setdefault(
        "homeassistant.helpers.entity_platform",
        types.ModuleType("homeassistant.helpers.entity_platform"),
    )
    dispatcher = sys.modules.setdefault(
        "homeassistant.helpers.dispatcher", types.ModuleType("homeassistant.helpers.dispatcher")
    )
    config_validation = types.ModuleType("homeassistant.helpers.config_validation")

    class SelectEntity:
        def async_write_ha_state(self) -> None:
            self.wrote_state = True

    class ConfigEntry:
        pass

    class HomeAssistant:
        pass

    class Entity:
        pass

    class DeviceInfo(dict):
        pass

    class EntityCategory:
        CONFIG = "config"

    select.SelectEntity = SelectEntity
    config_entries.ConfigEntry = ConfigEntry
    core.HomeAssistant = HomeAssistant
    core.callback = lambda func: func
    const.EntityCategory = EntityCategory
    entity.Entity = Entity
    entity.DeviceInfo = DeviceInfo
    entity_platform.AddEntitiesCallback = object
    dispatcher.async_dispatcher_connect = lambda *args, **kwargs: (lambda: None)
    config_validation.config_entry_only_config_schema = lambda _domain: dict
    helpers.entity = entity
    helpers.entity_platform = entity_platform
    helpers.dispatcher = dispatcher
    helpers.config_validation = config_validation
    components.select = select
    homeassistant.components = components
    sys.modules["homeassistant.components.select"] = select
    sys.modules["homeassistant.helpers.config_validation"] = config_validation

from custom_components.bticino_c300x.select import (  # noqa: E402
    C300XSmartphoneForwardingModeSelect,
)


class _FakeApi:
    def __init__(self) -> None:
        self.active_reads = 0
        self.selected: list[str] = []

    async def async_smartphone_forwarding_status(self) -> dict[str, Any]:
        self.active_reads += 1
        return {"mode": 2, "state": "blocked"}

    async def async_set_smartphone_forwarding_mode(self, mode: str) -> dict[str, Any]:
        self.selected.append(mode)
        return {"mode": 1, "state": mode}


@dataclass
class _FakeRuntimeData:
    capabilities: dict[str, Any] = field(default_factory=dict)
    api: _FakeApi = field(default_factory=_FakeApi)


@dataclass
class _FakeEntry:
    entry_id: str = "entry-1"
    title: str = "C300X"
    data: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    runtime_data: _FakeRuntimeData = field(default_factory=_FakeRuntimeData)


def test_smartphone_forwarding_select_refreshes_active_status() -> None:
    entry = _FakeEntry()
    entity = C300XSmartphoneForwardingModeSelect(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())

    assert entry.runtime_data.api.active_reads == 1
    assert entity.current_option == "blocked"
    assert entity.extra_state_attributes == {"mode": 2, "state": "blocked"}


def test_smartphone_forwarding_select_sets_three_state_mode() -> None:
    entry = _FakeEntry()
    entity = C300XSmartphoneForwardingModeSelect(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_select_option("in-house-only"))

    assert entry.runtime_data.api.selected == ["in-house-only"]
    assert entity.current_option == "in-house-only"


def test_smartphone_forwarding_event_updates_select_state() -> None:
    entity = C300XSmartphoneForwardingModeSelect(_FakeEntry())  # type: ignore[arg-type]

    entity._handle_agent_event(
        SimpleNamespace(
            data={
                "entry_id": "entry-1",
                "event_type": "smartphone_forwarding_changed",
                "mode": 1,
            }
        )
    )

    assert entity.current_option == "in-house-only"
    assert entity.extra_state_attributes == {"mode": 1, "state": "in-house-only"}
