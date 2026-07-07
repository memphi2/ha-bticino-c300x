"""Debug helpers for the C300X camera WebRTC provider path."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from contextlib import suppress
from typing import Any

from .webrtc_session import short_session_id as _short_session_id

_LOGGER = logging.getLogger("custom_components.bticino_c300x.camera")


def debug_safe_details(details: Mapping[str, Any]) -> dict[str, Any]:
    """Return compact debug fields without SDP, ICE candidates, tokens or URLs."""

    safe: dict[str, Any] = {}
    for key, value in details.items():
        text_key = str(key)
        lowered = text_key.lower()
        if any(
            unsafe in lowered
            for unsafe in ("candidate", "password", "sdp", "secret", "token", "url")
        ):
            continue
        if value is None or isinstance(value, bool | int | float):
            safe[text_key] = value
        elif isinstance(value, str):
            safe[text_key] = value[:160]
    return safe


def debug_value(item: Any, key: str, default: Any = None) -> Any:
    """Read a debug-only field from mapping or attribute style objects."""

    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def debug_status_details(status: Mapping[str, Any]) -> dict[str, Any]:
    """Return selected native media status fields useful for EOF RCA."""

    details: dict[str, Any] = {}
    bridge_data = status.get("bridge")
    bridge = bridge_data if isinstance(bridge_data, Mapping) else {}
    for key in (
        "media_owner",
        "external_media_active",
        "external_owner",
        "last_block_reason",
        "last_error",
        "last_rtp_at",
        "last_media_started_at",
        "last_rtsp_reject_reason",
        "video_bridge_stop_in_progress",
        "bt_media_start_attempts",
        "bt_media_stop_attempts",
        "rtp_packets",
    ):
        if key in status:
            details[f"status_{key}"] = status[key]
    for key in (
        "clients",
        "max_clients",
        "media_owner",
        "media_active",
        "media_starting",
        "call_active",
        "running",
        "stop_in_progress",
        "open_fds",
        "active_threads",
        "ring_call_active",
        "ring_media_active",
        "ring_audio_active",
        "ring_answer_requested",
        "ring_answered",
        "ring_hangup_requested",
        "unanswered_ring_call",
        "home_call_running",
        "home_call_active",
        "home_call_answered",
        "rtsp_options_requests",
        "rtsp_describe_requests",
        "rtsp_setup_requests",
        "rtsp_play_requests",
        "rtsp_teardown_requests",
        "rtsp_rejected_clients",
        "rtsp_rejected_describes",
        "rtsp_play_failures",
        "last_rtsp_method",
        "last_rtsp_reject_reason",
    ):
        if key in bridge:
            details[f"bridge_{key}"] = bridge[key]
    return debug_safe_details(details)


class WebRTCDebugMixin:
    """Mixin for DEBUG-only WebRTC media RCA breadcrumbs."""

    def _log_webrtc_debug(
        self,
        event: str,
        *,
        session_id: str | None = None,
        owner: str | None = None,
        provider: str | None = None,
        status: Mapping[str, Any] | None = None,
        **details: Any,
    ) -> None:
        """Log compact media RCA breadcrumbs only when integration debug is enabled."""

        if not _LOGGER.isEnabledFor(logging.DEBUG):
            return
        safe_details = debug_safe_details(details)
        if status is not None:
            safe_details.update(debug_status_details(status))
        detail_text = " ".join(
            f"{key}={value}" for key, value in sorted(safe_details.items())
        )
        _LOGGER.debug(
            "C300X WebRTC debug: event=%s session=%s owner=%s provider=%s "
            "media_state=%s video_owner=%s sessions=%s ready_sessions=%s %s",
            event,
            _short_session_id(session_id or ""),
            owner or "-",
            provider or "-",
            self._last_media_state.value,
            self._video_owner,
            len(self._provider_webrtc_sessions),
            sum(1 for session in self._provider_webrtc_sessions.values() if session.ready),
            detail_text,
        )

    async def _async_log_video_status_debug(
        self,
        event: str,
        *,
        session_id: str | None = None,
        owner: str | None = None,
        **details: Any,
    ) -> None:
        """Log a fresh native media status snapshot only for DEBUG RCA."""

        if not _LOGGER.isEnabledFor(logging.DEBUG):
            return
        status = await self._async_refresh_video_status_or_none(apply_status=False)
        self._log_webrtc_debug(
            event,
            session_id=session_id,
            owner=owner,
            status=status,
            **details,
        )

    async def _async_log_go2rtc_debug(
        self,
        provider: Any,
        event: str,
        *,
        session_id: str | None = None,
        owner: str | None = None,
        status: Mapping[str, Any] | None = None,
        **details: Any,
    ) -> None:
        """Log HA go2rtc provider state without exposing private URLs or SDP."""

        if not _LOGGER.isEnabledFor(logging.DEBUG):
            return
        provider_details = self._go2rtc_provider_debug_details(provider)
        provider_details.update(await self._async_go2rtc_stream_debug_details(provider))
        provider_details.update(details)
        if status is None:
            status = await self._async_refresh_video_status_or_none(apply_status=False)
        self._log_webrtc_debug(
            event,
            session_id=session_id,
            owner=owner,
            provider=str(getattr(provider, "domain", type(provider).__name__)),
            status=status,
            **provider_details,
        )

    def _go2rtc_provider_debug_details(self, provider: Any) -> dict[str, Any]:
        """Return safe details from HA's go2rtc provider object."""

        details: dict[str, Any] = {
            "go2rtc_provider_class": type(provider).__name__,
        }
        sessions = getattr(provider, "_sessions", None)
        if isinstance(sessions, Mapping):
            details["go2rtc_ws_sessions"] = len(sessions)
            if sessions:
                details["go2rtc_ws_session_ids"] = ",".join(
                    _short_session_id(str(session_id)) for session_id in sessions
                )[:160]
        return details

    async def _async_go2rtc_stream_debug_details(
        self,
        provider: Any,
    ) -> dict[str, Any]:
        """Return safe go2rtc stream inventory details when HA exposes them."""

        rest_client = getattr(provider, "_rest_client", None)
        streams_api = getattr(rest_client, "streams", None)
        list_streams = getattr(streams_api, "list", None)
        if not callable(list_streams):
            return {"go2rtc_stream_inventory": "unavailable"}
        try:
            streams = await list_streams()
        except Exception as err:  # noqa: BLE001 - debug must never break media
            return {"go2rtc_stream_inventory_error": type(err).__name__}
        if not isinstance(streams, Mapping):
            return {"go2rtc_stream_inventory": type(streams).__name__}

        matched_streams = 0
        matched_producers = 0
        matched_consumers = 0
        matched_paths: list[str] = []
        matched_ids: list[str] = []
        for stream_id, stream in streams.items():
            producers = tuple(debug_value(stream, "producers", ()) or ())
            consumers = tuple(debug_value(stream, "consumers", ()) or ())
            producer_paths = tuple(
                path
                for producer in producers
                if (
                    path := self._debug_rtsp_path(
                        str(debug_value(producer, "url", ""))
                    )
                )
            )
            if not self._go2rtc_stream_is_c300x(stream_id, stream):
                continue
            matched_streams += 1
            matched_producers += len(producers)
            matched_consumers += len(consumers)
            matched_ids.append(str(stream_id))
            matched_paths.extend(path for path in producer_paths if "/doorbell" in path)

        details: dict[str, Any] = {
            "go2rtc_streams_total": len(streams),
            "go2rtc_c300x_streams": matched_streams,
            "go2rtc_c300x_producers": matched_producers,
            "go2rtc_c300x_consumers": matched_consumers,
        }
        if matched_paths:
            details["go2rtc_c300x_paths"] = ",".join(
                sorted(set(matched_paths))
            )[:160]
        if matched_ids:
            details["go2rtc_c300x_stream_ids"] = ",".join(
                sorted(set(matched_ids))
            )[:160]
        return details

    def _go2rtc_stream_is_c300x(self, stream_id: Any, stream: Any) -> bool:
        """Return true when a go2rtc stream belongs to this integration."""

        producers = tuple(debug_value(stream, "producers", ()) or ())
        producer_paths = tuple(
            path
            for producer in producers
            if (path := self._debug_rtsp_path(str(debug_value(producer, "url", ""))))
        )
        return any("/doorbell" in path for path in producer_paths) or any(
            marker in str(stream_id).lower()
            for marker in ("bticino", "c300x", "doorbell")
        )

    def _debug_rtsp_path(self, stream_url: str) -> str:
        """Return the RTSP path/query fragment without logging the private host."""

        path_start = stream_url.find("/", len("rtsp://"))
        if path_start == -1:
            return ""
        return stream_url[path_start:]

    def _webrtc_message_field(self, message: Any, field: str) -> str | None:
        """Return one safe field from a provider WebRTC message."""

        if isinstance(message, Mapping):
            value = message.get(field)
        else:
            as_dict = getattr(message, "as_dict", None)
            value = None
            if callable(as_dict):
                with suppress(Exception):
                    data = as_dict()
                    if isinstance(data, Mapping):
                        value = data.get(field)
            if value is None:
                value = getattr(message, field, None)
        return str(value)[:160] if value is not None else None
