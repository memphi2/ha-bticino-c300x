"""Home Assistant Repairs issue helpers for BTicino C300X."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .action import ActionValidationError, validate_action_map
from .agent_update import agent_update_repair_placeholders
from .callback_target import callback_target_is_clean_local_http
from .capabilities import capability_is_supported, maintenance_action_is_advertised
from .const import (
    CONF_ACTIONS,
    CONF_ALARM_ENTITY_ID,
    CONF_FRONTEND_CARD_SETUP_DISMISSED,
    CONF_FRONTEND_CARD_SETUP_REPAIR_VERSION,
    CONF_VIDEO_ENABLED,
    DOMAIN,
    FRONTEND_CARD_SETUP_REPAIR_VERSION,
)
from .device_user import device_user_repair_reason
from .entry_types import BticinoC300XConfigEntry
from .media_readiness import media_readiness
from .media_setup import (
    media_setup_fixable_checks,
    media_setup_has_non_device_user_failure,
    media_setup_has_only_device_user_failures,
    summarize_self_test_failures,
)

er: Any
try:
    from homeassistant.helpers import entity_registry as er
except (ImportError, ModuleNotFoundError):  # pragma: no cover - local test stubs
    er = None

INVALID_ACTION_MAP_ISSUE = "invalid_action_map"
MISSING_ALARM_ENTITY_ISSUE = "missing_alarm_entity"
FRONTEND_CARD_SETUP_HINT_ISSUE = "frontend_card_setup_hint"
AGENT_CAPABILITY_MISMATCH_ISSUE = "agent_capability_mismatch"
DEVICE_AGENT_UPDATE_REQUIRED_ISSUE = "device_agent_update_required"
DEVICE_AGENT_STARTUP_DISABLED_ISSUE = "device_agent_startup_disabled"
DEVICE_AGENT_SELF_TEST_FAILED_ISSUE = "device_agent_self_test_failed"
DEVICE_AGENT_UI_EVENT_WATCHDOG_ISSUE = "device_agent_ui_event_watchdog"
UNSUPPORTED_CALLBACK_URL_ISSUE = "unsupported_callback_url"
DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE = "device_core_qml_hook_required"
DEVICE_USER_REQUIRED_ISSUE = "device_user_required"
MEDIA_SETUP_REPAIR_REQUIRED_ISSUE = "media_setup_repair_required"
MEDIA_WATCHDOG_TIMEOUT_ISSUE = "media_watchdog_timeout"
ALL_REPAIR_ISSUES = frozenset(
    {
        INVALID_ACTION_MAP_ISSUE,
        MISSING_ALARM_ENTITY_ISSUE,
        FRONTEND_CARD_SETUP_HINT_ISSUE,
        AGENT_CAPABILITY_MISMATCH_ISSUE,
        DEVICE_AGENT_UPDATE_REQUIRED_ISSUE,
        DEVICE_AGENT_STARTUP_DISABLED_ISSUE,
        DEVICE_AGENT_SELF_TEST_FAILED_ISSUE,
        DEVICE_AGENT_UI_EVENT_WATCHDOG_ISSUE,
        UNSUPPORTED_CALLBACK_URL_ISSUE,
        DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE,
        DEVICE_USER_REQUIRED_ISSUE,
        MEDIA_SETUP_REPAIR_REQUIRED_ISSUE,
        MEDIA_WATCHDOG_TIMEOUT_ISSUE,
    }
)


def repair_issue_id(issue_type: str, entry_id: str) -> str:
    """Return the stable Repairs issue ID for one config entry and issue type."""

    return f"{issue_type}_{entry_id}"


@callback
def async_sync_entry_repair_issues(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
) -> None:
    """Synchronize actionable Repairs issues for a loaded config entry."""

    _sync_action_map_issue(hass, entry)
    _sync_missing_alarm_entity_issue(hass, entry)
    _sync_frontend_card_setup_hint_issue(hass, entry)
    _sync_agent_capability_issue(hass, entry)
    _sync_device_agent_update_issue(hass, entry)
    _sync_device_agent_startup_issue(hass, entry)
    _sync_device_agent_self_test_issue(hass, entry)
    _sync_device_agent_ui_event_watchdog_issue(hass, entry)
    _sync_unsupported_callback_url_issue(hass, entry)
    _sync_device_core_qml_hook_issue(hass, entry)
    _sync_device_user_issue(hass, entry)
    _sync_media_setup_repair_issue(hass, entry)


@callback
def async_clear_entry_repair_issues(
    hass: HomeAssistant,
    entry_id: str,
) -> None:
    """Clear all Repairs issues for a config entry."""

    for issue_type in ALL_REPAIR_ISSUES:
        async_delete_repair_issue(hass, entry_id, issue_type)


@callback
def async_delete_repair_issue(
    hass: HomeAssistant,
    entry_id: str,
    issue_type: str,
) -> None:
    """Delete one C300X Repairs issue."""

    if issue_type not in ALL_REPAIR_ISSUES:
        return
    ir.async_delete_issue(
        hass=hass,
        domain=DOMAIN,
        issue_id=repair_issue_id(issue_type, entry_id),
    )


@callback
def async_create_media_watchdog_issue(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
    *,
    reason: str,
    cpu_percent: float | None,
    duration_seconds: int,
) -> None:
    """Create a Repairs issue after HA stopped media because of device CPU load."""

    cpu_text = "unknown" if cpu_percent is None else f"{cpu_percent:.1f}"
    _create_issue(
        hass,
        entry,
        MEDIA_WATCHDOG_TIMEOUT_ISSUE,
        severity=ir.IssueSeverity.ERROR,
        placeholders={
            "reason": reason,
            "cpu_percent": cpu_text,
            "duration_seconds": str(duration_seconds),
        },
    )


def _sync_action_map_issue(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> None:
    try:
        validate_action_map(entry.options.get(CONF_ACTIONS, {}))
    except ActionValidationError as err:
        _create_issue(
            hass,
            entry,
            INVALID_ACTION_MAP_ISSUE,
            severity=ir.IssueSeverity.ERROR,
            placeholders={"error": str(err)},
        )
        return
    async_delete_repair_issue(hass, entry.entry_id, INVALID_ACTION_MAP_ISSUE)


def _sync_missing_alarm_entity_issue(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> None:
    alarm_entity_id = _configured_alarm_entity_id(entry)
    if not alarm_entity_id:
        async_delete_repair_issue(hass, entry.entry_id, MISSING_ALARM_ENTITY_ISSUE)
        return
    if _entity_exists(hass, alarm_entity_id):
        async_delete_repair_issue(hass, entry.entry_id, MISSING_ALARM_ENTITY_ISSUE)
        return
    _create_issue(
        hass,
        entry,
        MISSING_ALARM_ENTITY_ISSUE,
        severity=ir.IssueSeverity.WARNING,
        placeholders={"entity_id": alarm_entity_id},
    )


def _sync_frontend_card_setup_hint_issue(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> None:
    capabilities = getattr(entry.runtime_data, "capabilities", {})
    if not isinstance(capabilities, dict) or not (
        capability_is_supported(capabilities, "doorbell_video")
        or capability_is_supported(capabilities, "home_call")
    ):
        async_delete_repair_issue(hass, entry.entry_id, FRONTEND_CARD_SETUP_HINT_ISSUE)
        return
    if _frontend_card_setup_repair_handled(entry):
        async_delete_repair_issue(hass, entry.entry_id, FRONTEND_CARD_SETUP_HINT_ISSUE)
        return
    _create_issue(
        hass,
        entry,
        FRONTEND_CARD_SETUP_HINT_ISSUE,
        severity=ir.IssueSeverity.WARNING,
        is_fixable=True,
    )


def _sync_agent_capability_issue(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> None:
    connection_state = getattr(entry.runtime_data, "connection_state", None)
    if connection_state is not None and not getattr(connection_state, "available", True):
        async_delete_repair_issue(
            hass,
            entry.entry_id,
            AGENT_CAPABILITY_MISMATCH_ISSUE,
        )
        return
    capabilities = getattr(entry.runtime_data, "capabilities", {})
    if isinstance(capabilities, dict) and capabilities:
        async_delete_repair_issue(
            hass,
            entry.entry_id,
            AGENT_CAPABILITY_MISMATCH_ISSUE,
        )
        return
    _create_issue(
        hass,
        entry,
        AGENT_CAPABILITY_MISMATCH_ISSUE,
        severity=ir.IssueSeverity.ERROR,
        is_fixable=True,
        translation_key=DEVICE_AGENT_UPDATE_REQUIRED_ISSUE,
        placeholders=agent_update_repair_placeholders(
            getattr(entry.runtime_data, "agent_update_state", None),
            entry.runtime_data,
        ),
    )


def _sync_device_agent_update_issue(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> None:
    update_state = getattr(entry.runtime_data, "agent_update_state", None)
    if update_state is None or not getattr(update_state, "update_required", False):
        async_delete_repair_issue(hass, entry.entry_id, DEVICE_AGENT_UPDATE_REQUIRED_ISSUE)
        return
    _create_issue(
        hass,
        entry,
        DEVICE_AGENT_UPDATE_REQUIRED_ISSUE,
        severity=ir.IssueSeverity.WARNING,
        is_fixable=getattr(update_state, "repair_fixable", False),
        placeholders=agent_update_repair_placeholders(update_state, entry.runtime_data),
    )


def _sync_device_agent_startup_issue(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> None:
    runtime_data = getattr(entry, "runtime_data", None)
    diagnostics = getattr(runtime_data, "agent_diagnostics", None)
    if not isinstance(diagnostics, Mapping):
        async_delete_repair_issue(
            hass,
            entry.entry_id,
            DEVICE_AGENT_STARTUP_DISABLED_ISSUE,
        )
        return
    if diagnostics.get("agent_init_link_ok") is not False:
        async_delete_repair_issue(
            hass,
            entry.entry_id,
            DEVICE_AGENT_STARTUP_DISABLED_ISSUE,
        )
        return
    _create_issue(
        hass,
        entry,
        DEVICE_AGENT_STARTUP_DISABLED_ISSUE,
        severity=ir.IssueSeverity.WARNING,
    )


def _sync_device_agent_self_test_issue(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> None:
    runtime_data = getattr(entry, "runtime_data", None)
    connection_state = getattr(runtime_data, "connection_state", None)
    if connection_state is not None and not getattr(connection_state, "available", True):
        async_delete_repair_issue(
            hass,
            entry.entry_id,
            DEVICE_AGENT_SELF_TEST_FAILED_ISSUE,
        )
        return
    status = getattr(runtime_data, "self_test_status", None)
    if not isinstance(status, Mapping) or status.get("ok") is not False:
        async_delete_repair_issue(
            hass,
            entry.entry_id,
            DEVICE_AGENT_SELF_TEST_FAILED_ISSUE,
        )
        return
    checks = status.get("checks")
    failed: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    if isinstance(checks, Mapping):
        summary = summarize_self_test_failures(checks)
        failed = summary.failed
        reasons = summary.reasons
        actions = summary.actions
    if not failed:
        async_delete_repair_issue(
            hass,
            entry.entry_id,
            DEVICE_AGENT_SELF_TEST_FAILED_ISSUE,
        )
        return
    _create_issue(
        hass,
        entry,
        DEVICE_AGENT_SELF_TEST_FAILED_ISSUE,
        severity=ir.IssueSeverity.WARNING,
        placeholders={
            "failed_checks": ", ".join(failed) if failed else "unknown",
            "reasons": "; ".join(reasons) if reasons else "unknown",
            "actions": "; ".join(actions)
            if actions
            else "Check the C300X device-agent diagnostic entities and reload the integration after fixing the device-agent setup.",
        },
    )


def _sync_device_agent_ui_event_watchdog_issue(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
) -> None:
    runtime_data = getattr(entry, "runtime_data", None)
    diagnostics = getattr(runtime_data, "agent_diagnostics", None)
    if not isinstance(diagnostics, Mapping):
        async_delete_repair_issue(
            hass,
            entry.entry_id,
            DEVICE_AGENT_UI_EVENT_WATCHDOG_ISSUE,
        )
        return
    waiters = diagnostics.get("ui_event_waiters")
    capacity = diagnostics.get("ui_event_waiter_capacity")
    active_saturation = (
        isinstance(waiters, int)
        and isinstance(capacity, int)
        and capacity > 0
        and waiters >= capacity
    )
    if not active_saturation:
        async_delete_repair_issue(
            hass,
            entry.entry_id,
            DEVICE_AGENT_UI_EVENT_WATCHDOG_ISSUE,
        )
        return
    overflows = diagnostics.get("ui_event_waiter_overflows")
    _create_issue(
        hass,
        entry,
        DEVICE_AGENT_UI_EVENT_WATCHDOG_ISSUE,
        severity=ir.IssueSeverity.WARNING,
        placeholders={
            "overflows": str(overflows) if isinstance(overflows, int) else "unknown",
            "waiters": str(waiters),
            "capacity": str(capacity),
        },
    )


def _sync_unsupported_callback_url_issue(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
) -> None:
    callback_problem = _callback_problem(entry)
    if callback_problem is None:
        async_delete_repair_issue(hass, entry.entry_id, UNSUPPORTED_CALLBACK_URL_ISSUE)
        return
    _create_issue(
        hass,
        entry,
        UNSUPPORTED_CALLBACK_URL_ISSUE,
        severity=ir.IssueSeverity.WARNING,
        is_fixable=True,
        placeholders=callback_problem,
    )


def _sync_device_core_qml_hook_issue(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> None:
    runtime_data = getattr(entry, "runtime_data", None)
    connection_state = getattr(runtime_data, "connection_state", None)
    if connection_state is not None and not getattr(connection_state, "available", True):
        async_delete_repair_issue(
            hass,
            entry.entry_id,
            DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE,
        )
        return
    if not _entry_media_enabled(entry):
        async_delete_repair_issue(
            hass,
            entry.entry_id,
            DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE,
        )
        return
    capabilities = getattr(runtime_data, "capabilities", {})
    if not maintenance_action_is_advertised(capabilities, "qml_core_patch"):
        async_delete_repair_issue(
            hass,
            entry.entry_id,
            DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE,
        )
        return
    status = getattr(runtime_data, "qml_patch_status", None)
    core_state = "unknown"
    missing = False
    if isinstance(status, dict):
        core_state = str(status.get("core_state") or "").strip().lower() or "unknown"
        missing = status.get("core_patched") is False or core_state in {
            "original",
            "partial",
        }
    diagnostics = getattr(runtime_data, "qml_patch_diagnostics", None)
    failed = bool(getattr(diagnostics, "last_error", None))
    if not missing and not failed:
        async_delete_repair_issue(
            hass,
            entry.entry_id,
            DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE,
        )
        return
    _create_issue(
        hass,
        entry,
        DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE,
        severity=ir.IssueSeverity.WARNING,
        is_fixable=True,
        placeholders={"core_state": core_state},
    )


def _sync_device_user_issue(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> None:
    runtime_data = getattr(entry, "runtime_data", None)
    connection_state = getattr(runtime_data, "connection_state", None)
    if connection_state is not None and not getattr(connection_state, "available", True):
        async_delete_repair_issue(hass, entry.entry_id, DEVICE_USER_REQUIRED_ISSUE)
        return
    if not _entry_media_enabled(entry):
        async_delete_repair_issue(hass, entry.entry_id, DEVICE_USER_REQUIRED_ISSUE)
        return
    capabilities = getattr(runtime_data, "capabilities", {})
    if not (
        capability_is_supported(capabilities, "doorbell_video")
        or capability_is_supported(capabilities, "home_call")
    ):
        async_delete_repair_issue(hass, entry.entry_id, DEVICE_USER_REQUIRED_ISSUE)
        return
    status = getattr(runtime_data, "device_user_status", None)
    if not isinstance(status, dict) or not status:
        async_delete_repair_issue(hass, entry.entry_id, DEVICE_USER_REQUIRED_ISSUE)
        return
    if status.get("available") is False:
        async_delete_repair_issue(hass, entry.entry_id, DEVICE_USER_REQUIRED_ISSUE)
        return

    reason = device_user_repair_reason(status)
    if reason is None:
        async_delete_repair_issue(hass, entry.entry_id, DEVICE_USER_REQUIRED_ISSUE)
        return
    readiness = media_readiness(entry)
    failed = readiness.get("failed_checks")
    if media_setup_has_non_device_user_failure(failed):
        async_delete_repair_issue(hass, entry.entry_id, DEVICE_USER_REQUIRED_ISSUE)
        return
    _create_issue(
        hass,
        entry,
        DEVICE_USER_REQUIRED_ISSUE,
        severity=ir.IssueSeverity.ERROR,
        is_fixable=maintenance_action_is_advertised(capabilities, "device_user_ensure"),
        placeholders={"reason": reason},
    )


def _sync_media_setup_repair_issue(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> None:
    runtime_data = getattr(entry, "runtime_data", None)
    if not _entry_media_enabled(entry):
        async_delete_repair_issue(
            hass,
            entry.entry_id,
            MEDIA_SETUP_REPAIR_REQUIRED_ISSUE,
        )
        return
    readiness = media_readiness(entry)
    failed = readiness.get("failed_checks")
    if readiness.get("status") not in {"blocked", "unavailable"} or not isinstance(
        failed,
        list,
    ):
        async_delete_repair_issue(
            hass,
            entry.entry_id,
            MEDIA_SETUP_REPAIR_REQUIRED_ISSUE,
        )
        return
    capabilities = getattr(runtime_data, "capabilities", {})
    if media_setup_has_only_device_user_failures(failed):
        async_delete_repair_issue(
            hass,
            entry.entry_id,
            MEDIA_SETUP_REPAIR_REQUIRED_ISSUE,
        )
        return
    fixable_checks = media_setup_fixable_checks(failed, capabilities)
    if not fixable_checks:
        async_delete_repair_issue(
            hass,
            entry.entry_id,
            MEDIA_SETUP_REPAIR_REQUIRED_ISSUE,
        )
        return
    _create_issue(
        hass,
        entry,
        MEDIA_SETUP_REPAIR_REQUIRED_ISSUE,
        severity=ir.IssueSeverity.WARNING,
        is_fixable=True,
        placeholders={
            "failed_checks": ", ".join(str(check) for check in failed),
            "fixable_checks": ", ".join(fixable_checks),
            "recommended_action": str(readiness.get("recommended_action") or "unknown"),
        },
    )


def _callback_problem(entry: BticinoC300XConfigEntry) -> dict[str, str] | None:
    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is None:
        return None
    readiness = media_readiness(entry)
    failed = readiness.get("failed_checks")
    if isinstance(failed, list) and "callback_url" in failed:
        connection_state = getattr(runtime_data, "connection_state", None)
        return {
            "source": "event subscription",
            "scheme": str(
                getattr(
                    connection_state,
                    "event_subscription_callback_scheme",
                    None,
                )
                or "unknown"
            ),
            "host_type": str(
                getattr(
                    connection_state,
                    "event_subscription_callback_host_type",
                    None,
                )
                or "unknown"
            ),
        }
    checks = (
        (
            "event subscription",
            getattr(runtime_data, "connection_state", None),
            "event_subscription_callback_scheme",
            "event_subscription_callback_host_type",
        ),
        (
            "display bridge",
            getattr(runtime_data, "display_bridge_diagnostics", None),
            "callback_scheme",
            "callback_host_type",
        ),
    )
    for source, holder, scheme_attr, host_type_attr in checks:
        if holder is None:
            continue
        scheme = getattr(holder, scheme_attr, None)
        host_type = getattr(holder, host_type_attr, None)
        clean = callback_target_is_clean_local_http(scheme, host_type)
        if clean is False:
            return {
                "source": source,
                "scheme": str(scheme or "missing"),
                "host_type": str(host_type or "unknown"),
            }
    return None


def _create_issue(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
    issue_type: str,
    *,
    severity: ir.IssueSeverity,
    is_fixable: bool = False,
    translation_key: str | None = None,
    placeholders: dict[str, str] | None = None,
) -> None:
    translation_placeholders = {
        "entry_title": str(getattr(entry, "title", "") or entry.entry_id),
    }
    if placeholders:
        translation_placeholders.update(placeholders)
    ir.async_create_issue(
        hass=hass,
        domain=DOMAIN,
        issue_id=repair_issue_id(issue_type, entry.entry_id),
        is_fixable=is_fixable,
        is_persistent=False,
        severity=severity,
        translation_key=translation_key or issue_type,
        translation_placeholders=translation_placeholders,
        data={"entry_id": entry.entry_id, "issue_type": issue_type},
    )


def _configured_alarm_entity_id(entry: BticinoC300XConfigEntry) -> str:
    value = entry.options.get(CONF_ALARM_ENTITY_ID) or entry.data.get(CONF_ALARM_ENTITY_ID)
    return value.strip() if isinstance(value, str) else ""


def _entry_media_enabled(entry: BticinoC300XConfigEntry) -> bool:
    options = getattr(entry, "options", {})
    data = getattr(entry, "data", {})
    if isinstance(options, dict) and CONF_VIDEO_ENABLED in options:
        return bool(options[CONF_VIDEO_ENABLED])
    return bool(data.get(CONF_VIDEO_ENABLED)) if isinstance(data, dict) else False


def _entity_exists(hass: HomeAssistant, entity_id: str) -> bool:
    if _registry_entity_exists(hass, entity_id):
        return True
    states = getattr(hass, "states", None)
    try:
        return states is not None and states.get(entity_id) is not None
    except Exception:  # noqa: BLE001 - defensive against early setup test stubs
        return False


def _registry_entity_exists(hass: HomeAssistant, entity_id: str) -> bool:
    if er is None:
        return False
    try:
        registry = er.async_get(hass)
    except Exception:  # noqa: BLE001 - entity registry may be unavailable in tests
        return False
    return registry.async_get(entity_id) is not None


def _frontend_card_setup_repair_handled(entry: BticinoC300XConfigEntry) -> bool:
    """Return true when this Lovelace card repair generation was handled."""

    data_version = entry.data.get(CONF_FRONTEND_CARD_SETUP_REPAIR_VERSION)
    options_version = entry.options.get(CONF_FRONTEND_CARD_SETUP_REPAIR_VERSION)
    return (
        data_version == FRONTEND_CARD_SETUP_REPAIR_VERSION
        or options_version == FRONTEND_CARD_SETUP_REPAIR_VERSION
    )


def _mark_frontend_card_setup_dismissed(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
) -> None:
    """Persist that the Lovelace card setup hint has been handled."""

    if _frontend_card_setup_repair_handled(entry):
        return
    config_entries = getattr(hass, "config_entries", None)
    if config_entries is None or not hasattr(config_entries, "async_update_entry"):
        return
    config_entries.async_update_entry(
        entry,
        data={
            **dict(entry.data),
            CONF_FRONTEND_CARD_SETUP_DISMISSED: True,
            CONF_FRONTEND_CARD_SETUP_REPAIR_VERSION: (
                FRONTEND_CARD_SETUP_REPAIR_VERSION
            ),
        },
    )
