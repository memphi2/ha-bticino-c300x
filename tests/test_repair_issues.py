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
entity_registry.EVENT_ENTITY_REGISTRY_UPDATED = "entity_registry_updated"
entity_registry.EventEntityRegistryUpdatedData = dict

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
    CONF_FRONTEND_CARD_SETUP_DISMISSED,
    CONF_VIDEO_ENABLED,
)
from custom_components.bticino_c300x.data import (  # noqa: E402
    C300XCallbackDiagnostics,
    C300XConnectionState,
)
from custom_components.bticino_c300x.repair_issues import (  # noqa: E402
    AGENT_CAPABILITY_MISMATCH_ISSUE,
    DEVICE_AGENT_STARTUP_DISABLED_ISSUE,
    DEVICE_AGENT_UPDATE_REQUIRED_ISSUE,
    DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE,
    DEVICE_USER_REQUIRED_ISSUE,
    FRONTEND_CARD_SETUP_HINT_ISSUE,
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
    agent_diagnostics: dict[str, Any] | None = None
    qml_patch_status: dict[str, Any] = field(default_factory=dict)
    device_user_status: dict[str, Any] = field(default_factory=dict)


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

    def async_get_entity_id(
        self,
        domain: str,
        platform: str,
        unique_id: str,
    ) -> str | None:
        if (
            domain == "camera"
            and platform == "bticino_c300x"
            and unique_id == "entry-1_doorbell_camera"
        ):
            return "camera.bticino_c300x_doorbell_camera"
        return None


@dataclass(slots=True)
class FakeConfigEntries:
    def async_update_entry(self, entry: Any, **kwargs: Any) -> None:
        if "options" in kwargs:
            entry.options = kwargs["options"]


@dataclass(slots=True)
class FakeHass:
    states: FakeStates = field(default_factory=FakeStates)
    entity_registry: FakeEntityRegistry = field(default_factory=FakeEntityRegistry)
    data: dict[str, Any] = field(default_factory=dict)
    config_entries: FakeConfigEntries = field(default_factory=FakeConfigEntries)


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


def test_frontend_card_setup_hint_created_for_video_capability() -> None:
    entry = FakeEntry(
        runtime_data=FakeRuntimeData(
            capabilities={"doorbell_video": {"supported": True}},
        )
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    issue = CREATED_ISSUES[
        repair_issue_id(FRONTEND_CARD_SETUP_HINT_ISSUE, entry.entry_id)
    ]
    assert issue["severity"] == "warning"
    assert issue["is_fixable"] is True
    assert issue["translation_key"] == FRONTEND_CARD_SETUP_HINT_ISSUE


def test_frontend_card_setup_hint_cleared_after_dismissed() -> None:
    entry = FakeEntry(
        options={CONF_FRONTEND_CARD_SETUP_DISMISSED: True},
        runtime_data=FakeRuntimeData(
            capabilities={"doorbell_video": {"supported": True}},
        ),
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    assert (
        repair_issue_id(FRONTEND_CARD_SETUP_HINT_ISSUE, entry.entry_id)
        in DELETED_ISSUES
    )
    assert CREATED_ISSUES == {}


def test_frontend_card_setup_hint_cleared_when_cards_exist(monkeypatch) -> None:
    components = types.ModuleType("homeassistant.components")
    components.__path__ = []
    lovelace_package = types.ModuleType("homeassistant.components.lovelace")
    lovelace_package.__path__ = []
    lovelace_const = types.ModuleType("homeassistant.components.lovelace.const")
    lovelace_const.LOVELACE_DATA = "lovelace"
    lovelace_const.MODE_STORAGE = "storage"
    monkeypatch.setitem(sys.modules, "homeassistant.components", components)
    monkeypatch.setitem(sys.modules, "homeassistant.components.lovelace", lovelace_package)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.lovelace.const",
        lovelace_const,
    )
    entry = FakeEntry(
        runtime_data=FakeRuntimeData(
            capabilities={"doorbell_video": {"supported": True}},
        )
    )
    dashboard = types.SimpleNamespace(
        mode="storage",
        config={
            "views": [
                {
                    "sections": [
                        {
                            "cards": [
                                {
                                    "type": "custom:c300x-doorbell-call-card",
                                    "entity": "camera.bticino_c300x_doorbell_camera",
                                    "mode": "home_call",
                                },
                                {
                                    "type": "custom:c300x-doorbell-call-card",
                                    "entity": "camera.bticino_c300x_doorbell_camera",
                                },
                            ]
                        }
                    ]
                }
            ]
        },
    )
    hass = FakeHass(data={"lovelace": types.SimpleNamespace(dashboards={None: dashboard})})

    async_sync_entry_repair_issues(hass, entry)

    assert entry.options[CONF_FRONTEND_CARD_SETUP_DISMISSED] is True
    assert (
        repair_issue_id(FRONTEND_CARD_SETUP_HINT_ISSUE, entry.entry_id)
        in DELETED_ISSUES
    )
    assert CREATED_ISSUES == {}


def test_frontend_card_setup_hint_cleared_without_video_or_home_call() -> None:
    entry = FakeEntry(runtime_data=FakeRuntimeData(capabilities={"doorbell_events": True}))

    async_sync_entry_repair_issues(FakeHass(), entry)

    assert (
        repair_issue_id(FRONTEND_CARD_SETUP_HINT_ISSUE, entry.entry_id)
        in DELETED_ISSUES
    )


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
                installed_bundle_hash="sha256:old-bundle",
                available_bundle_hash="sha256:new-bundle",
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
    assert issue["translation_placeholders"]["available_bundle_hash"] == "sha256:new-b"
    assert issue["translation_placeholders"]["update_path"] == "self-update"
    assert issue["translation_placeholders"]["qml_patch_status"] == "unknown"


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


def test_missing_agent_startup_link_creates_repair_issue() -> None:
    entry = FakeEntry(
        runtime_data=FakeRuntimeData(
            agent_diagnostics={
                "agent_init_script_present": True,
                "agent_init_link_ok": False,
            }
        )
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    issue = CREATED_ISSUES[
        repair_issue_id(DEVICE_AGENT_STARTUP_DISABLED_ISSUE, entry.entry_id)
    ]
    assert issue["severity"] == "warning"
    assert issue["translation_key"] == DEVICE_AGENT_STARTUP_DISABLED_ISSUE


def test_agent_startup_link_ok_clears_repair_issue() -> None:
    entry = FakeEntry(
        runtime_data=FakeRuntimeData(
            agent_diagnostics={
                "agent_init_script_present": True,
                "agent_init_link_ok": True,
            }
        )
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    assert (
        repair_issue_id(DEVICE_AGENT_STARTUP_DISABLED_ISSUE, entry.entry_id)
        in DELETED_ISSUES
    )


def test_missing_core_qml_hook_creates_fixable_repair_issue() -> None:
    entry = FakeEntry(
        data={CONF_VIDEO_ENABLED: True},
        runtime_data=FakeRuntimeData(
            capabilities={
                "maintenance": {
                    "supported": True,
                    "qml_core_patch": True,
                }
            },
            qml_patch_status={
                "available": True,
                "patched": False,
                "state": "original",
                "core_patched": False,
                "core_state": "original",
            }
        )
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    issue = CREATED_ISSUES[
        repair_issue_id(DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE, entry.entry_id)
    ]
    assert issue["severity"] == "warning"
    assert issue["is_fixable"] is True
    assert issue["translation_key"] == DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE
    assert issue["translation_placeholders"]["core_state"] == "original"


def test_missing_core_qml_hook_without_supported_action_clears_repair_issue() -> None:
    entry = FakeEntry(
        data={CONF_VIDEO_ENABLED: True},
        runtime_data=FakeRuntimeData(
            capabilities={
                "maintenance": {
                    "supported": True,
                    "qml_patch": True,
                }
            },
            qml_patch_status={
                "available": True,
                "patched": False,
                "state": "original",
                "core_patched": False,
                "core_state": "original",
            },
        ),
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    issue_id = repair_issue_id(DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE, entry.entry_id)
    assert issue_id not in CREATED_ISSUES
    assert issue_id in DELETED_ISSUES


def test_present_core_qml_hook_clears_repair_issue() -> None:
    entry = FakeEntry(
        data={CONF_VIDEO_ENABLED: True},
        runtime_data=FakeRuntimeData(
            capabilities={
                "maintenance": {
                    "supported": True,
                    "qml_core_patch": True,
                }
            },
            qml_patch_status={
                "available": True,
                "patched": False,
                "state": "original",
                "core_patched": True,
                "core_state": "patched",
            }
        )
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    assert (
        repair_issue_id(DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE, entry.entry_id)
        in DELETED_ISSUES
    )


def test_missing_device_user_media_identity_creates_repair_issue() -> None:
    entry = FakeEntry(
        data={CONF_VIDEO_ENABLED: True},
        runtime_data=FakeRuntimeData(
            capabilities={
                "doorbell_video": {"supported": True},
                "home_call": {"supported": True},
                "maintenance": {
                    "supported": True,
                    "device_user_ensure": True,
                },
            },
            device_user_status={
                "app_user_present": False,
                "homeassistant_user_present": False,
                "media_identity_available": False,
                "routes_consistent": False,
            },
        ),
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    issue = CREATED_ISSUES[repair_issue_id(DEVICE_USER_REQUIRED_ISSUE, entry.entry_id)]
    assert issue["severity"] == "error"
    assert issue["is_fixable"] is True
    assert issue["translation_key"] == DEVICE_USER_REQUIRED_ISSUE
    assert issue["translation_placeholders"]["reason"] == "media_identity_missing"


def test_device_user_app_fallback_without_homeassistant_user_clears_issue() -> None:
    entry = FakeEntry(
        data={CONF_VIDEO_ENABLED: True},
        runtime_data=FakeRuntimeData(
            capabilities={"doorbell_video": {"supported": True}},
            device_user_status={
                "app_user_present": True,
                "homeassistant_user_present": False,
                "media_identity_available": True,
                "routes_consistent": False,
            },
        ),
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    assert repair_issue_id(DEVICE_USER_REQUIRED_ISSUE, entry.entry_id) in DELETED_ISSUES
    assert repair_issue_id(DEVICE_USER_REQUIRED_ISSUE, entry.entry_id) not in CREATED_ISSUES


def test_homeassistant_user_with_incomplete_routes_creates_repair_issue() -> None:
    entry = FakeEntry(
        data={CONF_VIDEO_ENABLED: True},
        runtime_data=FakeRuntimeData(
            capabilities={
                "home_call": {"supported": True},
                "maintenance": {
                    "supported": True,
                    "device_user_ensure": True,
                },
            },
            device_user_status={
                "app_user_present": True,
                "homeassistant_user_present": True,
                "media_identity_available": True,
                "routes_consistent": False,
            },
        ),
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    issue = CREATED_ISSUES[repair_issue_id(DEVICE_USER_REQUIRED_ISSUE, entry.entry_id)]
    assert issue["severity"] == "error"
    assert issue["is_fixable"] is True
    assert issue["translation_placeholders"]["reason"] == (
        "homeassistant_routes_inconsistent"
    )


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
    assert issue["is_fixable"] is True
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
