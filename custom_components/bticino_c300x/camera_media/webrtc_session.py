"""WebRTC provider session helpers for C300X camera media."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from homeassistant.components.camera import WebRTCError


@dataclass(frozen=True)
class ProviderWebRTCStreamContext:
    """Provider stream-source context for one WebRTC offer."""

    owner: str
    wants_audio: bool
    wants_backchannel: bool


@dataclass
class ProviderWebRTCSession:
    """Local HA-side WebRTC provider session state."""

    provider: Any
    owner: str
    send_message: Any
    wants_audio: bool
    wants_backchannel: bool
    resource_id: str
    ring_call: bool = False
    ring_preview: bool = False
    ready: bool = False
    pending_candidates: list[Any] = field(default_factory=list)


def webrtc_message_is_error(message: Any) -> bool:
    """Return true when a provider message is a WebRTC error payload."""

    if isinstance(message, Mapping):
        return message.get("type") == "error"
    as_dict = getattr(message, "as_dict", None)
    if callable(as_dict):
        with suppress(Exception):
            data = as_dict()
            if isinstance(data, Mapping):
                return data.get("type") == "error"
    return isinstance(WebRTCError, type) and isinstance(message, WebRTCError)


def short_session_id(session_id: str) -> str:
    """Return a compact WebRTC session id fragment for logs."""

    text = str(session_id)
    if len(text) <= 12:
        return text
    return f"...{text[-8:]}"
