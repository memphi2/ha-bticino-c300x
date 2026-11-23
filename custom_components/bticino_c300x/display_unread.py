"""Ordered HA unread snapshots on the existing display event route."""

from __future__ import annotations

from asyncio import Lock
from weakref import WeakValueDictionary

from .api import C300XAgentApi
from .data import BticinoC300XRuntimeData
from .entry_types import BticinoC300XConfigEntry

# An in-flight send keeps its lock alive across entry unload/reload.
_locks: WeakValueDictionary[str, Lock] = WeakValueDictionary()


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
        await api.async_notify_display_bridge_event(
            topic, unread=store is not None and store.has_unread(),
        )
