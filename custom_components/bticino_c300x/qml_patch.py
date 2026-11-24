"""Helpers for synchronizing the C300X device UI patch state."""

from __future__ import annotations

import logging
from asyncio import Lock
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from .agent_update import async_retry_update_maintenance_busy
from .const import (
    CONF_DASHBOARD_DYNAMIC_HOMEPAGE,
    DEFAULT_DASHBOARD_DYNAMIC_HOMEPAGE,
    HOME_BUTTONS_SIDE_BY_SIDE,
    HOME_BUTTONS_STOCK,
)
from .entry_config import entry_config_value
from .entry_locks import entry_lock
from .entry_types import BticinoC300XConfigEntry

_LOGGER = logging.getLogger(__name__)


def _qml_patch_lock(entry: BticinoC300XConfigEntry) -> Lock:
    """Return the per-entry lock serializing all Display-patch mutations."""

    return entry_lock(entry.entry_id, "qml_patch")


async def async_refresh_qml_patch_status(
    entry: BticinoC300XConfigEntry, *, wait_busy: bool = False,
) -> dict[str, Any]:
    """Refresh and store the device-reported Display patch status.

    ``wait_busy`` waits while the agent runs another maintenance job.
    """

    read = entry.runtime_data.api.async_qml_patch_status
    status: dict[str, Any] = await (
        async_retry_update_maintenance_busy(read) if wait_busy else read()
    )
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


def entry_dynamic_homepage(entry: BticinoC300XConfigEntry) -> bool:
    """Return the entry's home page layout: True stock, False side by side.

    An absent key is the stock layout, the same default the form shows.
    """

    return bool(
        entry_config_value(
            entry,
            CONF_DASHBOARD_DYNAMIC_HOMEPAGE,
            DEFAULT_DASHBOARD_DYNAMIC_HOMEPAGE,
        )
    )


def entry_home_buttons(entry: BticinoC300XConfigEntry) -> str:
    """Return the entry's layout under the name the patch status reports."""

    return HOME_BUTTONS_STOCK if entry_dynamic_homepage(entry) else HOME_BUTTONS_SIDE_BY_SIDE


def _apply_full_patch_action(
    entry: BticinoC300XConfigEntry,
) -> Callable[[], Awaitable[dict[str, Any]]]:
    """Return the Display-patch apply call with the entry's home page layout."""

    return lambda: entry.runtime_data.api.async_apply_qml_patch(
        dynamic_homepage=entry_dynamic_homepage(entry)
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

    api = entry.runtime_data.api
    busy_retry = async_retry_update_maintenance_busy
    async with _qml_patch_lock(entry):
        core_status = await busy_retry(api.async_apply_qml_core_patch)
        _store_qml_patch_status(entry, core_status)
        if apply_full_patch:
            full_patch = _apply_full_patch_action(entry)
            await _async_run_qml_patch_action_unlocked(
                entry,
                status_changed=None,
                transient_state="patching",
                expected_patched=True,
                action=lambda: busy_retry(full_patch),
                refresh=lambda entry: async_refresh_qml_patch_status(entry, wait_busy=True),
            )
        await busy_retry(api.async_reload_gui)
        return await async_refresh_qml_patch_status(entry, wait_busy=True)


async def async_apply_qml_core_patch_and_confirm(
    entry: BticinoC300XConfigEntry,
    status_changed: _StatusChanged | None = None,
) -> dict[str, Any]:
    """Apply the always-needed core media hook and store confirmed status."""

    async with _qml_patch_lock(entry):
        previous_status = _qml_patch_status(entry)
        _store_transient_qml_core_patch_status(entry, "core_patching")
        return await _async_settle_qml_patch_action(
            entry,
            status_changed=status_changed,
            previous_status=previous_status,
            confirmed=lambda status: status.get("core_patched") is True,
            action=entry.runtime_data.api.async_apply_qml_core_patch,
            refresh=async_refresh_qml_patch_status,
        )


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
    refresh: Callable[
        [BticinoC300XConfigEntry], Awaitable[dict[str, Any]]
    ] = async_refresh_qml_patch_status,
) -> dict[str, Any]:
    """Run one patch mutation; the caller must hold the entry's patch lock."""

    previous_status = _qml_patch_status(entry)
    _store_transient_qml_patch_status(entry, transient_state)
    return await _async_settle_qml_patch_action(
        entry,
        status_changed=status_changed,
        previous_status=previous_status,
        confirmed=lambda status: status.get("patched") is expected_patched,
        action=action,
        refresh=refresh,
    )


async def _async_settle_qml_patch_action(
    entry: BticinoC300XConfigEntry,
    *,
    status_changed: _StatusChanged | None,
    previous_status: dict[str, Any],
    confirmed: Callable[[dict[str, Any]], bool],
    action: Callable[[], Awaitable[dict[str, Any]]],
    refresh: Callable[[BticinoC300XConfigEntry], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Run a write whose transient status is stored; never leave that status.

    A failed write (a 504 timeout included, whether it was rolled back or not)
    is followed by a fresh status read, since the device may have changed; the
    status from before the write comes back only when that read fails too, or
    when the task is cancelled. A write that succeeded keeps its own answer
    when the confirming read fails.
    """

    _notify_status_changed(status_changed)
    try:
        action_status = await action()
    except Exception:
        try:
            await refresh(entry)
        except Exception:
            _store_qml_patch_status(entry, previous_status)
        _notify_status_changed(status_changed)
        raise
    except BaseException:
        _store_qml_patch_status(entry, previous_status)
        _notify_status_changed(status_changed)
        raise
    if not confirmed(action_status):
        _store_qml_patch_status(entry, action_status)
        _notify_status_changed(status_changed)
        return action_status
    try:
        status = await refresh(entry)
    except Exception as err:
        _LOGGER.warning("C300X Display patch status read after a write failed: %s", err)
        status = action_status
        _store_qml_patch_status(entry, status)
    except BaseException:
        _store_qml_patch_status(entry, action_status)
        _notify_status_changed(status_changed)
        raise
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
