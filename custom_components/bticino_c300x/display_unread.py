"""Ordered HA unread snapshots on the existing display event route."""

from __future__ import annotations

import logging
from asyncio import Lock, timeout
from weakref import WeakValueDictionary

from .api import C300XAgentApi
from .api_errors import C300XAgentApiError
from .data import BticinoC300XRuntimeData
from .entry_types import BticinoC300XConfigEntry

# An in-flight send keeps its lock alive across entry unload/reload.
_locks: WeakValueDictionary[str, Lock] = WeakValueDictionary()
_LOGGER = logging.getLogger(__name__)
# One in-flight event and one final release, each with a two-second HTTP timeout.
_RELEASE_TIMEOUT = 5.0


async def async_send_unread_event(
    entry: BticinoC300XConfigEntry,
    runtime: BticinoC300XRuntimeData,
    api: C300XAgentApi,
    topic: str,
) -> None:
    lock = _locks.setdefault(entry.entry_id, Lock())
    async with lock:
        if getattr(entry, "runtime_data", None) is not runtime or getattr(
            getattr(runtime, "resources", None), "closed", False
        ):
            return
        store = getattr(runtime, "display_notifications", None)
        unread = store is not None and store.has_unread()
        if unread and runtime.capabilities.get("memo_led") is True:
            # A lost response is not proof that the agent missed the claim.
            runtime.display_unread_claim_possible = True
        await api.async_notify_display_bridge_event(topic, unread=unread)
        if not unread:
            runtime.display_unread_claim_possible = False


async def async_release_unread_claim(
    entry: BticinoC300XConfigEntry, runtime: BticinoC300XRuntimeData,
) -> None:
    """Best-effort release after local resources have closed to new sends."""
    if not getattr(runtime, "display_unread_claim_possible", False):
        return
    try:
        async with timeout(_RELEASE_TIMEOUT), _locks.setdefault(entry.entry_id, Lock()):
            if entry.runtime_data is not runtime or not runtime.display_unread_claim_possible:
                return
            await runtime.api.async_notify_display_bridge_event("notifications", unread=False)
            runtime.display_unread_claim_possible = False
    except (C300XAgentApiError, TimeoutError) as err:
        _LOGGER.debug("Could not confirm C300X unread release during unload: %s", err)
