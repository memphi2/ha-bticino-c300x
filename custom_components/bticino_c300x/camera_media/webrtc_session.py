"""WebRTC session helpers for C300X camera media."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from collections.abc import Callable, MutableMapping
from contextlib import suppress
from typing import Any

_LOGGER = logging.getLogger(__name__)


class NativeWebRTCSession:
    """Runtime resources for one native WebRTC session."""

    def __init__(
        self,
        peer: Any,
        *,
        owner: str = "doorbell",
        send_message: Any | None = None,
    ) -> None:
        self.peer = peer
        self.owner = owner
        self.send_message = send_message
        self.player: Any | None = None
        self.ice_flush_task: asyncio.Task[Any] | None = None
        self.renew_task: asyncio.Task[Any] | None = None
        self.talkback_task: asyncio.Task[Any] | None = None
        self.talkback_requested = False
        self.ring_call = False
        self.ring_preview = False
        self.talkback_active = False
        self.talkback_packets_sent = 0
        self.pending_ice_candidates: list[Any | None] = []


def webrtc_session_peer_closed(session: NativeWebRTCSession) -> bool:
    """Return true when aiortc has already moved the peer into a terminal state."""

    peer = getattr(session, "peer", None)
    if peer is None:
        return False
    for attr_name in ("connectionState", "iceConnectionState"):
        if getattr(peer, attr_name, None) in {"closed", "failed", "disconnected"}:
            return True
    return getattr(peer, "signalingState", None) == "closed"


class NativeWebRTCSessionRegistry:
    """Manage WebRTC session ownership and resource cleanup."""

    def __init__(
        self,
        sessions: MutableMapping[str, NativeWebRTCSession],
    ) -> None:
        self._sessions = sessions

    def active_media_sessions(self) -> int:
        """Return sessions that currently own a media player/track."""

        unique_resources: set[str] = set()
        standalone_sessions = 0
        for session in self._sessions.values():
            if session.player is None or webrtc_session_peer_closed(session):
                continue
            resource_id = getattr(session.player, "resource_id", None)
            if isinstance(resource_id, str) and resource_id:
                unique_resources.add(resource_id)
            else:
                standalone_sessions += 1
        return standalone_sessions + len(unique_resources)

    def has_sessions(self) -> bool:
        """Return true when at least one WebRTC session remains registered."""

        return bool(self._sessions)

    def session_ids(self) -> list[str]:
        """Return a stable snapshot of registered session IDs."""

        return list(self._sessions)

    def session_ids_by_owner(self, owner: str) -> list[str]:
        """Return session IDs for a given logical media owner."""

        return self.session_ids_matching(lambda session: getattr(session, "owner", None) == owner)

    def session_ids_for_ring_call(self) -> list[str]:
        """Return session IDs for active ring-call sessions."""

        return self.session_ids_matching(lambda session: session.ring_call)

    def session_ids_matching(
        self,
        predicate: Callable[[NativeWebRTCSession], bool],
    ) -> list[str]:
        """Return session IDs whose current session matches the predicate."""

        return [
            session_id
            for session_id, session in self._sessions.items()
            if predicate(session)
        ]

    async def async_close_session_resources(
        self,
        session_id: str,
        *,
        notify_client: bool = False,
        reason: str = "closed",
    ) -> NativeWebRTCSession | None:
        """Detach and close all HA-side resources for one WebRTC session."""

        session = self._sessions.pop(session_id, None)
        if session is None:
            return None

        _cancel_session_task(session.renew_task)
        session.renew_task = None
        _cancel_session_task(session.ice_flush_task)
        session.ice_flush_task = None
        _cancel_session_task(session.talkback_task)
        session.talkback_task = None

        if session.player is not None:
            with suppress(Exception):
                session.player.stop()
        if notify_client and session.send_message is not None:
            with suppress(Exception):
                session.send_message({"type": "closed", "reason": reason})
        await _async_cancel_peer_ice_check_tasks(session.peer)
        with suppress(Exception):
            await session.peer.close()

        return session


def _cancel_session_task(task: asyncio.Task[Any] | None) -> None:
    """Cancel a session task unless it is the currently running task."""

    if task is None or task is asyncio.current_task():
        return
    task.cancel()


async def _async_cancel_peer_ice_check_tasks(peer: Any) -> None:
    """Cancel pending aioice connectivity checks before transports close.

    aioice 0.10 can leave a STUN transaction retry timer alive briefly while
    RTCPeerConnection.close() tears down UDP transports. Cancelling active ICE
    check tasks first lets aioice cancel the transaction timer before the
    datagram transport is closed.
    """

    tasks: list[asyncio.Future[Any]] = []
    current_task = asyncio.current_task()
    for ice_transport in getattr(peer, "_RTCPeerConnection__iceTransports", ()) or ():
        connection = getattr(ice_transport, "_connection", None)
        for pair in getattr(connection, "_check_list", ()) or ():
            task = getattr(pair, "task", None)
            if (
                task is None
                or task is current_task
                or not hasattr(task, "cancel")
                or not hasattr(task, "done")
                or task.done()
            ):
                continue
            task.cancel()
            tasks.append(task)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def rtc_candidate_from_message(aiortc_modules: Any, candidate: Any) -> Any | None:
    """Build an aiortc ICE candidate from a HA WebRTC candidate message."""

    candidate_dict = candidate.to_dict() if hasattr(candidate, "to_dict") else {}
    candidate_sdp = str(
        candidate_dict.get("candidate")
        or getattr(candidate, "candidate", "")
        or ""
    )
    if not candidate_sdp:
        return None
    normalized_candidate_sdp = candidate_sdp
    if candidate_sdp.startswith("candidate:"):
        candidate_sdp = candidate_sdp[len("candidate:") :]
    if candidate_is_link_local(f"a={normalized_candidate_sdp}"):
        return None

    rtc_candidate = aiortc_modules.candidate_from_sdp(candidate_sdp)
    sdp_mid = candidate_dict.get("sdpMid")
    if sdp_mid is None:
        sdp_mid = getattr(candidate, "sdpMid", None)
    sdp_mline_index = candidate_dict.get("sdpMLineIndex")
    if sdp_mline_index is None:
        sdp_mline_index = getattr(candidate, "sdpMLineIndex", None)
    rtc_candidate.sdpMid = sdp_mid
    rtc_candidate.sdpMLineIndex = sdp_mline_index
    return rtc_candidate


async def async_flush_pending_webrtc_candidates(session: NativeWebRTCSession) -> None:
    """Replay ICE candidates that arrived before the remote description."""

    if getattr(session.peer, "remoteDescription", None) is None:
        return
    while session.pending_ice_candidates:
        await session.peer.addIceCandidate(session.pending_ice_candidates.pop(0))


def webrtc_server_configuration(
    aiortc_modules: Any,
    get_client_config: Any | None,
) -> Any:
    """Mirror HA's WebRTC ICE servers into the server-side aiortc peer."""

    patch_aioice_turn_transport_sendto()

    ice_servers: list[Any] = []
    if get_client_config is None:
        return aiortc_modules.RTCConfiguration(iceServers=ice_servers)

    try:
        client_config = get_client_config()
        rtc_config = getattr(client_config, "configuration", None)
        source_servers = getattr(rtc_config, "ice_servers", None) or []
    except Exception:  # noqa: BLE001 - ICE relay config must not break local video
        source_servers = []

    for server in source_servers:
        urls = getattr(server, "urls", None)
        if not urls:
            continue
        ice_servers.append(
            aiortc_modules.RTCIceServer(
                urls=urls,
                username=getattr(server, "username", None),
                credential=getattr(server, "credential", None),
            )
        )

    return aiortc_modules.RTCConfiguration(iceServers=ice_servers)


def patch_aioice_turn_transport_sendto(aioice_turn_module: Any | None = None) -> None:
    """Attach exception handling to aioice TURN send tasks.

    aioice 0.10 creates TURN ``send_data`` tasks without keeping or observing
    the returned task. A failed TURN channel bind can therefore surface in HA as
    "Task exception was never retrieved" even when WebRTC can fall back to
    another ICE candidate pair. The guard keeps expected STUN/TURN transaction
    errors out of the global log while preserving normal loop reporting for
    unexpected failures.
    """

    if aioice_turn_module is None:
        try:
            from aioice import turn as imported_aioice_turn_module
        except ImportError:
            return
        aioice_turn_module = imported_aioice_turn_module

    turn_transport = getattr(aioice_turn_module, "TurnTransport", None)
    if turn_transport is None:
        return

    original_sendto = getattr(turn_transport, "sendto", None)
    if original_sendto is None or getattr(original_sendto, "_c300x_guarded", False):
        return

    def _sendto(self: Any, data: bytes, addr: tuple[str, int]) -> None:
        inner_protocol = getattr(self, "_TurnTransport__inner_protocol", None)
        if inner_protocol is None or not hasattr(inner_protocol, "send_data"):
            original_sendto(self, data, addr)
            return
        task = asyncio.create_task(inner_protocol.send_data(data, addr))
        task.add_done_callback(_handle_aioice_turn_send_done)

    _sendto._c300x_guarded = True  # type: ignore[attr-defined]
    _sendto._c300x_original_sendto = original_sendto  # type: ignore[attr-defined]
    turn_transport.sendto = _sendto


def _handle_aioice_turn_send_done(task: asyncio.Task[Any]) -> None:
    """Consume expected aioice TURN transaction failures from send tasks."""

    try:
        exception = task.exception()
    except asyncio.CancelledError:
        return
    if exception is None:
        return
    if _is_expected_aioice_transaction_error(exception):
        _LOGGER.debug("Ignoring failed aioice TURN send task", exc_info=exception)
        return
    task.get_loop().call_exception_handler(
        {
            "message": "Unhandled aioice TURN send task exception",
            "exception": exception,
            "task": task,
        }
    )


def _is_expected_aioice_transaction_error(exception: BaseException) -> bool:
    """Return true for STUN/TURN transaction errors handled by ICE fallback."""

    exception_type = type(exception)
    return (
        exception_type.__module__ == "aioice.stun"
        and exception_type.__name__
        in {"TransactionFailed", "TransactionTimeout", "TransactionError"}
    )


def prefer_webrtc_codecs(peer: Any, aiortc_modules: Any) -> None:
    """Prefer C300X-compatible WebRTC video and browser audio codecs."""

    _prefer_h264(peer, aiortc_modules)
    _prefer_browser_audio(peer, aiortc_modules)


async def async_wait_for_ice_gathering(
    peer: Any,
    *,
    wait_seconds: float = 1.0,
) -> None:
    """Wait briefly for aiortc ICE gathering before sending the answer."""

    if peer.iceGatheringState == "complete":
        return

    done = asyncio.Event()

    def _on_icegatheringstatechange() -> None:
        if peer.iceGatheringState == "complete":
            done.set()

    peer.on("icegatheringstatechange")(_on_icegatheringstatechange)

    with suppress(asyncio.TimeoutError):
        await asyncio.wait_for(done.wait(), timeout=wait_seconds)


def filter_link_local_sdp_candidates(sdp: str) -> str:
    """Drop link-local/.local ICE candidates when better candidates exist."""

    lines = sdp.splitlines()
    candidate_lines = [line for line in lines if line.startswith("a=candidate:")]
    if not candidate_lines:
        return sdp

    usable_candidates = [
        line for line in candidate_lines if not candidate_is_link_local(line)
    ]
    if not usable_candidates:
        return sdp

    filtered = [
        line
        for line in lines
        if not line.startswith("a=candidate:") or not candidate_is_link_local(line)
    ]
    line_ending = "\r\n" if "\r\n" in sdp else "\n"
    suffix = line_ending if sdp.endswith(("\r\n", "\n")) else ""
    return line_ending.join(filtered) + suffix


def candidate_is_link_local(line: str) -> bool:
    """Return true for WebRTC host candidates known to be bad over HA Cloud."""

    parts = line[len("a=candidate:") :].split()
    if len(parts) < 6:
        return False
    address = parts[4].strip("[]").split("%", 1)[0].lower()
    if address.endswith(".local"):
        return True
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return parsed.is_link_local


def _prefer_h264(peer: Any, aiortc_modules: Any) -> None:
    capabilities = aiortc_modules.RTCRtpSender.getCapabilities("video")
    h264_codecs = [
        codec for codec in capabilities.codecs if codec.mimeType.lower() == "video/h264"
    ]
    other_codecs = [
        codec for codec in capabilities.codecs if codec.mimeType.lower() != "video/h264"
    ]
    if not h264_codecs:
        return

    for transceiver in peer.getTransceivers():
        if transceiver.kind == "video":
            with suppress(Exception):
                transceiver.setCodecPreferences([*h264_codecs, *other_codecs])


def _prefer_browser_audio(peer: Any, aiortc_modules: Any) -> None:
    capabilities = aiortc_modules.RTCRtpSender.getCapabilities("audio")
    preferred_mime_types = {"audio/opus", "audio/pcmu", "audio/pcma"}
    preferred_codecs = [
        codec
        for codec in capabilities.codecs
        if codec.mimeType.lower() in preferred_mime_types
    ]
    other_codecs = [
        codec
        for codec in capabilities.codecs
        if codec.mimeType.lower() not in preferred_mime_types
    ]
    if not preferred_codecs:
        return

    for transceiver in peer.getTransceivers():
        if transceiver.kind == "audio":
            with suppress(Exception):
                transceiver.setCodecPreferences([*preferred_codecs, *other_codecs])
