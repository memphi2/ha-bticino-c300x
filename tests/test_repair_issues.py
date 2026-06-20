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
issue_registry.EVENT_REPAIRS_ISSUE_REGISTRY_UPDATED = (
    "repairs_issue_registry_updated"
)
issue_registry.async_create_issue = _create_issue
issue_registry.async_delete_issue = _delete_issue
config_validation.config_entry_only_config_schema = lambda _domain: dict
config_validation.empty_config_schema = lambda _domain: dict
config_validation.ensure_list = lambda value: value if isinstance(value, list) else [value]
config_validation.string = str
config_validation.boolean = bool


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
    CONF_FRONTEND_CARD_SETUP_REPAIR_VERSION,
    CONF_VIDEO_ENABLED,
    FRONTEND_CARD_SETUP_REPAIR_VERSION,
)
from custom_components.bticino_c300x.data import (  # noqa: E402
    C300XCallbackDiagnostics,
    C300XConnectionState,
)
from custom_components.bticino_c300x.repair_issues import (  # noqa: E402
    AGENT_CAPABILITY_MISMATCH_ISSUE,
    ALL_REPAIR_ISSUES,
    DEVICE_AGENT_SELF_TEST_FAILED_ISSUE,
    DEVICE_AGENT_STARTUP_DISABLED_ISSUE,
    DEVICE_AGENT_UI_EVENT_WATCHDOG_ISSUE,
    DEVICE_AGENT_UPDATE_REQUIRED_ISSUE,
    DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE,
    DEVICE_USER_REQUIRED_ISSUE,
    FRONTEND_CARD_SETUP_HINT_ISSUE,
    INVALID_ACTION_MAP_ISSUE,
    MEDIA_SETUP_REPAIR_REQUIRED_ISSUE,
    MEDIA_WATCHDOG_TIMEOUT_ISSUE,
    MISSING_ALARM_ENTITY_ISSUE,
    UNSUPPORTED_CALLBACK_URL_ISSUE,
    _self_test_failure_is_optional_ipv6_only,
    _self_test_repair_action,
    async_clear_entry_repair_issues,
    async_create_media_watchdog_issue,
    async_delete_repair_issue,
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
    agent_info: dict[str, Any] = field(default_factory=dict)
    agent_update_state: AgentUpdateState | None = None
    connection_state: Any | None = None
    event_state: Any = field(
        default_factory=lambda: types.SimpleNamespace(
            smartphone_forwarding_mode="homeassistant"
        )
    )
    display_bridge_diagnostics: Any | None = None
    agent_diagnostics: dict[str, Any] | None = None
    qml_patch_status: dict[str, Any] = field(default_factory=dict)
    device_user_status: dict[str, Any] = field(default_factory=dict)
    self_test_status: dict[str, Any] = field(default_factory=dict)


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
        if "data" in kwargs:
            entry.data = kwargs["data"]
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


def test_clear_and_delete_repair_issue_helpers_ignore_unknown_types() -> None:
    hass = FakeHass()

    async_delete_repair_issue(hass, "entry-1", "unknown")
    assert DELETED_ISSUES == []

    async_clear_entry_repair_issues(hass, "entry-1")

    assert set(DELETED_ISSUES) == {
        repair_issue_id(issue_type, "entry-1") for issue_type in ALL_REPAIR_ISSUES
    }


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


def test_frontend_card_setup_hint_created_after_legacy_dismissal() -> None:
    entry = FakeEntry(
        options={CONF_FRONTEND_CARD_SETUP_DISMISSED: True},
        runtime_data=FakeRuntimeData(
            capabilities={"doorbell_video": {"supported": True}},
        ),
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    issue = CREATED_ISSUES[
        repair_issue_id(FRONTEND_CARD_SETUP_HINT_ISSUE, entry.entry_id)
    ]
    assert issue["is_fixable"] is True
    assert (
        repair_issue_id(FRONTEND_CARD_SETUP_HINT_ISSUE, entry.entry_id)
        not in DELETED_ISSUES
    )


def test_frontend_card_setup_hint_cleared_after_current_repair_handled() -> None:
    entry = FakeEntry(
        data={
            CONF_FRONTEND_CARD_SETUP_DISMISSED: True,
            CONF_FRONTEND_CARD_SETUP_REPAIR_VERSION: (
                FRONTEND_CARD_SETUP_REPAIR_VERSION
            ),
        },
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


def test_frontend_card_setup_hint_cleared_after_current_options_marker() -> None:
    entry = FakeEntry(
        options={
            CONF_FRONTEND_CARD_SETUP_DISMISSED: True,
            CONF_FRONTEND_CARD_SETUP_REPAIR_VERSION: (
                FRONTEND_CARD_SETUP_REPAIR_VERSION
            ),
        },
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


def test_frontend_card_setup_hint_created_when_cards_exist_without_fix_marker() -> None:
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

    issue = CREATED_ISSUES[
        repair_issue_id(FRONTEND_CARD_SETUP_HINT_ISSUE, entry.entry_id)
    ]
    assert issue["is_fixable"] is True


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
    assert issue["is_fixable"] is True
    assert issue["translation_key"] == DEVICE_AGENT_UPDATE_REQUIRED_ISSUE


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


def test_failed_self_test_creates_non_fixable_repair_issue() -> None:
    entry = FakeEntry(
        runtime_data=FakeRuntimeData(
            self_test_status={
                "ok": False,
                "checks": {
                    "firewall": {
                        "ok": False,
                        "reason": "ipv4_media_ports_missing",
                    },
                    "rtsp": {"ok": True, "reason": "rtsp_ready"},
                },
            }
        )
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    issue = CREATED_ISSUES[
        repair_issue_id(DEVICE_AGENT_SELF_TEST_FAILED_ISSUE, entry.entry_id)
    ]
    assert issue["severity"] == "warning"
    assert issue["is_fixable"] is False
    assert issue["translation_key"] == DEVICE_AGENT_SELF_TEST_FAILED_ISSUE
    assert issue["translation_placeholders"]["failed_checks"] == "firewall"
    assert (
        "required IPv4 media and talkback firewall setup"
        in issue["translation_placeholders"]["reasons"]
    )
    assert "ipv4_media_ports_missing" not in issue["translation_placeholders"]["reasons"]
    assert "C300X Firewall switch" in issue["translation_placeholders"]["actions"]
    assert "IPv4 media and talkback ports" in issue["translation_placeholders"]["actions"]


def test_failed_self_test_talkback_points_to_ipv4_firewall_switch() -> None:
    entry = FakeEntry(
        runtime_data=FakeRuntimeData(
            self_test_status={
                "ok": False,
                "checks": {
                    "firewall": {
                        "ok": True,
                        "reason": "media_ports_open",
                    },
                    "talkback_rtp": {
                        "ok": False,
                        "reason": "talkback_rtp_firewall_missing",
                    },
                },
            }
        )
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    issue = CREATED_ISSUES[
        repair_issue_id(DEVICE_AGENT_SELF_TEST_FAILED_ISSUE, entry.entry_id)
    ]
    assert issue["translation_placeholders"]["failed_checks"] == "talkback_rtp"
    assert "required IPv4 firewall setup" in issue["translation_placeholders"]["reasons"]
    assert "talkback_rtp_firewall_missing" not in issue["translation_placeholders"]["reasons"]
    assert "IPv6 firewall switch is only needed" in issue["translation_placeholders"]["actions"]


def test_combined_media_self_test_failure_creates_fixable_media_setup_repair() -> None:
    entry = FakeEntry(
        data={CONF_VIDEO_ENABLED: True},
        runtime_data=FakeRuntimeData(
            connection_state=types.SimpleNamespace(available=True),
            capabilities={
                "doorbell_video": {"supported": True},
                "doorbell_call": {"supported": True},
                "maintenance": {
                    "supported": True,
                    "firewall_apply": True,
                    "device_user_ensure": True,
                },
            },
            self_test_status={
                "ok": False,
                "checks": {
                    "capabilities": {"ok": True},
                    "firewall": {
                        "ok": False,
                        "reason": "ipv4_media_ports_missing",
                    },
                    "rtsp": {"ok": True},
                    "talkback_rtp": {"ok": True},
                    "homeassistant_user": {"ok": False},
                    "device_routing": {"ok": False},
                    "startup": {"ok": True},
                },
            },
        ),
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    issue = CREATED_ISSUES[
        repair_issue_id(MEDIA_SETUP_REPAIR_REQUIRED_ISSUE, entry.entry_id)
    ]
    assert issue["severity"] == "warning"
    assert issue["is_fixable"] is True
    assert issue["translation_key"] == MEDIA_SETUP_REPAIR_REQUIRED_ISSUE
    assert issue["translation_placeholders"]["fixable_checks"] == (
        "firewall, homeassistant_user"
    )


def test_offline_media_readiness_creates_fixable_media_setup_repair() -> None:
    entry = FakeEntry(
        data={CONF_VIDEO_ENABLED: True},
        runtime_data=FakeRuntimeData(
            connection_state=types.SimpleNamespace(available=False),
        ),
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    issue = CREATED_ISSUES[
        repair_issue_id(MEDIA_SETUP_REPAIR_REQUIRED_ISSUE, entry.entry_id)
    ]
    assert issue["is_fixable"] is True
    assert issue["translation_placeholders"]["fixable_checks"] == "agent_reachable"


def test_forwarding_failure_creates_fixable_media_setup_repair() -> None:
    entry = FakeEntry(
        data={CONF_VIDEO_ENABLED: True},
        runtime_data=FakeRuntimeData(
            connection_state=types.SimpleNamespace(available=True),
            capabilities={
                "doorbell_call": {"supported": True},
                "smartphone_forwarding": {"supported": True},
            },
            event_state=types.SimpleNamespace(smartphone_forwarding_mode="smartphone"),
            self_test_status={
                "ok": True,
                "checks": {
                    "capabilities": {"ok": True},
                    "firewall": {"ok": True},
                    "rtsp": {"ok": True},
                    "talkback_rtp": {"ok": True},
                    "homeassistant_user": {"ok": True},
                    "device_routing": {"ok": True},
                    "startup": {"ok": True},
                },
            },
        ),
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    issue = CREATED_ISSUES[
        repair_issue_id(MEDIA_SETUP_REPAIR_REQUIRED_ISSUE, entry.entry_id)
    ]
    assert issue["is_fixable"] is True
    assert issue["translation_placeholders"]["fixable_checks"] == "homeassistant"


def test_callback_readiness_failure_creates_callback_repair_issue() -> None:
    entry = FakeEntry(
        data={CONF_VIDEO_ENABLED: True},
        runtime_data=FakeRuntimeData(
            connection_state=types.SimpleNamespace(
                available=True,
                event_subscription_last_success_at=None,
                event_subscription_last_error="connection refused",
                event_subscription_callback_scheme="https",
                event_subscription_callback_host_type="hostname",
            ),
            capabilities={"doorbell_call": {"supported": True}},
            self_test_status={
                "ok": True,
                "checks": {
                    "capabilities": {"ok": True},
                    "firewall": {"ok": True},
                    "rtsp": {"ok": True},
                    "talkback_rtp": {"ok": True},
                    "homeassistant_user": {"ok": True},
                    "device_routing": {"ok": True},
                    "startup": {"ok": True},
                },
            },
        ),
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    issue = CREATED_ISSUES[
        repair_issue_id(UNSUPPORTED_CALLBACK_URL_ISSUE, entry.entry_id)
    ]
    assert issue["is_fixable"] is True
    assert issue["translation_placeholders"]["source"] == "event subscription"
    assert issue["translation_placeholders"]["scheme"] == "https"


def test_single_media_user_failure_creates_device_user_and_media_repairs() -> None:
    entry = FakeEntry(
        data={CONF_VIDEO_ENABLED: True},
        runtime_data=FakeRuntimeData(
            connection_state=types.SimpleNamespace(available=True),
            capabilities={
                "doorbell_video": {"supported": True},
                "maintenance": {
                    "supported": True,
                    "device_user_ensure": True,
                },
            },
            device_user_status={
                "homeassistant_user_present": False,
                "media_identity_available": True,
                "routes_consistent": False,
            },
            self_test_status={
                "ok": False,
                "checks": {
                    "capabilities": {"ok": True},
                    "firewall": {"ok": True},
                    "rtsp": {"ok": True},
                    "talkback_rtp": {"ok": True},
                    "homeassistant_user": {"ok": False},
                    "device_routing": {"ok": False},
                    "startup": {"ok": True},
                },
            },
        ),
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    assert repair_issue_id(DEVICE_USER_REQUIRED_ISSUE, entry.entry_id) in CREATED_ISSUES
    assert (
        repair_issue_id(MEDIA_SETUP_REPAIR_REQUIRED_ISSUE, entry.entry_id)
        in CREATED_ISSUES
    )


def test_failed_self_test_ignores_optional_ipv6_firewall_only() -> None:
    entry = FakeEntry(
        runtime_data=FakeRuntimeData(
            self_test_status={
                "ok": False,
                "checks": {
                    "firewall": {
                        "ok": False,
                        "reason": "ipv6_media_ports_missing",
                    },
                    "talkback_rtp": {
                        "ok": False,
                        "reason": "talkback_rtp_firewall_missing",
                    },
                },
            }
        )
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    assert (
        repair_issue_id(DEVICE_AGENT_SELF_TEST_FAILED_ISSUE, entry.entry_id)
        in DELETED_ISSUES
    )


def test_self_test_helpers_explain_known_and_unknown_failures() -> None:
    checks = {
        "firewall": {"ok": False, "reason": "ipv6_media_ports_missing"},
    }

    assert (
        _self_test_failure_is_optional_ipv6_only(
            "talkback_rtp",
            "talkback_rtp_firewall_missing",
            {},
        )
        is False
    )
    assert (
        _self_test_failure_is_optional_ipv6_only(
            "talkback_rtp",
            "talkback_rtp_firewall_missing",
            checks,
        )
        is True
    )
    assert (
        _self_test_failure_is_optional_ipv6_only(
            "talkback_rtp",
            "unknown",
            checks,
        )
        is False
    )
    assert "doorbell video is enabled" in _self_test_repair_action("rtsp", "failed")
    assert "media-user setup" in _self_test_repair_action(
        "homeassistant_user",
        "missing",
    )
    assert "media-user setup" in _self_test_repair_action(
        "device_routing",
        "missing",
    )
    assert "startup link" in _self_test_repair_action("startup", "missing")
    assert "Update or reconfigure" in _self_test_repair_action(
        "capabilities",
        "missing",
    )
    assert "IPv4 media and talkback ports" in _self_test_repair_action(
        "firewall",
        "ipv4_media_ports_missing",
    )
    assert "IPv6 is optional" in _self_test_repair_action(
        "firewall",
        "ipv6_media_ports_missing",
    )
    assert _self_test_repair_action("unknown", "missing") is None


def test_ok_self_test_clears_repair_issue() -> None:
    entry = FakeEntry(
        runtime_data=FakeRuntimeData(
            self_test_status={
                "ok": True,
                "checks": {"firewall": {"ok": True, "reason": "media_ports_open"}},
            }
        )
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    assert (
        repair_issue_id(DEVICE_AGENT_SELF_TEST_FAILED_ISSUE, entry.entry_id)
        in DELETED_ISSUES
    )


def test_ui_event_watchdog_creates_repair_issue() -> None:
    entry = FakeEntry(
        runtime_data=FakeRuntimeData(
            agent_diagnostics={
                "ui_event_waiters": 4,
                "ui_event_waiter_capacity": 4,
                "ui_event_waiter_overflows": 2,
            }
        )
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    issue = CREATED_ISSUES[
        repair_issue_id(DEVICE_AGENT_UI_EVENT_WATCHDOG_ISSUE, entry.entry_id)
    ]
    assert issue["severity"] == "warning"
    assert issue["translation_key"] == DEVICE_AGENT_UI_EVENT_WATCHDOG_ISSUE
    assert issue["translation_placeholders"]["capacity"] == "4"
    assert issue["translation_placeholders"]["overflows"] == "2"
    assert issue["translation_placeholders"]["waiters"] == "4"


def test_ui_event_watchdog_ignores_historical_overflow() -> None:
    entry = FakeEntry(
        runtime_data=FakeRuntimeData(
            agent_diagnostics={
                "ui_event_waiters": 0,
                "ui_event_waiter_capacity": 4,
                "ui_event_waiter_overflows": 2,
            }
        )
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    assert (
        repair_issue_id(DEVICE_AGENT_UI_EVENT_WATCHDOG_ISSUE, entry.entry_id)
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
    assert issue["translation_placeholders"]["reason"] == "homeassistant_user_missing"


def test_unavailable_device_user_status_does_not_create_repair_issue() -> None:
    entry = FakeEntry(
        data={CONF_VIDEO_ENABLED: True},
        runtime_data=FakeRuntimeData(
            capabilities={
                "doorbell_video": {"supported": True},
                "maintenance": {
                    "supported": True,
                    "device_user_ensure": True,
                },
            },
            device_user_status={
                "available": False,
                "supported": True,
                "homeassistant_user_present": None,
                "media_identity_available": None,
                "routes_consistent": None,
                "error": "status_failed",
            },
        ),
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    assert repair_issue_id(DEVICE_USER_REQUIRED_ISSUE, entry.entry_id) in DELETED_ISSUES
    assert repair_issue_id(DEVICE_USER_REQUIRED_ISSUE, entry.entry_id) not in CREATED_ISSUES


def test_device_user_with_missing_media_identity_creates_repair_issue() -> None:
    entry = FakeEntry(
        data={CONF_VIDEO_ENABLED: True},
        runtime_data=FakeRuntimeData(
            capabilities={
                "doorbell_video": {"supported": True},
                "maintenance": {"supported": True, "device_user_ensure": True},
            },
            device_user_status={
                "homeassistant_user_present": True,
                "media_identity_available": False,
                "routes_consistent": True,
            },
        ),
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    issue = CREATED_ISSUES[repair_issue_id(DEVICE_USER_REQUIRED_ISSUE, entry.entry_id)]
    assert issue["translation_placeholders"]["reason"] == "media_identity_missing"


def test_device_user_with_missing_device_routing_creates_repair_issue() -> None:
    entry = FakeEntry(
        data={CONF_VIDEO_ENABLED: True},
        runtime_data=FakeRuntimeData(
            capabilities={
                "doorbell_video": {"supported": True},
                "maintenance": {"supported": True, "device_user_ensure": True},
            },
            device_user_status={
                "homeassistant_user_present": True,
                "media_identity_available": True,
                "routes_consistent": True,
                "device_routing_applied": False,
            },
        ),
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    issue = CREATED_ISSUES[repair_issue_id(DEVICE_USER_REQUIRED_ISSUE, entry.entry_id)]
    assert issue["translation_placeholders"]["reason"] == "device_routing_missing"


def test_device_user_with_missing_media_label_clears_repair_issue() -> None:
    entry = FakeEntry(
        data={CONF_VIDEO_ENABLED: True},
        runtime_data=FakeRuntimeData(
            capabilities={
                "home_call": {"supported": True},
                "maintenance": {"supported": True, "device_user_ensure": True},
            },
            device_user_status={
                "homeassistant_user_present": True,
                "media_identity_available": True,
                "routes_consistent": True,
                "device_routing_applied": True,
                "media_user_label_applied": False,
            },
        ),
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    assert repair_issue_id(DEVICE_USER_REQUIRED_ISSUE, entry.entry_id) in DELETED_ISSUES
    assert repair_issue_id(DEVICE_USER_REQUIRED_ISSUE, entry.entry_id) not in CREATED_ISSUES


def test_complete_device_user_status_clears_repair_issue() -> None:
    entry = FakeEntry(
        data={CONF_VIDEO_ENABLED: True},
        runtime_data=FakeRuntimeData(
            capabilities={"doorbell_video": {"supported": True}},
            device_user_status={
                "homeassistant_user_present": True,
                "media_identity_available": True,
                "routes_consistent": True,
                "device_routing_applied": True,
                "media_user_label_applied": True,
            },
        ),
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    assert repair_issue_id(DEVICE_USER_REQUIRED_ISSUE, entry.entry_id) in DELETED_ISSUES
    assert repair_issue_id(DEVICE_USER_REQUIRED_ISSUE, entry.entry_id) not in CREATED_ISSUES


def test_device_user_without_homeassistant_user_creates_repair_issue() -> None:
    entry = FakeEntry(
        data={CONF_VIDEO_ENABLED: True},
        runtime_data=FakeRuntimeData(
            capabilities={
                "doorbell_video": {"supported": True},
                "maintenance": {"supported": True, "device_user_ensure": True},
            },
            device_user_status={
                "homeassistant_user_present": False,
                "media_identity_available": True,
                "routes_consistent": False,
            },
        ),
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    issue = CREATED_ISSUES[repair_issue_id(DEVICE_USER_REQUIRED_ISSUE, entry.entry_id)]
    assert issue["severity"] == "error"
    assert issue["translation_placeholders"]["reason"] == "homeassistant_user_missing"


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


def test_ready_media_setup_clears_media_repair_issue() -> None:
    entry = FakeEntry(
        data={CONF_VIDEO_ENABLED: True},
        runtime_data=FakeRuntimeData(
            connection_state=types.SimpleNamespace(
                available=True,
                event_subscription_last_success_at=datetime(2026, 6, 2, tzinfo=UTC),
            ),
            agent_info={"version": "1.2.3"},
            capabilities={
                "doorbell_video": {"supported": True},
                "doorbell_call": {"supported": True},
            },
            device_user_status={
                "homeassistant_user_present": True,
                "device_routing_applied": True,
                "media_user_label_applied": True,
            },
            self_test_status={
                "ok": True,
                "checks": {
                    "capabilities": {"ok": True},
                    "firewall": {"ok": True},
                    "rtsp": {"ok": True},
                    "talkback_rtp": {"ok": True},
                    "homeassistant_user": {"ok": True},
                    "device_routing": {"ok": True},
                    "startup": {"ok": True},
                },
            },
        ),
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    assert (
        repair_issue_id(MEDIA_SETUP_REPAIR_REQUIRED_ISSUE, entry.entry_id)
        in DELETED_ISSUES
    )


def test_media_setup_with_no_fixable_checks_clears_media_repair_issue() -> None:
    entry = FakeEntry(
        data={CONF_VIDEO_ENABLED: True},
        runtime_data=FakeRuntimeData(
            connection_state=types.SimpleNamespace(available=True),
            capabilities={"doorbell_video": {"supported": True}},
            self_test_status={
                "ok": False,
                "checks": {
                    "capabilities": {"ok": True},
                    "firewall": {"ok": True},
                    "rtsp": {"ok": True},
                    "talkback_rtp": {"ok": True},
                    "homeassistant_user": {"ok": True},
                    "device_routing": {"ok": True},
                    "startup": {"ok": False},
                },
            },
        ),
    )

    async_sync_entry_repair_issues(FakeHass(), entry)

    assert (
        repair_issue_id(MEDIA_SETUP_REPAIR_REQUIRED_ISSUE, entry.entry_id)
        in DELETED_ISSUES
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


def test_media_watchdog_creates_error_repair_issue() -> None:
    entry = FakeEntry()

    async_create_media_watchdog_issue(
        FakeHass(),
        entry,
        reason="agent_cpu_high_95.0_percent_300s",
        cpu_percent=95.0,
        duration_seconds=300,
    )

    issue = CREATED_ISSUES[
        repair_issue_id(MEDIA_WATCHDOG_TIMEOUT_ISSUE, entry.entry_id)
    ]
    assert issue["severity"] == issue_registry.IssueSeverity.ERROR
    assert issue["translation_key"] == MEDIA_WATCHDOG_TIMEOUT_ISSUE
    assert issue["translation_placeholders"]["cpu_percent"] == "95.0"
    assert issue["translation_placeholders"]["duration_seconds"] == "300"


def test_repair_issue_defensive_helpers_cover_edge_paths(monkeypatch) -> None:
    entry = FakeEntry()

    assert repair_issues._callback_problem(  # noqa: SLF001 - targeted helper coverage
        types.SimpleNamespace(runtime_data=None)
    ) is None
    assert repair_issues._media_setup_fixable_checks(  # noqa: SLF001
        ["capabilities", "rtsp"],
        {},
    ) == ["agent_update"]
    assert repair_issues._entry_media_enabled(  # noqa: SLF001
        FakeEntry(
            data={CONF_VIDEO_ENABLED: True},
            options={CONF_VIDEO_ENABLED: False},
        )
    ) is False

    display_bridge = types.SimpleNamespace(
        callback_scheme="https",
        callback_host_type="mdns",
    )
    assert repair_issues._callback_problem(  # noqa: SLF001
        FakeEntry(runtime_data=FakeRuntimeData(display_bridge_diagnostics=display_bridge))
    ) == {
        "source": "display bridge",
        "scheme": "https",
        "host_type": "mdns",
    }

    monkeypatch.setattr(repair_issues, "er", None)
    assert repair_issues._entity_exists(FakeHass(), "sensor.anything") is False  # noqa: SLF001
    repair_issues._mark_frontend_card_setup_dismissed(  # noqa: SLF001
        types.SimpleNamespace(),
        entry,
    )
    assert entry.data == {}
