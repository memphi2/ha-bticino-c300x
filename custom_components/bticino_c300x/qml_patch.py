"""Helpers for synchronizing the C300X device UI patch state."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry


async def async_refresh_qml_patch_status(entry: ConfigEntry) -> dict[str, Any]:
    """Refresh and store the device-reported Display patch status."""

    status = await entry.runtime_data.api.async_qml_patch_status()
    _store_qml_patch_status(entry, status)
    return status


type _StatusChanged = Callable[[], None]


async def async_apply_qml_patch_and_confirm(
    entry: ConfigEntry,
    status_changed: _StatusChanged | None = None,
) -> dict[str, Any]:
    """Apply the patch and store the confirmed post-action status."""

    return await _async_run_qml_patch_action(
        entry,
        status_changed=status_changed,
        transient_state="patching",
        expected_patched=True,
        action=entry.runtime_data.api.async_apply_qml_patch,
    )


async def async_apply_qml_core_patch_and_confirm(
    entry: ConfigEntry,
    status_changed: _StatusChanged | None = None,
) -> dict[str, Any]:
    """Apply the always-needed core media hook and store confirmed status."""

    previous_status = _qml_patch_status(entry)
    _store_transient_qml_core_patch_status(entry, "core_patching")
    _notify_status_changed(status_changed)
    try:
        action_status = await entry.runtime_data.api.async_apply_qml_core_patch()
    except Exception:
        _store_qml_patch_status(entry, previous_status)
        _notify_status_changed(status_changed)
        raise
    if action_status.get("core_patched") is not True:
        _store_qml_patch_status(entry, action_status)
        _notify_status_changed(status_changed)
        return action_status
    status = await async_refresh_qml_patch_status(entry)
    _notify_status_changed(status_changed)
    return status


async def async_restore_qml_core_patch_and_confirm(
    entry: ConfigEntry,
    status_changed: _StatusChanged | None = None,
) -> dict[str, Any]:
    """Restore only the core media hook and store confirmed status."""

    previous_status = _qml_patch_status(entry)
    _store_transient_qml_core_patch_status(entry, "core_restoring")
    _notify_status_changed(status_changed)
    try:
        action_status = await entry.runtime_data.api.async_restore_qml_core_patch()
    except Exception:
        _store_qml_patch_status(entry, previous_status)
        _notify_status_changed(status_changed)
        raise
    if action_status.get("core_patched") is not False:
        _store_qml_patch_status(entry, action_status)
        _notify_status_changed(status_changed)
        return action_status
    status = await async_refresh_qml_patch_status(entry)
    _notify_status_changed(status_changed)
    return status


async def async_restore_qml_patch_and_confirm(
    entry: ConfigEntry,
    status_changed: _StatusChanged | None = None,
) -> dict[str, Any]:
    """Restore display files and store the confirmed post-action status."""

    return await _async_run_qml_patch_action(
        entry,
        status_changed=status_changed,
        transient_state="restoring",
        expected_patched=False,
        action=entry.runtime_data.api.async_restore_qml_patch,
    )


async def _async_run_qml_patch_action(
    entry: ConfigEntry,
    *,
    status_changed: _StatusChanged | None,
    transient_state: str,
    expected_patched: bool,
    action: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Run a Display patch mutation and confirm the final reported state."""

    previous_status = _qml_patch_status(entry)
    _store_transient_qml_patch_status(entry, transient_state)
    _notify_status_changed(status_changed)
    try:
        action_status = await action()
    except Exception:
        _store_qml_patch_status(entry, previous_status)
        _notify_status_changed(status_changed)
        raise
    if action_status.get("patched") is not expected_patched:
        _store_qml_patch_status(entry, action_status)
        _notify_status_changed(status_changed)
        return action_status
    status = await async_refresh_qml_patch_status(entry)
    _notify_status_changed(status_changed)
    return status


def _store_transient_qml_patch_status(entry: ConfigEntry, state: str) -> None:
    current = _qml_patch_status(entry)
    _store_qml_patch_status(
        entry,
        {
            "available": current.get("available", True),
            "patched": None,
            "state": state,
            "core_patched": current.get("core_patched"),
            "core_state": current.get("core_state"),
            "backup_available": current.get("backup_available"),
            "core_backup_available": current.get("core_backup_available"),
            "gui_running": current.get("gui_running"),
        },
    )


def _store_transient_qml_core_patch_status(entry: ConfigEntry, state: str) -> None:
    current = _qml_patch_status(entry)
    _store_qml_patch_status(
        entry,
        {
            "available": current.get("available", True),
            "patched": current.get("patched"),
            "state": current.get("state"),
            "core_patched": None,
            "core_state": state,
            "backup_available": current.get("backup_available"),
            "core_backup_available": current.get("core_backup_available"),
            "gui_running": current.get("gui_running"),
        },
    )


def _qml_patch_status(entry: ConfigEntry) -> dict[str, Any]:
    status = getattr(entry.runtime_data, "qml_patch_status", {})
    return dict(status) if isinstance(status, dict) else {}


def _notify_status_changed(status_changed: _StatusChanged | None) -> None:
    if status_changed is not None:
        status_changed()


def _store_qml_patch_status(entry: ConfigEntry, status: dict[str, Any]) -> None:
    entry.runtime_data.qml_patch_status = status
    entry.runtime_data.qml_patch_status_updated_at = datetime.now(UTC)
