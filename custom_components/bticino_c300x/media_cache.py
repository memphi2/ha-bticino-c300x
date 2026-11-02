"""Bounded, short-lived in-memory storage for authenticated media requests."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass

MAX_MEDIA_BYTES = 64 * 1024 * 1024
_CACHE_SECONDS = 30
_MAX_PENDING = 4
_MAX_ENTRIES = 4


class MediaBusyError(Exception):
    """The bounded processing queue is full."""


@dataclass
class _CachedMedia:
    value: tuple[bytes, str]
    expiry: asyncio.TimerHandle


class MediaCache:
    """Share identical work, serialize conversions, and cap retained bytes."""

    def __init__(self) -> None:
        self._pending: dict[Hashable, asyncio.Task[tuple[bytes, str]]] = {}
        self._cached: OrderedDict[Hashable, _CachedMedia] = OrderedDict()
        self._serial = asyncio.Semaphore(1)
        self._bytes = 0

    async def get(
        self, key: Hashable, load: Callable[[], Awaitable[tuple[bytes, str]]]
    ) -> tuple[bytes, str]:
        cached = self._cached.get(key)
        if cached is not None:
            self._cached.move_to_end(key)
            return cached.value
        task = self._pending.get(key)
        if task is None:
            if len(self._pending) >= _MAX_PENDING:
                raise MediaBusyError
            task = asyncio.create_task(self._load(key, load))
            self._pending[key] = task

            def finished(done: asyncio.Task[tuple[bytes, str]]) -> None:
                self._pending.pop(key, None)
                if not done.cancelled():
                    done.exception()

            task.add_done_callback(finished)
        # A disconnected viewer must not cancel work shared with other viewers.
        return await asyncio.shield(task)

    async def _load(
        self, key: Hashable, load: Callable[[], Awaitable[tuple[bytes, str]]]
    ) -> tuple[bytes, str]:
        async with self._serial:
            value = await load()
        size = len(value[0])
        if size > MAX_MEDIA_BYTES:
            raise ValueError("converted media exceeds size limit")
        while self._cached and (
            self._bytes + size > MAX_MEDIA_BYTES or len(self._cached) >= _MAX_ENTRIES
        ):
            self._expire(next(iter(self._cached)))
        expiry = asyncio.get_running_loop().call_later(
            _CACHE_SECONDS, self._expire, key
        )
        self._cached[key] = _CachedMedia(value, expiry)
        self._bytes += size
        return value

    def _expire(self, key: Hashable) -> None:
        cached = self._cached.pop(key, None)
        if cached is not None:
            cached.expiry.cancel()
            self._bytes -= len(cached.value[0])
