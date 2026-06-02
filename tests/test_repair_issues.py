from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
config_validation = types.ModuleType("homeassistant.helpers.config_validation")
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
config_validation.config_entry_only_config_schema = lambda _domain: dict


def _async_get_entity_registry(hass: Any) -> Any:
    return hass.entity_registry


entity_registry.async_get = _async_get_entity_registry
helpers.issue_registry = issue_registry
helpers.entity_registry = entity_registry
helpers.config_validation = config_validation
sys.modules["homeassistant.helpers.config_validation"] = config_validation
sys.modules["homeassistant.helpers.issue_registry"] = issue_registry
sys.modules["homeassistant.helpers.entity_registry"] = entity_registry

from custom_components.bticino_c300x import repair_issues  # noqa: E402
from custom_components.bticino_c300x.agent_update import AgentUpdateState  # noqa: E402
from custom_components.bticino_c300x.const import (  # noqa: E402
    CONF_ACTIONS,
    CONF_ALARM_ENTITY_ID,
)
from custom_components.bticino_c300x.data import (  # noqa: E402
    C300XCallbackDiagnostics,
    C300XConnectionState,
)
from custom_components.bticino_c300x.repair_issues import (  # noqa: E402
    AGENT_CAPABILITY_MISMATCH_ISSUE,
    DEVICE_AGENT_UPDATE_REQUIRED_ISSUE,
    INVALID_ACTION_MAP_ISSUE,
    MISSING_ALARM_ENTITY_ISSUE,
    UNSUPPORTED_CALLBACK_URL_ISSUE,
    async_sync_entry_repair_issues,
    repair_issue_id,
)

repair_issues.ir.IssueSeverity = issue_registry.IssueSeverity
repair_issues.ir.async_create_issue = _create_issue
repair_issues.ir.async_delete_issue = _delete_issue
repair_issues.er = entity_registry


@dataclass(slots=True)
class FakeRuntimeData:
    capabilities: dict[str, Any] = field(default_factory=lambda: {"doorbell_events": True})
    agent_update_state: AgentUpdateState | None = None
    connection_state: Any | None = None
    display_bridge_diagnostics: Any | None = None


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


def test_offline_agent_clears_capability_repair_issue() -> None:
    entry = FakeEntry(
        runtime_data=FakeRuntimeData(
            capabilities={},
            connection_state=types.SimpleNamespace(available=False),
        )
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    assert repair_issue_id(AGENT_CAPABILITY_MISMATCH_ISSUE, entry.entry_id) in DELETED_ISSUES
    assert CREATED_ISSUES == {}


def test_agent_update_available_creates_fixable_repair_issue() -> None:
    entry = FakeEntry(
        runtime_data=FakeRuntimeData(
            agent_update_state=AgentUpdateState(
                state="update_available",
                installed_version="0.2.0",
                available_version="0.3.1",
                installed_api_version="1",
                available_api_version="1",
                self_update_supported=True,
                reason="version_mismatch",
            )
        )
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    issue = CREATED_ISSUES[
        repair_issue_id(DEVICE_AGENT_UPDATE_REQUIRED_ISSUE, entry.entry_id)
    ]
    assert issue["severity"] == "warning"
    assert issue["is_fixable"] is True
    assert issue["translation_key"] == DEVICE_AGENT_UPDATE_REQUIRED_ISSUE
    assert issue["translation_placeholders"]["available_version"] == "0.3.1"


def test_non_self_update_agent_creates_fixable_ssh_repair_issue() -> None:
    entry = FakeEntry(
        runtime_data=FakeRuntimeData(
            agent_update_state=AgentUpdateState(
                state="incompatible",
                installed_version="0.2.0",
                available_version="0.3.1",
                installed_api_version="1",
                available_api_version="1",
                self_update_supported=False,
                reason="self_update_not_supported",
            )
        )
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    issue = CREATED_ISSUES[
        repair_issue_id(DEVICE_AGENT_UPDATE_REQUIRED_ISSUE, entry.entry_id)
    ]
    assert issue["severity"] == "warning"
    assert issue["is_fixable"] is True
    assert issue["translation_key"] == DEVICE_AGENT_UPDATE_REQUIRED_ISSUE


def test_agent_update_up_to_date_clears_repair_issue() -> None:
    entry = FakeEntry(
        runtime_data=FakeRuntimeData(
            agent_update_state=AgentUpdateState(
                state="up_to_date",
                installed_version="0.3.1",
                available_version="0.3.1",
            )
        )
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    assert repair_issue_id(DEVICE_AGENT_UPDATE_REQUIRED_ISSUE, entry.entry_id) in DELETED_ISSUES


def test_unsupported_callback_url_creates_repair_issue() -> None:
    connection_state = C300XConnectionState()
    connection_state.mark_event_subscription_attempt(
        "https://homeassistant.local:8123/api/webhook/private",
        1,
        datetime(2026, 6, 2, tzinfo=UTC),
    )
    entry = FakeEntry(
        runtime_data=FakeRuntimeData(connection_state=connection_state),
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    issue = CREATED_ISSUES[
        repair_issue_id(UNSUPPORTED_CALLBACK_URL_ISSUE, entry.entry_id)
    ]
    assert issue["severity"] == "warning"
    assert issue["translation_key"] == UNSUPPORTED_CALLBACK_URL_ISSUE
    assert issue["translation_placeholders"]["scheme"] == "https"
    assert issue["translation_placeholders"]["host_type"] == "mdns"


def test_clean_callback_url_clears_repair_issue() -> None:
    display_bridge = C300XCallbackDiagnostics()
    display_bridge.mark_callback_attempt(
        "http://192.0.2.10:8123/api/webhook/private",
        datetime(2026, 6, 2, tzinfo=UTC),
    )
    entry = FakeEntry(
        runtime_data=FakeRuntimeData(display_bridge_diagnostics=display_bridge),
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    assert (
        repair_issue_id(UNSUPPORTED_CALLBACK_URL_ISSUE, entry.entry_id)
        in DELETED_ISSUES
    )
