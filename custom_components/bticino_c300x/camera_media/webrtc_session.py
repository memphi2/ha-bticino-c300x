"""WebRTC provider session helpers for C300X camera media."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class SessionOwner(StrEnum):
    """Owner of an active media / WebRTC session (also the camera media_owner)."""

    DOORBELL = "doorbell"
    HOME_CALL = "home_call"
    RING = "ring"
    EXTERNAL_MEDIA = "external_media"
    IDLE = "idle"
    UNKNOWN = "unknown"


def owner_is_home_call(owner: str) -> bool:
    """Return true for a Home Call owner."""

    return owner == SessionOwner.HOME_CALL


def owner_requires_explicit_stop(owner: str) -> bool:
    """Whether this owner's device media needs an explicit stop when its last
    session closes. Home Call has no RTSP-drain backstop (unlike doorbell), so
    a closed subscription must stop it or it lingers to its duration timeout."""

    return owner == SessionOwner.HOME_CALL


def owner_is_doorbell_media(owner: str) -> bool:
    """Whether this owner carries the ring/doorbell media stream -- i.e. any
    owner that is not a Home Call."""

    return owner != SessionOwner.HOME_CALL


class _OwnedSession:
    """Shared owner-capability predicates for the session dataclasses."""

    owner: str

    @property
    def is_home_call(self) -> bool:
        return owner_is_home_call(self.owner)

    @property
    def requires_explicit_stop(self) -> bool:
        return owner_requires_explicit_stop(self.owner)

    @property
    def is_doorbell_media(self) -> bool:
        return owner_is_doorbell_media(self.owner)


@dataclass
class ProviderWebRTCStreamContext(_OwnedSession):
    """Provider stream-source context for one WebRTC offer."""

    owner: str
    session_id: str
    wants_audio: bool
    wants_backchannel: bool
    media_started: bool = False
    provider_domain: str | None = None
    resource_id: str | None = None
    ring_call: bool = False
    ring_preview: bool = False


@dataclass
class ProviderWebRTCSession(_OwnedSession):
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
    return type(message).__name__ == "WebRTCError"


def short_session_id(session_id: str) -> str:
    """Return a compact WebRTC session id fragment for logs."""

    text = str(session_id)
    if len(text) <= 12:
        return text
    return f"...{text[-8:]}"
