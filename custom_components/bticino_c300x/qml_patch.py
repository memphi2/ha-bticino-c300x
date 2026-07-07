"""Helpers for synchronizing the C300X device UI patch state."""

from __future__ import annotations

from asyncio import Lock
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, cast

from .const import CONF_DASHBOARD_DYNAMIC_HOMEPAGE
from .entry_config import entry_config_value
from .entry_locks import entry_lock
from .entry_types import BticinoC300XConfigEntry


def _qml_patch_lock(entry: BticinoC300XConfigEntry) -> Lock:
    """Return the per-entry lock serializing all Display-patch mutations."""

    return entry_lock(entry.entry_id, "qml_patch")


async def async_refresh_qml_patch_status(entry: BticinoC300XConfigEntry) -> dict[str, Any]:
    """Refresh and store the device-reported Display patch status."""

    status = cast(dict[str, Any], await entry.runtime_data.api.async_qml_patch_status())
    _store_qml_patch_status(entry, status)
    return status


type _StatusChanged = Callable[[], None]


async def async_apply_qml_patch_and_confirm(
    entry: BticinoC300XConfigEntry,
    status_changed: _StatusChanged | None = None,
) -> dict[str, Any]:
    """Apply the patch and store the confirmed post-action status."""

    return await _async_run_qml_patch_action(
        entry,
        status_changed=status_changed,
        transient_state="patching",
        expected_patched=True,
        action=_apply_full_patch_action(entry),
    )


def _apply_full_patch_action(
    entry: BticinoC300XConfigEntry,
) -> Callable[[], Awaitable[dict[str, Any]]]:
    """Return the full Display-patch apply call with configured options."""

    return lambda: entry.runtime_data.api.async_apply_qml_patch(
        dynamic_homepage=bool(
            entry_config_value(entry, CONF_DASHBOARD_DYNAMIC_HOMEPAGE, False)
        )
    )


async def async_restore_qml_patches_after_update(
    entry: BticinoC300XConfigEntry,
    *,
    apply_full_patch: bool,
) -> dict[str, Any]:
    """Re-apply the core hook (and active full patch) after an agent update.

    Holds the per-entry Display-patch lock across the whole sequence so a
    concurrent switch toggle or repair-flow action cannot interleave between
    the core apply, the full-patch apply, and the GUI reload.
    """

    async with _qml_patch_lock(entry):
        core_status = cast(
            dict[str, Any],
            await entry.runtime_data.api.async_apply_qml_core_patch(),
        )
        _store_qml_patch_status(entry, core_status)
        if apply_full_patch:
            await _async_run_qml_patch_action_unlocked(
                entry,
                status_changed=None,
                transient_state="patching",
                expected_patched=True,
                action=_apply_full_patch_action(entry),
            )
        await entry.runtime_data.api.async_reload_gui()
        return await async_refresh_qml_patch_status(entry)


async def async_apply_qml_core_patch_and_confirm(
    entry: BticinoC300XConfigEntry,
    status_changed: _StatusChanged | None = None,
) -> dict[str, Any]:
    """Apply the always-needed core media hook and store confirmed status."""

    async with _qml_patch_lock(entry):
        previous_status = _qml_patch_status(entry)
        _store_transient_qml_core_patch_status(entry, "core_patching")
        _notify_status_changed(status_changed)
        try:
            action_status = cast(
                dict[str, Any],
                await entry.runtime_data.api.async_apply_qml_core_patch(),
            )
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
    entry: BticinoC300XConfigEntry,
    status_changed: _StatusChanged | None = None,
) -> dict[str, Any]:
    """Restore only the core media hook and store confirmed status."""

    async with _qml_patch_lock(entry):
        previous_status = _qml_patch_status(entry)
        _store_transient_qml_core_patch_status(entry, "core_restoring")
        _notify_status_changed(status_changed)
        try:
            action_status = cast(
                dict[str, Any],
                await entry.runtime_data.api.async_restore_qml_core_patch(),
            )
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
    entry: BticinoC300XConfigEntry,
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
    entry: BticinoC300XConfigEntry,
    *,
    status_changed: _StatusChanged | None,
    transient_state: str,
    expected_patched: bool,
    action: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Run a Display patch mutation and confirm the final reported state."""

    async with _qml_patch_lock(entry):
        return await _async_run_qml_patch_action_unlocked(
            entry,
            status_changed=status_changed,
            transient_state=transient_state,
            expected_patched=expected_patched,
            action=action,
        )


async def _async_run_qml_patch_action_unlocked(
    entry: BticinoC300XConfigEntry,
    *,
    status_changed: _StatusChanged | None,
    transient_state: str,
    expected_patched: bool,
    action: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Run one patch mutation; the caller must hold the entry's patch lock."""

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


def _store_transient_qml_patch_status(entry: BticinoC300XConfigEntry, state: str) -> None:
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


def _store_transient_qml_core_patch_status(entry: BticinoC300XConfigEntry, state: str) -> None:
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


def _qml_patch_status(entry: BticinoC300XConfigEntry) -> dict[str, Any]:
    status = getattr(entry.runtime_data, "qml_patch_status", {})
    return dict(status) if isinstance(status, dict) else {}


def _notify_status_changed(status_changed: _StatusChanged | None) -> None:
    if status_changed is not None:
        status_changed()


def _store_qml_patch_status(entry: BticinoC300XConfigEntry, status: dict[str, Any]) -> None:
    entry.runtime_data.qml_patch_status = status
    entry.runtime_data.qml_patch_status_updated_at = datetime.now(UTC)
