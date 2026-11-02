"""Camera-owned background work that cannot outlive entity removal."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class CameraBackgroundTasks:
    """Own camera event tasks and optionally coalesce one named operation."""

    def __init__(self) -> None:
        self.closing = False
        self._tasks: set[asyncio.Task[Any]] = set()
        self._named: dict[str, asyncio.Task[Any]] = {}

    def create(
        self, hass: HomeAssistant, coro: Coroutine[Any, Any, None], *, key: str | None = None,
    ) -> None:
        """Schedule work, disposing unused coroutines during unload or coalescing."""
        previous = self._named.get(key) if key is not None else None
        if self.closing or (previous is not None and not previous.done()):
            coro.close()
            return
        try:
            task = hass.async_create_task(coro)
        except BaseException:
            coro.close()
            raise
        self._tasks.add(task)
        if key is not None:
            self._named[key] = task

        def done(completed: asyncio.Task[Any]) -> None:
            self._tasks.discard(completed)
            if key is not None and self._named.get(key) is completed:
                self._named.pop(key)
            if not completed.cancelled() and (error := completed.exception()) is not None:
                _LOGGER.error("Camera background task failed", exc_info=error)

        task.add_done_callback(done)

    async def close(self) -> None:
        """Reject new work, cancel outstanding tasks and await their cleanup."""
        self.closing = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._named.clear()
