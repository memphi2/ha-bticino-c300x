"""Debug websocket helpers for the C300X integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

import voluptuous as vol

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(f"custom_components.{DOMAIN}.camera")

_WsCommand = Callable[..., Any]
_WsCommandDecorator = Callable[[_WsCommand], _WsCommand]
_WsCommandFactory = Callable[[dict[Any, Any]], _WsCommandDecorator]
_CLIENT_DEBUG_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("event", ("event",)),
    ("sequence", ("sequence",)),
    ("session", ("session_id",)),
    ("entity", ("entity_id",)),
    ("mode", ("mode",)),
    ("reason", ("reason",)),
    ("message", ("message",)),
    ("debug_state", ("debug_state",)),
    ("layer", ("observation", "likelyLayer")),
    ("connected", ("observation", "connected")),
    ("inbound", ("observation", "inboundProgressing")),
    ("decoding", ("observation", "decodingProgressing")),
    ("media_progress", ("observation", "mediaProgressing")),
    ("conn", ("connection_state",)),
    ("ice", ("ice_connection_state",)),
    ("ice_gathering", ("ice_gathering_state",)),
    ("signaling", ("signaling_state",)),
    ("media_event", ("media_event",)),
    ("peer_event", ("peer_event",)),
    ("media_error_code", ("media_error", "code")),
    ("current_time", ("media", "currentTime")),
    ("current_time_rate", ("media", "currentTimePerSecond")),
    ("ready_state", ("media", "readyState")),
    ("network_state", ("media", "networkState")),
    ("paused", ("media", "paused")),
    ("ended", ("media", "ended")),
    ("video_width", ("media", "videoWidth")),
    ("video_height", ("media", "videoHeight")),
    ("total_video_frames", ("media", "playbackQuality", "totalVideoFrames")),
    (
        "total_video_frames_rate",
        ("media", "playbackQuality", "totalVideoFramesPerSecond"),
    ),
    ("dropped_video_frames", ("media", "playbackQuality", "droppedVideoFrames")),
    (
        "dropped_video_frames_rate",
        ("media", "playbackQuality", "droppedVideoFramesPerSecond"),
    ),
    (
        "webkit_decoded_frames",
        ("media", "playbackQuality", "webkitDecodedFrameCount"),
    ),
    (
        "webkit_decoded_frames_rate",
        ("media", "playbackQuality", "webkitDecodedFrameCountPerSecond"),
    ),
    (
        "webkit_dropped_frames",
        ("media", "playbackQuality", "webkitDroppedFrameCount"),
    ),
    ("bytes_rate", ("inbound", "video", "bytesReceivedPerSecond")),
    ("frames_per_second", ("inbound", "video", "framesPerSecond")),
    ("frames_decoded_rate", ("inbound", "video", "framesDecodedPerSecond")),
    ("frames_received_rate", ("inbound", "video", "framesReceivedPerSecond")),
    ("packets_rate", ("inbound", "video", "packetsReceivedPerSecond")),
    ("packets_lost", ("inbound", "video", "packetsLost")),
    ("jitter", ("inbound", "video", "jitter")),
    ("freeze_count", ("inbound", "video", "freezeCount")),
    ("freeze_duration", ("inbound", "video", "totalFreezesDuration")),
    ("out_audio_bytes_rate", ("outbound", "audio", "bytesSentPerSecond")),
    ("out_audio_packets_rate", ("outbound", "audio", "packetsSentPerSecond")),
    ("rtt", ("candidate_pair", "currentRoundTripTime")),
    ("local_candidate", ("candidates", "local", "candidateType")),
    ("remote_candidate", ("candidates", "remote", "candidateType")),
    ("local_protocol", ("candidates", "local", "protocol")),
)


def async_register_debug_ws(hass: HomeAssistant) -> None:
    """Register integration debug websocket commands."""

    from homeassistant.components import websocket_api

    async_register_command = cast(
        Callable[[Any, _WsCommand], None],
        websocket_api.async_register_command,
    )
    async_response = cast(
        _WsCommandDecorator,
        websocket_api.async_response,  # type: ignore[attr-defined]
    )
    websocket_command = cast(
        _WsCommandFactory,
        websocket_api.websocket_command,  # type: ignore[attr-defined]
    )

    @websocket_command({vol.Required("type"): "bticino_c300x/debug/status"})
    @async_response
    async def ws_debug_status(
        _hass: HomeAssistant,
        connection: Any,
        msg: dict[str, Any],
    ) -> None:
        enabled = _LOGGER.isEnabledFor(logging.DEBUG)
        connection.send_result(
            msg["id"],
            {
                "enabled": enabled,
                "webrtc_stats": enabled,
            },
        )

    async_register_command(hass, ws_debug_status)

    @websocket_command(
        {
            vol.Required("type"): "bticino_c300x/debug/webrtc_stats",
            vol.Required("snapshot"): dict,
        }
    )
    @async_response
    async def ws_webrtc_stats(
        _hass: HomeAssistant,
        connection: Any,
        msg: dict[str, Any],
    ) -> None:
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "C300X WebRTC client debug: %s",
                _format_client_debug_snapshot(msg["snapshot"]),
            )
        connection.send_result(msg["id"], {"ok": True})

    async_register_command(hass, ws_webrtc_stats)


def _format_client_debug_snapshot(snapshot: dict[str, Any]) -> str:
    parts: list[str] = []
    for name, path in _CLIENT_DEBUG_FIELDS:
        value = _nested_value(snapshot, path)
        if value is None or value == "":
            continue
        if name == "session":
            value = _short_session_id(str(value))
        parts.append(f"{name}={_format_debug_value(value)}")
    return " ".join(parts)


def _nested_value(source: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = source
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _short_session_id(session_id: str) -> str:
    if len(session_id) <= 8:
        return session_id
    return f"...{session_id[-8:]}"


def _format_debug_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value).replace(" ", "_")
