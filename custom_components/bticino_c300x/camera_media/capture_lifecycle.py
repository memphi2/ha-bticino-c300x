"""Conservative call ownership for automatic ring-capture cleanup."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from homeassistant.core import callback

from ..const import EVENT_AGENT_EVENT_RECEIVED
from ..event_payload import agent_event_key


class RingCaptureCallGuard:
    """Reject cleanup after observed call transitions or ambiguous status.

    The agent exposes no call id or conditional hangup. Its media-start timestamp
    is only corroborating evidence, not an atomic call-ownership token.
    """

    def __init__(self, hass: Any, entry_id: str) -> None:
        self.invalidated = False
        self.finished = False
        self.started_at: str | None = None
        task = asyncio.current_task()

        @callback
        def changed(event: Any) -> None:
            if event.data.get("entry_id") != entry_id:
                return
            if agent_event_key(event.data) not in {
                "doorbell_pressed", "doorbell_media_closed", "call_ended",
                "home_call_started", "agent_restarted",
            }:
                return
            self.invalidated = True
            if self.finished:
                # The capture is done and published. The call changing now only
                # decides whether the cleanup may hang up; it must not turn the
                # finished capture into a cancelled one.
                return
            if task is not None and not task.done() and not task.cancelling():
                task.cancel()

        listen = getattr(getattr(hass, "bus", None), "async_listen", None)
        self._unsubscribe = listen(EVENT_AGENT_EVENT_RECEIVED, changed) if callable(listen) else None

    def observe_answered(self, status: Mapping[str, Any]) -> None:
        self.started_at = _media_started_at(status)

    def matches(self, status: Mapping[str, Any]) -> bool:
        bridge = status.get("bridge")
        if not isinstance(bridge, Mapping):
            return False
        # The recorder has disconnected before cleanup. Any remaining client
        # may be a newer viewer; unknown counts cannot authorize hangup either.
        clients = bridge.get("clients")
        if type(clients) is not int or clients != 0:
            return False
        return bool(
            self._unsubscribe is not None
            and not self.invalidated
            and self.started_at is not None
            and _media_started_at(status) == self.started_at
            and (status.get("media_owner") or bridge.get("media_owner")) == "ring"
            and (bridge.get("ring_answered") or bridge.get("ring_audio_active"))
            and not bridge.get("ring_hangup_requested")
            and not status.get("external_media_active")
            and not bridge.get("external_media_active")
        )

    def close(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None


def _media_started_at(status: Mapping[str, Any]) -> str | None:
    bridge = status.get("bridge")
    value = bridge.get("last_media_started_at") if isinstance(bridge, Mapping) else None
    if value is None:
        value = status.get("last_media_started_at")
    return value if isinstance(value, str) and value.strip() else None
