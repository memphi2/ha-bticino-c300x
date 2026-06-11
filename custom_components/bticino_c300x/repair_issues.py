"""Home Assistant Repairs issue helpers for BTicino C300X."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

try:
    from homeassistant.helpers import entity_registry as er
except (ImportError, ModuleNotFoundError):  # pragma: no cover - local test stubs
    er = None

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

INVALID_ACTION_MAP_ISSUE = "invalid_action_map"
MISSING_ALARM_ENTITY_ISSUE = "missing_alarm_entity"
FRONTEND_CARD_SETUP_HINT_ISSUE = "frontend_card_setup_hint"
AGENT_CAPABILITY_MISMATCH_ISSUE = "agent_capability_mismatch"
DEVICE_AGENT_UPDATE_REQUIRED_ISSUE = "device_agent_update_required"
DEVICE_AGENT_STARTUP_DISABLED_ISSUE = "device_agent_startup_disabled"
UNSUPPORTED_CALLBACK_URL_ISSUE = "unsupported_callback_url"
DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE = "device_core_qml_hook_required"
DEVICE_USER_REQUIRED_ISSUE = "device_user_required"
ALL_REPAIR_ISSUES = frozenset(
    {
        INVALID_ACTION_MAP_ISSUE,
        MISSING_ALARM_ENTITY_ISSUE,
        FRONTEND_CARD_SETUP_HINT_ISSUE,
        AGENT_CAPABILITY_MISMATCH_ISSUE,
        DEVICE_AGENT_UPDATE_REQUIRED_ISSUE,
        DEVICE_AGENT_STARTUP_DISABLED_ISSUE,
        UNSUPPORTED_CALLBACK_URL_ISSUE,
        DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE,
        DEVICE_USER_REQUIRED_ISSUE,
    }
)


def repair_issue_id(issue_type: str, entry_id: str) -> str:
    """Return the stable Repairs issue ID for one config entry and issue type."""

    return f"{issue_type}_{entry_id}"


@callback
def async_sync_entry_repair_issues(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Synchronize actionable Repairs issues for a loaded config entry."""

    _sync_action_map_issue(hass, entry)
    _sync_missing_alarm_entity_issue(hass, entry)
    _sync_frontend_card_setup_hint_issue(hass, entry)
    _sync_agent_capability_issue(hass, entry)
    _sync_device_agent_update_issue(hass, entry)
    _sync_device_agent_startup_issue(hass, entry)
    _sync_unsupported_callback_url_issue(hass, entry)
    _sync_device_core_qml_hook_issue(hass, entry)
    _sync_device_user_issue(hass, entry)


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


def _sync_action_map_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
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


def _sync_missing_alarm_entity_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
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


def _sync_frontend_card_setup_hint_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
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


def _sync_agent_capability_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
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
    )


def _sync_device_agent_update_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
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


def _sync_device_agent_startup_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    runtime_data = getattr(entry, "runtime_data", None)
    diagnostics = getattr(runtime_data, "agent_diagnostics", None)
    if not isinstance(diagnostics, dict):
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


def _sync_unsupported_callback_url_issue(
    hass: HomeAssistant,
    entry: ConfigEntry,
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


def _sync_device_core_qml_hook_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
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


def _sync_device_user_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
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

    reason = None
    if status.get("homeassistant_user_present") is True and status.get("routes_consistent") is not True:
        reason = "homeassistant_routes_inconsistent"
    elif status.get("media_identity_available") is not True:
        reason = "media_identity_missing"
    elif (
        status.get("homeassistant_user_present") is True
        and "inhouse_binary_patch_applied" in status
        and status.get("inhouse_binary_patch_applied") is not True
    ):
        reason = "homeassistant_binary_patch_missing"
    elif (
        status.get("homeassistant_user_present") is True
        and "inhouse_qml_patch_applied" in status
        and status.get("inhouse_qml_patch_applied") is not True
    ):
        reason = "homeassistant_qml_patch_missing"
    if reason is None:
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


def _callback_problem(entry: ConfigEntry) -> dict[str, str] | None:
    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is None:
        return None
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
    entry: ConfigEntry,
    issue_type: str,
    *,
    severity: ir.IssueSeverity,
    is_fixable: bool = False,
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
        translation_key=issue_type,
        translation_placeholders=translation_placeholders,
        data={"entry_id": entry.entry_id, "issue_type": issue_type},
    )


def _configured_alarm_entity_id(entry: ConfigEntry) -> str:
    value = entry.options.get(CONF_ALARM_ENTITY_ID) or entry.data.get(CONF_ALARM_ENTITY_ID)
    return value.strip() if isinstance(value, str) else ""


def _entry_media_enabled(entry: ConfigEntry) -> bool:
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


def _frontend_card_setup_repair_handled(entry: ConfigEntry) -> bool:
    """Return true when this Lovelace card repair generation was handled."""

    return (
        entry.options.get(CONF_FRONTEND_CARD_SETUP_REPAIR_VERSION)
        == FRONTEND_CARD_SETUP_REPAIR_VERSION
    )


def _mark_frontend_card_setup_dismissed(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Persist that the Lovelace card setup hint has been handled."""

    if _frontend_card_setup_repair_handled(entry):
        return
    config_entries = getattr(hass, "config_entries", None)
    if config_entries is None or not hasattr(config_entries, "async_update_entry"):
        return
    config_entries.async_update_entry(
        entry,
        options={
            **dict(entry.options),
            CONF_FRONTEND_CARD_SETUP_DISMISSED: True,
            CONF_FRONTEND_CARD_SETUP_REPAIR_VERSION: (
                FRONTEND_CARD_SETUP_REPAIR_VERSION
            ),
        },
    )
