"""WebRTC provider session helpers for C300X camera media."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Mapping, MutableMapping
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


async def _async_retry_failed_provider_close(
    provider: Any,
    sessions: MutableMapping[Any, Any],
    session_id: str,
    session_entry: Any,
) -> None:
    """Give a failed websocket close one retry, then drop its entry.

    Nothing calls this close a second time: the camera has already forgotten
    the session. An entry left behind for "a later retry" would therefore stay
    in the provider for good. A session that replaced ours is never touched.
    """

    if sessions.get(session_id) is not session_entry:
        return
    close_session = getattr(provider, "async_close_session", None)
    if callable(close_session):
        try:
            result = close_session(session_id)
            if inspect.isawaitable(result):
                await result
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the entry is dropped below either way
            pass
    if sessions.get(session_id) is session_entry:
        sessions.pop(session_id, None)


async def async_close_provider_session(
    provider: Any,
    session_id: str,
    log_debug: Callable[..., None],
) -> str:
    """Close the provider session and await HA go2rtc consumer shutdown."""

    sessions = getattr(provider, "_sessions", None)
    if isinstance(sessions, MutableMapping):
        session_entry = sessions.get(session_id)
        if session_entry is None:
            return "go2rtc_ws_missing"
        # HA providers may store a websocket directly or wrap it with camera
        # metadata. Keep the original value for retry after an interrupted close.
        ws_client = getattr(session_entry, "ws_client", session_entry)
        close = getattr(ws_client, "close", None)
        if callable(close):
            sessions.pop(session_id)
            try:
                result = close()
                if inspect.isawaitable(result):
                    await result
                    return "go2rtc_ws_awaited"
                return "go2rtc_ws_sync"
            except asyncio.CancelledError:
                sessions.setdefault(session_id, session_entry)
                raise
            except Exception as err:  # noqa: BLE001 - close cleanup must continue
                sessions.setdefault(session_id, session_entry)
                log_debug(
                    "provider_go2rtc_ws_close_failed",
                    session_id=session_id,
                    provider=str(getattr(provider, "domain", type(provider).__name__)),
                    error_type=type(err).__name__,
                )
                await _async_retry_failed_provider_close(
                    provider, sessions, session_id, session_entry
                )
                return "go2rtc_ws_failed"
        # Unknown private layouts belong to the provider's public close API.
        # Leave its session entry present so that API can find it.

    close_session = getattr(provider, "async_close_session", None)
    if not callable(close_session):
        return "provider_close_missing"
    try:
        result = close_session(session_id)
        if inspect.isawaitable(result):
            await result
            return "provider_close_awaited"
        return "provider_close_sync"
    except Exception as err:  # noqa: BLE001 - close cleanup must continue
        log_debug(
            "provider_close_failed",
            session_id=session_id,
            provider=str(getattr(provider, "domain", type(provider).__name__)),
            error_type=type(err).__name__,
        )
        return "provider_close_failed"


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
