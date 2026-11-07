"""Own pending offers, ICE candidates and active camera provider sessions."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from typing import Any

from .background_tasks import CameraBackgroundTasks
from .webrtc_session import ProviderWebRTCSession


class CameraWebRTCSessions:
    """Keep session cancellation independent of device/media stop policy."""

    def __init__(self, tasks: CameraBackgroundTasks) -> None:
        self._tasks = tasks
        self.active: dict[str, ProviderWebRTCSession] = {}
        self.candidates: dict[str, list[Any]] = {}
        self.offers: dict[str, asyncio.Task[Any]] = {}

    @contextmanager
    def opening(self, session_id: str) -> Iterator[None]:
        """Own an offer until completion, failure or cancellation cleanup."""
        if session_id in self.offers:
            raise ValueError("Session is already opening")
        task = asyncio.current_task()
        assert task is not None
        self.offers[session_id] = task
        try:
            with self._tasks.track_current():
                yield
        finally:
            if self.offers.get(session_id) is task:
                self.offers.pop(session_id)

    def cancel_offer(self, session_id: str) -> asyncio.Task[Any] | None:
        """Cancel once so repeated closes cannot interrupt cancellation cleanup."""
        offer = self.offers.get(session_id)
        if offer is not None and not offer.cancelling():
            offer.cancel()
        return offer

    async def close_after_offer(
        self, offer: asyncio.Task[Any] | None, close: Callable[[], Awaitable[None]],
    ) -> None:
        """Finish offer cleanup before closing any resulting provider session."""
        if offer is not None:
            # Entity removal also cancels the offer; avoid a second cancellation.
            await asyncio.gather(asyncio.shield(offer), return_exceptions=True)
        await close()
