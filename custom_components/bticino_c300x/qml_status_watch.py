"""Re-read the Display patch status after an agent restart or a reconnect.

At start the agent finishes a display write that a power loss or a kill left
behind, or reports it stuck. Home Assistant keeps the status it read last, so
the "unfinished Display patch write" Repairs issue follows the device only
after a new read. The read runs in the background, waits for a running write
and is throttled.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .entry_types import BticinoC300XConfigEntry

_LOGGER = logging.getLogger(__name__)
# At most one read per window; a trigger inside it is served at its end.
READ_INTERVAL_SECONDS = 60.0


@dataclass(slots=True)
class QmlStatusWatch:
    """The entry's one background status read and its throttle."""

    task: asyncio.Task[None] | None = None
    last_read: float | None = None
    again: bool = False


def async_schedule_qml_status_refresh(
    hass: HomeAssistant, entry: BticinoC300XConfigEntry, *, restarted: bool
) -> None:
    """Read the status again soon.

    A restarted agent always gets the read. A reconnect does not when the
    status was stored within the window: the agent kept its state, and a
    start-up read or a write has just stored it.
    """

    from .capabilities import maintenance_action_is_advertised

    runtime: Any = getattr(entry, "runtime_data", None)
    if runtime is None or not maintenance_action_is_advertised(
        getattr(runtime, "capabilities", {}), "qml_status"
    ):
        return
    if not restarted and _stored_recently(runtime):
        return
    watch: QmlStatusWatch = runtime.qml_status_watch
    if watch.task is not None and not watch.task.done():
        watch.again = True
        return
    watch.task = entry.async_create_background_task(
        hass, _async_run(hass, entry, watch), "C300X Display patch status", eager_start=False
    )


def _stored_recently(runtime: Any) -> bool:
    updated_at = getattr(runtime, "qml_patch_status_updated_at", None)
    return (
        updated_at is not None
        and (datetime.now(UTC) - updated_at).total_seconds() < READ_INTERVAL_SECONDS
    )


async def _async_run(
    hass: HomeAssistant, entry: BticinoC300XConfigEntry, watch: QmlStatusWatch
) -> None:
    while True:
        if watch.last_read is not None:
            wait = watch.last_read + READ_INTERVAL_SECONDS - monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
        watch.again = False
        watch.last_read = monotonic()
        await _async_read(hass, entry)
        if not watch.again:
            return


async def _async_read(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> None:
    from homeassistant.helpers.dispatcher import async_dispatcher_send

    from .const import SIGNAL_QML_PATCH_CHANGED
    from .error_text import compact_error_text
    from .qml_patch import async_refresh_qml_patch_status_between_writes
    from .repair_issues import async_sync_entry_repair_issues

    try:
        await async_refresh_qml_patch_status_between_writes(entry)
    except Exception as err:  # noqa: BLE001 - the next restart or reconnect asks again
        _LOGGER.debug("C300X Display patch status read after a reconnect failed: %s", compact_error_text(err))
        return
    async_sync_entry_repair_issues(hass, entry)
    async_dispatcher_send(hass, SIGNAL_QML_PATCH_CHANGED, entry.entry_id)
