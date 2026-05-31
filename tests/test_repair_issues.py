from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from typing import Any

if "homeassistant.core" not in sys.modules:
    homeassistant = sys.modules.setdefault(
        "homeassistant",
        types.ModuleType("homeassistant"),
    )
    core = types.ModuleType("homeassistant.core")

    def callback(func: Any) -> Any:
        return func

    class HomeAssistant:  # pragma: no cover - import-time stub only
        pass

    core.HomeAssistant = HomeAssistant
    core.callback = callback
    sys.modules["homeassistant.core"] = core
else:
    core = sys.modules["homeassistant.core"]
    if not hasattr(core, "callback"):
        core.callback = lambda func: func

if "homeassistant.config_entries" not in sys.modules:
    config_entries = types.ModuleType("homeassistant.config_entries")

    class ConfigEntry:  # pragma: no cover - import-time stub only
        pass

    config_entries.ConfigEntry = ConfigEntry
    sys.modules["homeassistant.config_entries"] = config_entries

helpers = sys.modules.setdefault(
    "homeassistant.helpers",
    types.ModuleType("homeassistant.helpers"),
)
issue_registry = types.ModuleType("homeassistant.helpers.issue_registry")
entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")

CREATED_ISSUES: dict[str, dict[str, Any]] = {}
DELETED_ISSUES: list[str] = []


def _create_issue(**kwargs: Any) -> None:
    CREATED_ISSUES[kwargs["issue_id"]] = kwargs


def _delete_issue(**kwargs: Any) -> None:
    issue_id = kwargs["issue_id"]
    DELETED_ISSUES.append(issue_id)
    CREATED_ISSUES.pop(issue_id, None)


issue_registry.IssueSeverity = types.SimpleNamespace(ERROR="error", WARNING="warning")
issue_registry.async_create_issue = _create_issue
issue_registry.async_delete_issue = _delete_issue


def _async_get_entity_registry(hass: Any) -> Any:
    return hass.entity_registry


entity_registry.async_get = _async_get_entity_registry
helpers.issue_registry = issue_registry
helpers.entity_registry = entity_registry
sys.modules["homeassistant.helpers.issue_registry"] = issue_registry
sys.modules["homeassistant.helpers.entity_registry"] = entity_registry

from custom_components.bticino_c300x.const import (  # noqa: E402
    CONF_ACTIONS,
    CONF_ALARM_ENTITY_ID,
)
from custom_components.bticino_c300x.repair_issues import (  # noqa: E402
    AGENT_CAPABILITY_MISMATCH_ISSUE,
    INVALID_ACTION_MAP_ISSUE,
    MISSING_ALARM_ENTITY_ISSUE,
    async_sync_entry_repair_issues,
    repair_issue_id,
)


@dataclass(slots=True)
class FakeRuntimeData:
    capabilities: dict[str, Any] = field(default_factory=lambda: {"doorbell_events": True})


@dataclass(slots=True)
class FakeEntry:
    entry_id: str = "entry-1"
    title: str = "C300X"
    data: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    runtime_data: FakeRuntimeData = field(default_factory=FakeRuntimeData)


@dataclass(slots=True)
class FakeStates:
    values: dict[str, object] = field(default_factory=dict)

    def get(self, entity_id: str) -> object | None:
        return self.values.get(entity_id)


@dataclass(slots=True)
class FakeEntityRegistry:
    entity_ids: set[str] = field(default_factory=set)

    def async_get(self, entity_id: str) -> object | None:
        return object() if entity_id in self.entity_ids else None


@dataclass(slots=True)
class FakeHass:
    states: FakeStates = field(default_factory=FakeStates)
    entity_registry: FakeEntityRegistry = field(default_factory=FakeEntityRegistry)


def setup_function() -> None:
    CREATED_ISSUES.clear()
    DELETED_ISSUES.clear()


def test_invalid_action_map_creates_repair_issue() -> None:
    entry = FakeEntry(
        options={
            CONF_ACTIONS: {
                "bad action": {"domain": "light", "service": "toggle"},
            }
        }
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    issue = CREATED_ISSUES[repair_issue_id(INVALID_ACTION_MAP_ISSUE, entry.entry_id)]
    assert issue["severity"] == "error"
    assert issue["translation_key"] == INVALID_ACTION_MAP_ISSUE
    assert "unsupported characters" in issue["translation_placeholders"]["error"]


def test_valid_action_map_clears_repair_issue() -> None:
    entry = FakeEntry(
        options={
            CONF_ACTIONS: {
                "entry_light": {"domain": "light", "service": "toggle"},
            }
        }
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    assert repair_issue_id(INVALID_ACTION_MAP_ISSUE, entry.entry_id) in DELETED_ISSUES
    assert CREATED_ISSUES == {}


def test_missing_alarm_entity_creates_repair_issue() -> None:
    entry = FakeEntry(data={CONF_ALARM_ENTITY_ID: "alarm_control_panel.missing"})

    async_sync_entry_repair_issues(FakeHass(), entry)

    issue = CREATED_ISSUES[repair_issue_id(MISSING_ALARM_ENTITY_ISSUE, entry.entry_id)]
    assert issue["severity"] == "warning"
    assert issue["translation_placeholders"]["entity_id"] == "alarm_control_panel.missing"


def test_existing_alarm_entity_clears_repair_issue() -> None:
    entry = FakeEntry(data={CONF_ALARM_ENTITY_ID: "alarm_control_panel.home"})
    hass = FakeHass(entity_registry=FakeEntityRegistry({"alarm_control_panel.home"}))

    async_sync_entry_repair_issues(hass, entry)

    assert repair_issue_id(MISSING_ALARM_ENTITY_ISSUE, entry.entry_id) in DELETED_ISSUES
    assert CREATED_ISSUES == {}


def test_empty_agent_capabilities_create_repair_issue() -> None:
    entry = FakeEntry(runtime_data=FakeRuntimeData(capabilities={}))

    async_sync_entry_repair_issues(FakeHass(), entry)

    issue = CREATED_ISSUES[
        repair_issue_id(AGENT_CAPABILITY_MISMATCH_ISSUE, entry.entry_id)
    ]
    assert issue["severity"] == "error"
    assert issue["translation_key"] == AGENT_CAPABILITY_MISMATCH_ISSUE
