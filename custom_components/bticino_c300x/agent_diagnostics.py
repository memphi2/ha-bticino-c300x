"""Runtime write-diagnostics helpers for the C300X device agent."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .api import (
    C300XAgentApiError,
    C300XAgentApiResponseError,
    normalize_agent_diagnostics,
)
from .capabilities import diagnostics_supported
from .const import SIGNAL_AGENT_DIAGNOSTICS_CHANGED

_WRITE_DIAGNOSTIC_KEYS = (
    "agent_write_count",
    "last_write_at",
    "last_write_reason",
    "last_write_class",
    "qml_patch_last_action",
)
_MEDIA_DIAGNOSTIC_KEYS = (
    "video_running",
    "video_media_starting",
    "video_call_active",
    "video_clients",
    "video_media_owner",
    "video_external_media_active",
    "video_external_owner",
    "video_last_block_reason",
    "video_bridge_media_active",
    "video_bridge_stop_in_progress",
    "video_bridge_open_fds",
    "video_bridge_active_threads",
    "ring_receiver_running",
    "ring_registered",
    "ring_call_active",
    "ring_media_active",
    "home_call_running",
    "home_call_active",
)
_UI_EVENT_DIAGNOSTIC_KEYS = (
    "ui_event_waiters",
    "ui_event_waiter_capacity",
    "ui_event_waiter_overflows",
)


async def async_refresh_agent_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> Mapping[str, Any] | None:
    """Refresh safe write diagnostics once and notify interested entities."""

    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is None or not diagnostics_supported(runtime_data.capabilities):
        return None
    try:
        diagnostics = await runtime_data.api.async_diagnostics()
    except C300XAgentApiError:
        return None
    _store_agent_diagnostics(
        hass,
        entry,
        diagnostics,
        updated_by="api_refresh",
        reason="api_refresh",
        notify_if_unchanged=True,
    )
    return diagnostics


def apply_agent_diagnostics_event(
    hass: HomeAssistant,
    entry: ConfigEntry,
    data: dict[str, Any],
) -> Mapping[str, Any] | None:
    """Apply write diagnostics carried in a push event without callback recursion."""

    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is None or not diagnostics_supported(runtime_data.capabilities):
        return None
    try:
        diagnostics = normalize_agent_diagnostics(data)
    except C300XAgentApiResponseError:
        return None
    _store_agent_diagnostics(
        hass,
        entry,
        diagnostics,
        updated_by="push_event",
        reason=_agent_diagnostics_change_reason(
            runtime_data.agent_diagnostics,
            diagnostics,
        ),
        notify_if_unchanged=False,
    )
    return diagnostics


def _store_agent_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
    diagnostics: Mapping[str, Any],
    *,
    updated_by: str,
    reason: str,
    notify_if_unchanged: bool,
) -> bool:
    """Store diagnostics and dispatch only when the visible state should change."""

    runtime_data = entry.runtime_data
    changed = diagnostics != runtime_data.agent_diagnostics
    if not changed and not notify_if_unchanged:
        return False
    runtime_data.agent_diagnostics = diagnostics
    runtime_data.agent_diagnostics_updated_at = datetime.now(UTC)
    runtime_data.agent_diagnostics_updated_by = updated_by
    runtime_data.agent_diagnostics_change_reason = (
        reason if changed else f"{reason}_unchanged"
    )
    async_dispatcher_send(hass, SIGNAL_AGENT_DIAGNOSTICS_CHANGED, entry.entry_id)
    from .repair_issues import async_sync_entry_repair_issues

    async_sync_entry_repair_issues(hass, entry)
    return True


def _agent_diagnostics_change_reason(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
) -> str:
    """Return a compact operator-facing reason for a diagnostics change."""

    if not previous:
        return "initial_push"
    if _changed(previous, current, _WRITE_DIAGNOSTIC_KEYS):
        return "write_diagnostics_changed"
    if _changed(previous, current, _MEDIA_DIAGNOSTIC_KEYS):
        return "media_diagnostics_changed"
    if _changed(previous, current, _UI_EVENT_DIAGNOSTIC_KEYS):
        return "display_event_watchdog_changed"
    if previous.get("last_wake_reason") != current.get("last_wake_reason"):
        return "agent_wake_reason_changed"
    if previous.get("poll_wakeups") != current.get("poll_wakeups"):
        return "agent_poll_activity_changed"
    return "agent_diagnostics_changed"


def _changed(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
    keys: tuple[str, ...],
) -> bool:
    return any(previous.get(key) != current.get(key) for key in keys)
