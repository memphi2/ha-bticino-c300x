"""Per-config-entry asyncio.Lock registry shared across feature modules.

Feature modules that must serialize check-then-act sequences against the
device agent (message refresh, ring capture, Display patch) share this
registry so every lock is dropped by one call on entry unload. Whether a
caller queues behind the lock or fails fast while it is held is decided at
the call site, not here.
"""

from __future__ import annotations

from asyncio import Lock

_locks: dict[tuple[str, str], Lock] = {}


def entry_lock(entry_id: str, scope: str) -> Lock:
    """Return the cached per-entry lock for one feature scope."""

    return _locks.setdefault((entry_id, scope), Lock())


def clear_entry_locks(entry_id: str) -> None:
    """Drop all cached locks for an unloaded config entry."""

    for key in tuple(_locks):
        if key[0] == entry_id:
            _locks.pop(key, None)
