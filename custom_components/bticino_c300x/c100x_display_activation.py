"""Follow a C100X display activation or restore through its reboot.

The C100X display program cannot be restarted: the agent switches the pages,
waits until the station is idle, reboots it and checks the new display in the
boot that follows. Home Assistant only watches: it reads the agent's status
every 30 seconds for at most an hour and reloads the entry once the outcome
differs from what the entry started with. A rollback is shown as a repair.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .api_errors import C300XAgentApiError
from .const import DOMAIN
from .entry_types import BticinoC300XConfigEntry

_LOGGER = logging.getLogger(__name__)

POLL_SECONDS = 30.0
MAX_POLLS = 120
ROLLED_BACK_ISSUE = "c100x_display_rolled_back"
BOOT_CHECK_ISSUE = "c100x_display_boot_check_failed"
UPDATE_POLLS = 10
UPDATE_POLL_SECONDS = 3.0
_PENDING_PHASES = frozenset({"prepared", "trial", "stale"})
_COMPARED = ("status_known", "phase", "confirmed")


def c100x_display_status(capabilities: Any) -> Mapping[str, Any] | None:
    """The agent's c100x_display object; None on a C300X or an older agent."""

    status = capabilities.get("c100x_display") if isinstance(capabilities, Mapping) else None
    return status if isinstance(status, Mapping) and status.get("supported") is True else None


def c100x_display_in_progress(status: Mapping[str, Any]) -> bool:
    """Whether a trial, a reboot or the status itself is still open."""

    return (
        status.get("status_known") is not True
        or status.get("busy") is True
        or status.get("phase") in _PENDING_PHASES
        or status.get("reboot_pending") is True
    )


def _issue_id(entry: BticinoC300XConfigEntry, issue: str = ROLLED_BACK_ISSUE) -> str:
    return f"{issue}_{entry.entry_id}"


def _placeholders(entry: BticinoC300XConfigEntry) -> dict[str, str]:
    return {"entry_title": str(getattr(entry, "title", "") or entry.entry_id)}


@callback
def async_sync_c100x_display_issues(
    hass: HomeAssistant, entry: BticinoC300XConfigEntry, status: Mapping[str, Any]
) -> None:
    """Both display repairs: a failed boot check and a rollback."""

    async_sync_boot_check_issue(hass, entry, status)
    async_sync_rolled_back_issue(hass, entry, status)


@callback
def async_sync_boot_check_issue(
    hass: HomeAssistant, entry: BticinoC300XConfigEntry, status: Mapping[str, Any]
) -> None:
    """Show a failed boot check of a pending trial while the agent reports it."""

    reason = status.get("boot_check")
    if isinstance(reason, str) and reason:
        ir.async_create_issue(
            hass,
            DOMAIN,
            _issue_id(entry, BOOT_CHECK_ISSUE),
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=BOOT_CHECK_ISSUE,
            translation_placeholders=_placeholders(entry),
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, _issue_id(entry, BOOT_CHECK_ISSUE))


@callback
def async_sync_rolled_back_issue(
    hass: HomeAssistant, entry: BticinoC300XConfigEntry, status: Mapping[str, Any]
) -> None:
    """Show a rollback until the pages are confirmed or restored."""

    if status.get("status_known") is not True:
        return
    if status.get("last_result") == "rolled_back" and status.get("phase") == "stock":
        ir.async_create_issue(
            hass,
            DOMAIN,
            _issue_id(entry),
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ROLLED_BACK_ISSUE,
            translation_placeholders=_placeholders(entry),
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, _issue_id(entry))


async def _async_follow(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> None:
    runtime = entry.runtime_data
    start = c100x_display_status(runtime.capabilities) or {}
    for _ in range(MAX_POLLS):
        await asyncio.sleep(POLL_SECONDS)
        try:
            status = (await runtime.api.async_c100x_display_status()).get("c100x_display")
        except C300XAgentApiError as err:
            # The station reboots in between.
            _LOGGER.debug("C300X C100X display status not readable: %s", err)
            continue
        if not isinstance(status, Mapping):
            return
        async_sync_c100x_display_issues(hass, entry, status)
        if isinstance(runtime.capabilities, dict):
            runtime.capabilities["c100x_display"] = dict(status)
        if c100x_display_in_progress(status):
            continue
        # Settled: a new outcome needs the entry's capabilities and options again.
        if any(status.get(key) != start.get(key) for key in _COMPARED):
            hass.config_entries.async_schedule_reload(entry.entry_id)
        return


async def async_renew_c100x_display_after_update(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> None:
    """After an update: confirmed pages go to the adapter the update brought.

    The agent reads its adapter again after the update. Pages that are active
    and confirmed are activated again when the agent offers that, as with the
    button: the agent reboots the station once it is idle. An original display
    stays as it is, and a station that does not answer is left alone.
    """

    runtime = entry.runtime_data
    if c100x_display_status(getattr(runtime, "capabilities", None)) is None:
        return
    for attempt in range(UPDATE_POLLS):
        if attempt:
            await asyncio.sleep(UPDATE_POLL_SECONDS)
        try:
            status = (await runtime.api.async_c100x_display_status()).get("c100x_display")
        except C300XAgentApiError as err:
            _LOGGER.debug("C300X C100X display status not readable after the update: %s", err)
            continue
        if not isinstance(status, Mapping):
            return
        if status.get("status_known") is True and status.get("busy") is not True:
            break
    else:
        return
    if status.get("confirmed") is not True or status.get("activate") is not True:
        return
    try:
        await runtime.api.async_c100x_display_activate()
    except C300XAgentApiError as err:
        _LOGGER.warning("C100X display pages were not renewed after the update: %s", err)
        return
    async_follow_c100x_display(hass, entry)


@callback
def async_follow_c100x_display_if_open(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> None:
    """At a start: follow an activation or restore the agent has not finished."""

    status = c100x_display_status(getattr(entry.runtime_data, "capabilities", {}))
    if status is not None:
        async_sync_c100x_display_issues(hass, entry, status)
        if c100x_display_in_progress(status):
            async_follow_c100x_display(hass, entry)


@callback
def async_follow_c100x_display(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> None:
    """Start following, once per entry lifetime; the entry's unload cancels it."""

    resources = entry.runtime_data.resources
    task = resources.c100x_display_task
    if resources.closed or (task is not None and not task.done()):
        return
    resources.c100x_display_task = hass.async_create_background_task(
        _async_follow(hass, entry), f"{DOMAIN}_c100x_display_{entry.entry_id}"
    )
