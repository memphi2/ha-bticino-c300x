"""Helpers for C300X agent event payloads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .event_types import agent_event_key as agent_event_key


def ring_media_closed(data: Mapping[str, Any], call_id: Any) -> bool:
    """A doorbell_media_closed event ends the media of the ring with this call_id.

    The agent says whose media closed: ``data.kind`` is ``ring`` or ``view``,
    ``call_id`` the live call it belongs to. A view's close, or one of
    another call where both calls are known, leaves the ring's media open.
    """

    payload = data.get("data")
    if isinstance(payload, Mapping) and payload.get("kind") == "view":
        return False
    closed = data.get("call_id")
    return closed is None or call_id is None or closed == call_id
