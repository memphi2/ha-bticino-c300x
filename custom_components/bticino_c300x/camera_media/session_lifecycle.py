"""Own pending offers, ICE candidates and active camera provider sessions."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from typing import Any

from homeassistant.exceptions import HomeAssistantError

from .background_tasks import CameraBackgroundTasks
from .webrtc_session import ProviderWebRTCSession

MAX_PRESESSION_WEBRTC_SESSIONS = 16
MAX_PRESESSION_WEBRTC_CANDIDATES = 64


def raise_if_on_demand_capture_active(resources: Any) -> None:
    """Keep new camera consumers out of a reserved on-demand capture."""

    if getattr(resources, "on_demand_capture_active", False):
        raise HomeAssistantError("C300X on-demand capture is active")


def media_owner_stopping(resources: Any, owner: str) -> bool:
    """Check the shared stop boundary used by camera offers and HA services."""
    return bool(getattr(resources, "media_stop_counts", {}).get(owner))


@contextmanager
def media_stop_scope(resources: Any, owner: str) -> Iterator[None]:
    """Reject new offers until all overlapping stop operations have finished."""
    counts = getattr(resources, "media_stop_counts", None)
    if counts is None:
        counts = resources.media_stop_counts = {}
    counts[owner] = counts.get(owner, 0) + 1
    try:
        yield
    finally:
        counts[owner] -= 1
        if not counts[owner]:
            counts.pop(owner)


@dataclass
class OpeningOffer:
    task: asyncio.Task[Any]
    owner: str
    send_message: Callable[[Any], None] | None


class CameraWebRTCSessions:
    """Keep session cancellation independent of device/media stop policy."""

    def __init__(self, tasks: CameraBackgroundTasks) -> None:
        self._tasks = tasks
        self.active: dict[str, ProviderWebRTCSession] = {}
        self.candidates: dict[str, list[Any]] = {}
        self.offers: dict[str, OpeningOffer] = {}

    def active_ids(self, owner: str | None = None) -> list[str]:
        """Snapshot registered sessions, excluding offers still awaiting a provider."""
        return [
            key for key, session in self.active.items()
            if owner is None or session.owner == owner
        ]

    def has_resource(self, resource_id: str) -> bool:
        """Check whether a registered session still owns this media resource."""
        return any(session.resource_id == resource_id for session in self.active.values())

    def accepts_provider_messages(self, session_id: str, session: ProviderWebRTCSession) -> bool:
        """Reject callbacks from replaced, removed or cancelling sessions."""
        offer = self.offers.get(session_id)
        return self.active.get(session_id) is session and (
            offer is None or not offer.task.cancelling()
        )

    async def on_candidate(self, session_id: str, candidate: Any) -> None:
        """Forward ICE or buffer it within the pre-session resource limits."""
        if self._tasks.closing:
            return
        session = self.active.get(session_id)
        if session is not None:
            if not session.ready:
                if len(session.pending_candidates) < MAX_PRESESSION_WEBRTC_CANDIDATES:
                    session.pending_candidates.append(candidate)
                return
            await session.provider.async_on_webrtc_candidate(session_id, candidate)
            return
        pending = self.candidates.get(session_id)
        if pending is None:
            if len(self.candidates) >= MAX_PRESESSION_WEBRTC_SESSIONS:
                self.candidates.pop(next(iter(self.candidates)))
            pending = self.candidates[session_id] = []
        if len(pending) < MAX_PRESESSION_WEBRTC_CANDIDATES:
            pending.append(candidate)

    async def flush_candidates(self, session_id: str) -> None:
        """Replay buffered ICE candidates once the provider session is ready."""
        session = self.active.get(session_id)
        if session is None or not session.ready:
            return
        while session.pending_candidates:
            await session.provider.async_on_webrtc_candidate(
                session_id, session.pending_candidates.pop(0),
            )

    @contextmanager
    def opening(
        self, session_id: str, owner: str = "doorbell",
        send_message: Callable[[Any], None] | None = None,
    ) -> Iterator[None]:
        """Own an offer until completion, failure or cancellation cleanup."""
        if session_id in self.offers:
            raise ValueError("Session is already opening")
        task = asyncio.current_task()
        assert task is not None
        offer = self.offers[session_id] = OpeningOffer(task, owner, send_message)
        try:
            with self._tasks.track_current():
                yield
        finally:
            if self.offers.get(session_id) is offer:
                self.offers.pop(session_id)

    def ids_by_owner(self, owner: str) -> list[str]:
        """Include offers which have not reached provider/session registration."""
        return list(dict.fromkeys(
            self.active_ids(owner)
            + [key for key, offer in self.offers.items() if offer.owner == owner]
        ))

    def cancel_offer(self, session_id: str, *, reason: str | None = None) -> asyncio.Task[Any] | None:
        """Cancel once so repeated closes cannot interrupt cancellation cleanup."""
        offer = self.offers.get(session_id)
        if offer is None:
            return None
        if not offer.task.cancelling():
            offer.task.cancel()
            if reason is not None and offer.send_message is not None:
                with suppress(Exception):
                    offer.send_message({"type": "closed", "reason": reason})
        return offer.task

    async def close_after_offer(
        self, offer: asyncio.Task[Any] | None, close: Callable[[], Awaitable[None]],
    ) -> None:
        """Finish offer cleanup before closing any resulting provider session."""
        if offer is not None:
            # Entity removal also cancels the offer; avoid a second cancellation.
            await asyncio.gather(asyncio.shield(offer), return_exceptions=True)
        await close()

    async def stop_owner(
        self, resources: Any, owner: str, reason: str,
        close: Callable[..., Awaitable[None]], *,
        drain: Callable[[], Awaitable[None]] | None = None,
        session_ids: list[str] | None = None,
    ) -> None:
        """Cancel admission, await cleanup, then close this owner's sessions."""
        with media_stop_scope(resources, owner):
            ids = self.ids_by_owner(owner) if session_ids is None else session_ids
            opening = set(ids) & self.offers.keys()
            offers = [
                task for session_id in ids
                if (task := self.cancel_offer(session_id, reason=reason)) is not None
            ]
            await asyncio.gather(*(asyncio.shield(task) for task in offers), return_exceptions=True)
            for session_id in ids:
                await close(
                    session_id, stop_media=False,
                    notify_client=session_id not in opening, reason=reason,
                )
            if ids and drain is not None:
                await drain()
