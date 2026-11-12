"""Camera entity for the C300X doorbell WebRTC stream."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from contextlib import suppress
from contextvars import ContextVar
from typing import Any, cast

from homeassistant.components.camera import Camera
from homeassistant.components.stream import (
    CONF_RTSP_TRANSPORT,
    CONF_USE_WALLCLOCK_AS_TIMESTAMPS,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from propcache.api import cached_property

from .agent_diagnostics import publish_agent_media_facts
from .camera_media import webrtc_debug as _webrtc_debug
from .camera_media.background_tasks import CameraBackgroundTasks
from .camera_media.ha_compat import (
    CameraEntityCapabilities,
    CameraEntityFeature,
    WebRTCError,
    WebRTCSendMessage,
)
from .camera_media.ha_compat import (
    async_get_supported_webrtc_provider as _async_get_supported_webrtc_provider,
)
from .camera_media.home_call_ws import (
    async_register_home_call_ws as _async_register_home_call_ws,
)
from .camera_media.rtsp_orchestrator import (
    CameraRtspOrchestrator,
    CameraRtspOrchestratorSettings,
)
from .camera_media.rtsp_url import (
    agent_host_for_socket as _agent_host_for_socket,
)
from .camera_media.rtsp_url import (
    agent_host_for_url as _agent_host_for_url,
)
from .camera_media.rtsp_url import (
    build_rtsp_url as _build_rtsp_url,
)
from .camera_media.sdp import offer_can_send_microphone as _offer_can_send_microphone
from .camera_media.sdp import offer_has_audio as _offer_has_audio
from .camera_media.sdp import (
    offer_should_use_audio_stream as _offer_should_use_audio_stream,
)
from .camera_media.session_lifecycle import (
    CameraWebRTCSessions,
    media_owner_stopping,
)
from .camera_media.state_machine import (
    MediaState,
    MediaStateInput,
    MediaStateOutput,
    derive_media_state,
    media_state_input_from_video_status,
    status_reports_agent_idle,
)
from .camera_media.webrtc_debug import WebRTCDebugMixin
from .camera_media.webrtc_ice_filter import filter_webrtc_message_for_entry
from .camera_media.webrtc_session import (
    ProviderWebRTCSession as _ProviderWebRTCSession,
)
from .camera_media.webrtc_session import (
    ProviderWebRTCStreamContext as _ProviderWebRTCStreamContext,
)
from .camera_media.webrtc_session import async_close_provider_session
from .camera_media.webrtc_session import (
    owner_is_doorbell_media as _owner_is_doorbell_media,
)
from .camera_media.webrtc_session import (
    owner_is_home_call as _owner_is_home_call,
)
from .camera_media.webrtc_session import (
    short_session_id as _short_session_id,
)
from .camera_media.webrtc_session import (
    webrtc_message_is_error as _webrtc_message_is_error,
)
from .const import (
    CONF_AGENT_HOST,
    CONF_NATIVE_TWO_WAY_AUDIO,
    CONF_VIDEO_PORT,
    CONF_VIDEO_STREAM_PATH,
    DEFAULT_VIDEO_PORT,
    DEFAULT_VIDEO_STREAM_PATH,
    EVENT_AGENT_EVENT_RECEIVED,
    SIGNAL_SYSTEM_METRICS_CHANGED,
)
from .device_user import media_user_attribute
from .doorstation_audio import doorstation_audio_gain_db
from .entity import C300XEntity, entry_config_value, supports_capability
from .entry_types import BticinoC300XConfigEntry
from .event_payload import agent_event_key
from .media_status import (
    home_call_payload as _home_call_payload,
)
from .media_status import (
    home_call_status_has_media as _home_call_status_has_media,
)
from .media_status import (
    rtsp_client_count_from_status as _rtsp_client_count_from_status,
)
from .media_watchdog import AgentCpuWatchdog, handle_agent_cpu_metrics_changed
from .value_parsing import (
    freeze_state_value as _freeze_state_value,
)
from .value_parsing import optional_mapping, optional_string
from .video import (
    doorbell_camera_unique_id,
)

_CameraStateSnapshot = tuple[Any, Any, Any]
PARALLEL_UPDATES = 0
VIDEO_WINDOW_EVENTS = {"doorbell_pressed", "doorbell_view_requested"}
VIDEO_WINDOW_CLOSED_EVENTS = {"doorbell_media_closed"}
HOME_CALL_EVENTS = {"home_call_started", "home_call_answered", "home_call_ended"}
RING_CALL_STATES = {
    MediaState.RING_PENDING,
    MediaState.RING_PREVIEW_ACTIVE,
    MediaState.RING_ANSWERING,
    MediaState.RING_ACTIVE,
    MediaState.RING_HANGING_UP,
}
UNANSWERED_RING_STATES = {
    MediaState.RING_PENDING,
    MediaState.RING_PREVIEW_ACTIVE,
}
RTSP_READY_CONNECT_TIMEOUT_SECONDS = 1.0
RTSP_READY_INTERVAL_SECONDS = 0.25
RTSP_READY_TIMEOUT_SECONDS = 6.0
RTSP_FAILURE_COOLDOWN_SECONDS = 20.0
RING_CALL_WAIT_INTERVAL_SECONDS = 0.2
RING_CALL_WAIT_TIMEOUT_SECONDS = 4.0
WEBRTC_PROVIDER_CLOSE_DRAIN_INTERVAL_SECONDS = 0.05
WEBRTC_PROVIDER_CLOSE_DRAIN_TIMEOUT_SECONDS = 1.0
STILL_IMAGE_CONTENT_TYPE = "image/svg+xml"
STILL_IMAGE_BYTES = b"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360"><rect width="640" height="360" fill="#111820"/><g fill="none" stroke="#8da2b5" stroke-width="16" stroke-linecap="round" stroke-linejoin="round"><path d="M216 152h178v96H216z"/><path d="M394 180l82-46v132l-82-46z"/><path d="M250 152l-32-56h174l-32 56"/><path d="M305 248v48"/><path d="M250 296h142"/></g></svg>"""
TALKBACK_CODEC = "speex/8000"
TALKBACK_RTP_PAYLOAD_TYPE = 97
_LOGGER = logging.getLogger(__name__)

_PROVIDER_WEBRTC_STREAM_CONTEXT: ContextVar[_ProviderWebRTCStreamContext | None] = (
    ContextVar("bticino_c300x_provider_webrtc_stream_context", default=None)
)
_debug_safe_details = _webrtc_debug.debug_safe_details
_debug_status_details = _webrtc_debug.debug_status_details


def _media_decision_is_ring_call(decision: MediaStateOutput) -> bool:
    return decision.state in RING_CALL_STATES


def _media_decision_is_unanswered_ring(decision: MediaStateOutput) -> bool:
    return decision.state in UNANSWERED_RING_STATES


def _capability_supported_if_known(entry: BticinoC300XConfigEntry, capability: str) -> bool:
    capabilities = getattr(getattr(entry, "runtime_data", None), "capabilities", None)
    if not isinstance(capabilities, dict) or not capabilities:
        return True
    return supports_capability(entry, capability)


def _camera_state_snapshot(camera: C300XDoorbellCamera) -> _CameraStateSnapshot:
    """Return the HA-visible camera state surface used for write de-duplication."""

    return (
        getattr(camera, "_attr_is_streaming", False),
        getattr(camera, "_attr_available", True),
        _freeze_state_value(camera.extra_state_attributes),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the optional C300X WebRTC camera."""

    if supports_capability(entry, "doorbell_video"):
        async_add_entities([C300XDoorbellCamera(entry)])


class C300XDoorbellCamera(WebRTCDebugMixin, C300XEntity, Camera):
    """Camera that exposes the agent media bridge through native WebRTC."""

    _attr_icon = "mdi:cctv"
    _attr_should_poll = False
    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_translation_key = "doorbell_camera"

    def __init__(self, entry: BticinoC300XConfigEntry) -> None:
        Camera.__init__(self)
        C300XEntity.__init__(self, entry, "doorbell_camera")
        self._runtime_data = entry.runtime_data
        self._background_tasks = CameraBackgroundTasks()
        self._attr_unique_id = doorbell_camera_unique_id(entry)
        self._attr_is_streaming = False
        self.content_type = STILL_IMAGE_CONTENT_TYPE
        self._video_window_available = False
        self._video_stream_path: str | None = None
        self._audio_stream_path: str | None = None
        self._recorder_stream_path: str | None = None
        self._bridge_available = False
        self._bridge_status: dict[str, Any] = {}
        self._video_owner = "unknown"
        self._external_media_active = False
        self._external_owner: str | None = None
        self._last_video_block_reason: str | None = None
        self._last_media_state = MediaState.UNKNOWN
        self._last_media_decision = derive_media_state(
            MediaStateInput(video_owner="unknown")
        )
        self._rtsp_prepare_lock = asyncio.Lock()
        self._rtsp_ready_lock = asyncio.Lock()
        self._rtsp_unavailable_until = 0.0
        self._last_rtsp_error: str | None = None
        self._rtsp_cooldown_scope: str | None = None
        self._rtsp_state_event_revision = 0
        self._rtsp_state_event_waiters: set[asyncio.Future[None]] = set()
        self._rtsp_orchestrator = CameraRtspOrchestrator(
            self,
            settings=CameraRtspOrchestratorSettings(
                rtsp_ready_connect_timeout_seconds=RTSP_READY_CONNECT_TIMEOUT_SECONDS,
                rtsp_ready_interval_seconds=RTSP_READY_INTERVAL_SECONDS,
                rtsp_ready_timeout_seconds=RTSP_READY_TIMEOUT_SECONDS,
                rtsp_failure_cooldown_seconds=RTSP_FAILURE_COOLDOWN_SECONDS,
                ring_call_wait_interval_seconds=RING_CALL_WAIT_INTERVAL_SECONDS,
                ring_call_wait_timeout_seconds=RING_CALL_WAIT_TIMEOUT_SECONDS,
            ),
        )
        self._agent_cpu_watchdog = AgentCpuWatchdog()
        self._webrtc_sessions = CameraWebRTCSessions(self._background_tasks)
        self._reconcile_in_flight = False
        self._last_state_snapshot: _CameraStateSnapshot | None = None
        if not hasattr(self, "stream_options"):
            self.stream_options = {}
        self.stream_options[CONF_RTSP_TRANSPORT] = "tcp"
        self.stream_options[CONF_USE_WALLCLOCK_AS_TIMESTAMPS] = True

    @property
    def available(self) -> bool:
        """Return whether the configured RTSP endpoint is addressable."""

        return super().available

    @property
    def entity_picture(self) -> None:  # type: ignore[override]
        """Keep the entity-list representation on the configured CCTV icon."""

        return None

    @cached_property
    def use_stream_for_stills(self) -> bool:
        """Avoid HA background stream workers for still images.

        The C300X starts video on demand. Asking Home Assistant to build stills from
        RTSP can create repeated background ffmpeg attempts while the doorbell media
        bridge is intentionally idle. Live viewing still uses native WebRTC.
        """

        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose compact user-facing media state without bridge internals."""

        return {
            "media_state": self._last_media_state.value,
            "media_primary_action": self._last_media_decision.primary_action.value,
            "video_window_available": self._video_window_available,
            "video_owner": self._video_owner,
            "external_media_active": self._external_media_active,
            "external_owner": self._external_owner,
            "last_video_block_reason": self._last_video_block_reason,
            "talkback_supported": self._talkback_supported(),
            # The configured doorstation gain (from HA's own config-flow option,
            # not the agent) so the card can apply it client-side in PCMU mode
            # where the agent stays at passthrough.
            "doorstation_audio_gain_db": doorstation_audio_gain_db(self._entry),
            **media_user_attribute(self._entry),
        }

    async def async_update(self) -> None:
        """Refresh doorbell video metadata on explicit HA update requests."""

        try:
            status = await self._runtime_data.api.async_doorbell_video_status()
        except Exception:  # noqa: BLE001 - keep explicit refresh non-fatal
            self._bridge_available = False
            self._attr_available = False
            return
        self._apply_status(status)
        self._attr_available = True

    def camera_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes:
        """Return a local still fallback instead of touching the C300X media path."""

        return STILL_IMAGE_BYTES

    async def async_camera_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes:
        """Return a local still fallback without starting an on-demand video session.

        The C300X video path is session based. Home Assistant and HA Cloud may
        ask for a camera proxy still before opening WebRTC; using the base camera
        implementation raises NotImplementedError, while warming RTSP here would
        create surprise device load. Live viewing continues through WebRTC.
        """

        return STILL_IMAGE_BYTES

    async def stream_source(self) -> str:
        """Return the RTSP source HA or its WebRTC provider should consume."""

        provider_context = _PROVIDER_WEBRTC_STREAM_CONTEXT.get()
        owner = provider_context.owner if provider_context is not None else "doorbell"
        if self._background_tasks.closing or media_owner_stopping(self._runtime_data.resources, owner):
            raise HomeAssistantError("C300X media is stopping")
        if provider_context is not None:
            if provider_context.session_id not in self._webrtc_sessions.active:
                raise HomeAssistantError("C300X WebRTC session is closed")
            if provider_context.is_home_call:
                stream_url = await self._async_prepare_home_call_rtsp_stream()
            else:
                stream_url = await self._async_prepare_provider_rtsp_stream(
                    provider_context
                )
            provider_context.media_started = True
            if provider_context.wants_backchannel:
                stream_url = f"{stream_url}#backchannel=1"
            self._log_webrtc_debug(
                "provider_stream_source",
                session_id=provider_context.session_id,
                owner=provider_context.owner,
                provider=provider_context.provider_domain,
                status=(
                    await self._async_refresh_video_status_or_none(apply_status=False)
                    if _LOGGER.isEnabledFor(logging.DEBUG)
                    else None
                ),
                wants_audio=provider_context.wants_audio,
                wants_backchannel=provider_context.wants_backchannel,
                ring_call=provider_context.ring_call,
                ring_preview=provider_context.ring_preview,
                resource_id=provider_context.resource_id,
                rtsp_path=self._debug_rtsp_path(stream_url),
                media_started=provider_context.media_started,
            )
            return stream_url
        return await self._async_prepare_rtsp_stream(audio=True)

    async def _async_prepare_provider_rtsp_stream(
        self,
        provider_context: _ProviderWebRTCStreamContext,
    ) -> str:
        """Prepare a provider RTSP source without downgrading on-demand media.

        Standard HA camera surfaces may offer video only. For regular on-demand
        viewing we still use the agent's audio+video path because that is the
        stable go2rtc source. Unanswered ring previews keep the video-only path
        so multiple preview browsers can continue to share the same upstream.
        """

        if provider_context.wants_audio:
            return await self._async_prepare_rtsp_stream(audio=True)
        status = await self._async_refresh_video_status_or_none(apply_status=False)
        decision = (
            self._derive_media_decision(status)
            if status is not None
            else self._last_media_decision
        )
        return await self._async_prepare_rtsp_stream(
            audio=not _media_decision_is_unanswered_ring(decision)
        )

    async def async_handle_async_webrtc_offer(
        self,
        offer_sdp: str,
        session_id: str,
        send_message: WebRTCSendMessage,
    ) -> None:
        """Handle browser WebRTC offers through Home Assistant's WebRTC provider."""

        await self._async_handle_webrtc_offer(
            offer_sdp,
            session_id,
            send_message,
            owner="doorbell",
        )

    async def async_handle_home_call_webrtc_offer(
        self,
        offer_sdp: str,
        session_id: str,
        send_message: WebRTCSendMessage,
        *,
        duration_seconds: int | None = None,
    ) -> None:
        """Handle an audio-only Home Call WebRTC offer through the provider."""

        await self._async_handle_webrtc_offer(
            offer_sdp,
            session_id,
            send_message,
            owner="home_call",
            duration_seconds=duration_seconds,
        )

    async def _async_handle_webrtc_offer(
        self,
        offer_sdp: str,
        session_id: str,
        send_message: WebRTCSendMessage,
        *,
        owner: str,
        duration_seconds: int | None = None,
    ) -> None:
        """Handle a WebRTC offer for doorbell video or Home Call audio."""

        if self._background_tasks.closing:
            send_message(WebRTCError("bticino_webrtc_offer_failed", "Camera is unloading"))
            return
        if media_owner_stopping(self._runtime_data.resources, owner):
            send_message(WebRTCError("bticino_webrtc_offer_failed", "Media is stopping"))
            return
        if session_id in self._webrtc_sessions.offers:
            send_message(WebRTCError("bticino_webrtc_offer_failed", "Session is already opening"))
            return
        with self._webrtc_sessions.opening(session_id, owner, send_message):
            await self._async_handle_owned_webrtc_offer(
                offer_sdp, session_id, send_message,
                owner=owner, duration_seconds=duration_seconds,
            )

    async def _async_handle_owned_webrtc_offer(
        self,
        offer_sdp: str,
        session_id: str,
        send_message: WebRTCSendMessage,
        *,
        owner: str,
        duration_seconds: int | None,
    ) -> None:
        """Build an offer while entity removal owns its cancellation and cleanup."""

        has_audio_media = _offer_has_audio(offer_sdp)
        talkback_requested = _offer_can_send_microphone(offer_sdp)
        wants_audio = has_audio_media and _offer_should_use_audio_stream(offer_sdp)
        self._record_media_timeline(
            "webrtc",
            "offer_received",
            details={
                "offer_owner": owner,
                "has_audio": has_audio_media,
                "wants_audio": wants_audio,
                "microphone_requested": talkback_requested,
                "duration_seconds": duration_seconds,
            },
        )
        if _owner_is_home_call(owner) and not wants_audio:
            self._record_media_timeline(
                "webrtc",
                "offer_rejected",
                details={"offer_owner": owner, "reason": "home_call_requires_audio"},
            )
            send_message(
                WebRTCError(
                    "bticino_webrtc_offer_failed",
                    "Home Call WebRTC offer must accept incoming audio",
                )
            )
            return

        if session_id in self._webrtc_sessions.active:
            await self._async_close_webrtc_session(session_id)

        stream_context = _ProviderWebRTCStreamContext(
            owner=owner,
            session_id=session_id,
            wants_audio=wants_audio,
            wants_backchannel=talkback_requested,
        )
        try:
            await self._async_handle_provider_webrtc_offer(
                offer_sdp,
                session_id,
                send_message,
                owner=owner,
                wants_audio=wants_audio,
                talkback_requested=talkback_requested,
                stream_context=stream_context,
                duration_seconds=duration_seconds,
            )
        except asyncio.CancelledError:
            self._webrtc_sessions.candidates.pop(session_id, None)
            current = getattr(self._entry, "runtime_data", None) is self._runtime_data
            # During unload, leave sessions registered for the final forced close.
            if not self._background_tasks.closing:
                if current:
                    await self._async_cleanup_failed_provider_offer(
                        session_id, owner=owner, stream_context=stream_context,
                    )
                else:
                    await self._async_close_webrtc_session(session_id, stop_media=False)
            if (
                _owner_is_home_call(owner) and current
                and (not self._background_tasks.closing
                     or session_id not in self._webrtc_sessions.active)
            ):
                # The agent may accept start before its HTTP response is cancelled.
                with suppress(Exception):
                    await self._async_stop_unowned_home_call()
            raise
        except HomeAssistantError as err:
            self._log_webrtc_debug(
                "provider_offer_unavailable",
                session_id=session_id,
                owner=owner,
                wants_audio=wants_audio,
                wants_backchannel=talkback_requested,
                media_started=stream_context.media_started,
                error_type=type(err).__name__,
                error=str(err),
            )
            self._webrtc_sessions.candidates.pop(session_id, None)
            await self._async_cleanup_failed_provider_offer(
                session_id,
                owner=owner,
                stream_context=stream_context,
            )
            if _owner_is_home_call(owner) and stream_context.media_started:
                with suppress(Exception):
                    await self._async_stop_unowned_home_call()
            send_message(WebRTCError("bticino_webrtc_unavailable", str(err)))
        except Exception as err:
            self._log_webrtc_debug(
                "provider_offer_exception",
                session_id=session_id,
                owner=owner,
                wants_audio=wants_audio,
                wants_backchannel=talkback_requested,
                media_started=stream_context.media_started,
                error_type=type(err).__name__,
                error=str(err),
            )
            self._webrtc_sessions.candidates.pop(session_id, None)
            await self._async_cleanup_failed_provider_offer(
                session_id,
                owner=owner,
                stream_context=stream_context,
            )
            if _owner_is_home_call(owner) and stream_context.media_started:
                with suppress(Exception):
                    await self._async_stop_unowned_home_call()
            send_message(WebRTCError("bticino_webrtc_offer_failed", str(err)))

    async def _async_stop_unowned_home_call(self) -> None:
        """A failed offer must not stop media shared by a surviving session."""
        async with self._rtsp_prepare_lock:
            if (
                getattr(self._entry, "runtime_data", None) is self._runtime_data
                and not self._webrtc_sessions.has_resource(
                    f"home_call:{self._entry.entry_id}"
                )
            ):
                await self._runtime_data.api.async_stop_home_call()

    async def _async_handle_provider_webrtc_offer(
        self,
        offer_sdp: str,
        session_id: str,
        send_message: WebRTCSendMessage,
        *,
        owner: str,
        wants_audio: bool,
        talkback_requested: bool,
        stream_context: _ProviderWebRTCStreamContext,
        duration_seconds: int | None = None,
    ) -> None:
        """Delegate one browser WebRTC offer to HA/go2rtc."""

        token = _PROVIDER_WEBRTC_STREAM_CONTEXT.set(stream_context)
        try:
            decision = await self._async_provider_webrtc_decision_snapshot(owner=owner)
            support_stream_url = self._provider_webrtc_support_stream_url(
                owner=owner,
                wants_audio=wants_audio,
                decision=decision,
            )
            provider = await _async_get_supported_webrtc_provider(
                self.hass,
                support_stream_url,
            )
            if provider is None:
                raise HomeAssistantError(
                    "No Home Assistant WebRTC provider is available for the C300X RTSP stream"
                )
            session = _ProviderWebRTCSession(
                provider=provider,
                owner=owner,
                send_message=send_message,
                wants_audio=wants_audio,
                wants_backchannel=talkback_requested,
                resource_id=self._provider_webrtc_resource_id(
                    owner=owner,
                    wants_audio=wants_audio,
                    decision=decision,
                ),
                ring_call=_owner_is_doorbell_media(owner) and _media_decision_is_ring_call(
                    decision
                ),
                ring_preview=_owner_is_doorbell_media(owner)
                and _media_decision_is_unanswered_ring(decision),
                pending_candidates=self._webrtc_sessions.candidates.pop(
                    session_id,
                    [],
                ),
            )
            stream_context.provider_domain = str(
                getattr(provider, "domain", type(provider).__name__)
            )
            stream_context.resource_id = session.resource_id
            stream_context.ring_call = session.ring_call
            stream_context.ring_preview = session.ring_preview
            async with self._rtsp_prepare_lock:
                self._webrtc_sessions.active[session_id] = session
                if _owner_is_home_call(owner):
                    # Keep admission and device start indivisible with respect
                    # to the final close of a previous Home Call session.
                    stream_context.media_started = True
                    await self._runtime_data.api.async_start_home_call(
                        duration_seconds=duration_seconds
                    )
            await self._async_log_go2rtc_debug(
                provider,
                "provider_go2rtc_before_offer",
                session_id=session_id,
                owner=owner,
                wants_audio=wants_audio,
                wants_backchannel=talkback_requested,
                ring_call=session.ring_call,
                ring_preview=session.ring_preview,
                resource_id=session.resource_id,
                support_rtsp_path=self._debug_rtsp_path(support_stream_url),
            )
            _LOGGER.debug(
                "C300X WebRTC provider session prepared: session=%s owner=%s "
                "audio=%s talkback=%s ring_call=%s ring_preview=%s provider=%s",
                _short_session_id(session_id),
                owner,
                wants_audio,
                talkback_requested,
                session.ring_call,
                session.ring_preview,
                getattr(provider, "domain", type(provider).__name__),
            )
            self._record_media_timeline(
                "webrtc",
                "session_prepared",
                details={
                    "session_owner": owner,
                    "wants_audio": wants_audio,
                    "microphone_requested": talkback_requested,
                    "ring_call": session.ring_call,
                    "ring_preview": session.ring_preview,
                    "provider": str(getattr(provider, "domain", type(provider).__name__)),
                },
            )
            provider_offer_failed = False

            def _send_provider_message(message: Any) -> None:
                nonlocal provider_offer_failed
                if (
                    not self._webrtc_sessions.accepts_provider_messages(session_id, session)
                    or media_owner_stopping(self._runtime_data.resources, owner)
                ):
                    return
                if _webrtc_message_is_error(message):
                    provider_offer_failed = True
                    self._log_webrtc_debug(
                        "provider_message_error",
                        session_id=session_id,
                        owner=owner,
                        provider=stream_context.provider_domain,
                        wants_audio=wants_audio,
                        wants_backchannel=talkback_requested,
                        ring_call=session.ring_call,
                        ring_preview=session.ring_preview,
                        resource_id=session.resource_id,
                        error_code=self._webrtc_message_field(message, "code"),
                        error_message=self._webrtc_message_field(message, "message"),
                        media_started=stream_context.media_started,
                    )
                else:
                    message = filter_webrtc_message_for_entry(
                        message, self._entry, logger=_LOGGER, direction="outbound"
                    )
                    if message is None:
                        return
                send_message(message)

            await provider.async_handle_async_webrtc_offer(
                self,
                offer_sdp,
                session_id,
                _send_provider_message,
            )
            await self._async_log_go2rtc_debug(
                provider,
                "provider_go2rtc_after_offer",
                session_id=session_id,
                owner=owner,
                wants_audio=wants_audio,
                wants_backchannel=talkback_requested,
                ring_call=session.ring_call,
                ring_preview=session.ring_preview,
                resource_id=session.resource_id,
                media_started=stream_context.media_started,
            )
            current_session = self._webrtc_sessions.active.get(session_id)
            if current_session is session:
                if provider_offer_failed:
                    self._record_media_timeline(
                        "webrtc",
                        "provider_offer_failed",
                        details={
                            "session_owner": owner,
                            "wants_audio": wants_audio,
                            "microphone_requested": talkback_requested,
                            "ring_call": session.ring_call,
                            "ring_preview": session.ring_preview,
                        },
                    )
                    await self._async_close_webrtc_session(
                        session_id,
                        stop_media=(
                            stream_context.media_started or _owner_is_home_call(owner)
                        ),
                        notify_client=False,
                    )
                    return
                session.ready = True
                self._log_webrtc_debug(
                    "provider_session_ready",
                    session_id=session_id,
                    owner=owner,
                    provider=stream_context.provider_domain,
                    wants_audio=wants_audio,
                    wants_backchannel=talkback_requested,
                    ring_call=session.ring_call,
                    ring_preview=session.ring_preview,
                    resource_id=session.resource_id,
                    media_started=stream_context.media_started,
                )
                self._record_media_timeline(
                    "webrtc",
                    "session_ready",
                    details={
                        "session_owner": owner,
                        "wants_audio": wants_audio,
                        "microphone_requested": talkback_requested,
                        "ring_call": session.ring_call,
                        "ring_preview": session.ring_preview,
                    },
                )
                await self._webrtc_sessions.flush_candidates(session_id)
        finally:
            _PROVIDER_WEBRTC_STREAM_CONTEXT.reset(token)

    async def _async_provider_webrtc_decision_snapshot(
        self,
        *,
        owner: str,
    ) -> MediaStateOutput:
        """Return a fresh media decision without starting native RTSP media."""

        if _owner_is_home_call(owner):
            return self._last_media_decision
        status = await self._async_refresh_video_status_or_none(apply_status=False)
        if status is None:
            return self._last_media_decision
        return self._derive_media_decision(status)

    def _provider_webrtc_support_stream_url(
        self,
        *,
        owner: str,
        wants_audio: bool,
        decision: MediaStateOutput,
    ) -> str:
        """Build a provider-support URL without activating native media."""

        if _owner_is_home_call(owner) or wants_audio:
            return self._build_stream_url(audio=True)
        return self._build_stream_url(
            audio=not _media_decision_is_unanswered_ring(decision)
        )

    def _provider_webrtc_resource_id(
        self,
        *,
        owner: str,
        wants_audio: bool,
        decision: MediaStateOutput,
    ) -> str:
        """Return a stable local-media resource key for provider sessions."""

        if _owner_is_home_call(owner):
            return f"home_call:{self._entry.entry_id}"
        if _media_decision_is_ring_call(decision) or _media_decision_is_unanswered_ring(
            decision
        ):
            return f"ring:{self._entry.entry_id}"
        suffix = "audio" if wants_audio else "video"
        return f"doorbell:{self._entry.entry_id}:{suffix}"

    async def _async_cleanup_failed_provider_offer(
        self,
        session_id: str,
        *,
        owner: str,
        stream_context: _ProviderWebRTCStreamContext,
    ) -> None:
        """Close a failed provider offer without stopping unrelated media."""

        had_provider_session = session_id in self._webrtc_sessions.active
        self._log_webrtc_debug(
            "provider_offer_cleanup",
            session_id=session_id,
            owner=owner,
            wants_audio=stream_context.wants_audio,
            wants_backchannel=stream_context.wants_backchannel,
            media_started=stream_context.media_started,
            had_provider_session=had_provider_session,
            provider=stream_context.provider_domain,
            resource_id=stream_context.resource_id,
        )
        await self._async_close_webrtc_session(
            session_id,
            stop_media=_owner_is_doorbell_media(owner) and stream_context.media_started,
            notify_client=False,
        )
        if (
            not had_provider_session
            and self._provider_offer_failure_should_stop_doorbell_media(
                owner,
                stream_context,
            )
        ):
            with suppress(Exception):
                await self._runtime_data.api.async_stop_doorbell_video()

    def _provider_offer_failure_should_stop_doorbell_media(
        self,
        owner: str,
        stream_context: _ProviderWebRTCStreamContext,
    ) -> bool:
        """Return true when a failed offer owns a started on-demand media path."""

        if _owner_is_home_call(owner) or not stream_context.media_started:
            return False
        decision = self._last_media_decision
        return not (
            stream_context.ring_call
            or stream_context.ring_preview
            or _media_decision_is_ring_call(decision)
            or _media_decision_is_unanswered_ring(decision)
        )

    async def async_on_webrtc_candidate(self, session_id: str, candidate: Any) -> None:
        """Forward browser ICE candidates to the active WebRTC provider session."""
        await self._webrtc_sessions.on_candidate(session_id, candidate)

    @callback
    def close_webrtc_session(self, session_id: str) -> None:
        """Close an active WebRTC provider session."""

        # A closing subscription (tab closed, network drop, HA unsubscribe) is
        # the only stop signal a Home Call gets: unlike on-demand doorbell RTSP
        # it is not torn down by an RTSP disconnect, so the device call would
        # otherwise linger until its duration timeout. Stop the device media for
        # Home Call here; doorbell sessions keep stop_media=False and rely on the
        # RTSP drain backstop.
        session = self._webrtc_sessions.active.get(session_id)
        stop_media = session is not None and session.requires_explicit_stop
        offer = self._webrtc_sessions.cancel_offer(session_id)
        self._background_tasks.create(self.hass,
            self._webrtc_sessions.close_after_offer(
                offer, lambda: self._async_close_webrtc_session(
                    session_id, stop_media=stop_media, reason="webrtc_session_closed",
                ),
            ),
            key=f"close:{session_id}",
        )

    async def async_will_remove_from_hass(self) -> None:
        """Stop active media sessions when HA removes the camera entity."""

        await self._background_tasks.close()
        self._webrtc_sessions.candidates.clear()
        self._runtime_data.resources.prepare_doorbell_video_stop = None
        self._runtime_data.resources.prepare_home_call_stop = None
        current = getattr(self._entry, "runtime_data", None) is self._runtime_data
        for session_id in self._webrtc_session_ids():
            await self._async_close_webrtc_session(session_id, stop_media=current, force_stop_media=current)
        if current:
            with suppress(Exception):
                await self._runtime_data.api.async_stop_doorbell_video()

    async def async_prepare_doorbell_video_stop(self) -> None:
        """Close HA-owned doorbell media before an explicit agent stop."""
        await self._webrtc_sessions.stop_owner(
            self._runtime_data.resources, "doorbell", "doorbell_video_stopped",
            self._async_close_webrtc_session,
            drain=self._async_wait_for_provider_rtsp_clients_to_drain,
        )

    async def async_prepare_home_call_stop(self) -> None:
        """Close HA-owned Home Call media before an explicit agent stop."""
        await self._webrtc_sessions.stop_owner(
            self._runtime_data.resources, "home_call", "home_call_stopped",
            self._async_close_webrtc_session,
            drain=self._async_wait_for_provider_rtsp_clients_to_drain,
        )

    async def _async_wait_for_provider_rtsp_clients_to_drain(self) -> None:
        """Wait until the provider has dropped native RTSP clients after close."""

        deadline = asyncio.get_running_loop().time() + (
            WEBRTC_PROVIDER_CLOSE_DRAIN_TIMEOUT_SECONDS
        )
        last_logged_clients: int | None = None
        while True:
            status = await self._async_refresh_video_status_or_none(apply_status=False)
            clients = _rtsp_client_count_from_status(status)
            if clients != last_logged_clients:
                self._log_webrtc_debug(
                    "provider_rtsp_drain",
                    status=status,
                    clients=clients,
                )
                last_logged_clients = clients
            if clients is None or clients <= 0:
                return
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                self._log_webrtc_debug(
                    "provider_rtsp_drain_timeout",
                    status=status,
                    clients=clients,
                )
                return
            await asyncio.sleep(
                min(WEBRTC_PROVIDER_CLOSE_DRAIN_INTERVAL_SECONDS, remaining)
            )

    async def _async_close_webrtc_session(
        self,
        session_id: str,
        *,
        stop_media: bool = True,
        force_stop_media: bool = False,
        notify_client: bool = False,
        reason: str = "closed",
    ) -> None:
        session = self._webrtc_sessions.active.get(session_id)
        try:
            await self._async_close_webrtc_session_impl(
                session_id, stop_media=stop_media, force_stop_media=force_stop_media,
                notify_client=notify_client, reason=reason,
            )
        except asyncio.CancelledError:
            # Unload must be able to finish a close interrupted after its pop.
            if session is not None:
                self._webrtc_sessions.active.setdefault(session_id, session)
            raise

    async def _async_close_webrtc_session_impl(
        self,
        session_id: str,
        *,
        stop_media: bool = True,
        force_stop_media: bool = False,
        notify_client: bool = False,
        reason: str = "closed",
    ) -> None:
        provider_session = self._webrtc_sessions.active.pop(session_id, None)
        if provider_session is not None:
            self._log_webrtc_debug(
                "provider_session_closing",
                session_id=session_id,
                owner=provider_session.owner,
                provider=getattr(
                    provider_session.provider,
                    "domain",
                    type(provider_session.provider).__name__,
                ),
                wants_audio=provider_session.wants_audio,
                wants_backchannel=provider_session.wants_backchannel,
                ring_call=provider_session.ring_call,
                ring_preview=provider_session.ring_preview,
                ready=provider_session.ready,
                resource_id=provider_session.resource_id,
                stop_media=stop_media,
                force_stop_media=force_stop_media,
                notify_client=notify_client,
                reason=reason,
            )
            self._record_media_timeline(
                "webrtc",
                "session_closed",
                details={
                    "session_owner": provider_session.owner,
                    "ready": provider_session.ready,
                    "stop_media": stop_media,
                    "force_stop_media": force_stop_media,
                    "notify_client": notify_client,
                    "reason": reason,
                    "ring_call": provider_session.ring_call,
                    "ring_preview": provider_session.ring_preview,
                    "wants_audio": provider_session.wants_audio,
                    "wants_backchannel": provider_session.wants_backchannel,
                },
            )
            self._webrtc_sessions.candidates.pop(session_id, None)
            if notify_client:
                with suppress(Exception):
                    provider_session.send_message(
                        {"type": "closed", "reason": reason}
                    )
            await self._async_log_go2rtc_debug(
                provider_session.provider,
                "provider_go2rtc_before_close",
                session_id=session_id,
                owner=provider_session.owner,
                wants_audio=provider_session.wants_audio,
                wants_backchannel=provider_session.wants_backchannel,
                ring_call=provider_session.ring_call,
                ring_preview=provider_session.ring_preview,
                ready=provider_session.ready,
                resource_id=provider_session.resource_id,
                stop_media=stop_media,
                reason=reason,
            )
            provider_close_path = await async_close_provider_session(
                provider_session.provider,
                session_id,
                self._log_webrtc_debug,
            )
            await self._async_log_go2rtc_debug(
                provider_session.provider,
                "provider_go2rtc_after_close",
                session_id=session_id,
                owner=provider_session.owner,
                wants_audio=provider_session.wants_audio,
                wants_backchannel=provider_session.wants_backchannel,
                ring_call=provider_session.ring_call,
                ring_preview=provider_session.ring_preview,
                ready=provider_session.ready,
                resource_id=provider_session.resource_id,
                stop_media=stop_media,
                reason=reason,
                provider_close_path=provider_close_path,
            )
            last_resource_session = not self._webrtc_sessions.has_resource(
                provider_session.resource_id
            )
            if provider_session.ring_preview:
                with suppress(Exception):
                    provider_session.ring_preview = _media_decision_is_unanswered_ring(
                        self._derive_media_decision(
                            await self._async_refresh_video_status(apply_status=False)
                        )
                    )
            should_stop_media = (
                last_resource_session
                and stop_media
                and (
                    force_stop_media
                    or (
                        not provider_session.ring_preview
                        and not provider_session.ring_call
                    )
                )
            )
            if should_stop_media:
                self._log_webrtc_debug(
                    "provider_session_stop_media",
                    session_id=session_id,
                    owner=provider_session.owner,
                    wants_audio=provider_session.wants_audio,
                    wants_backchannel=provider_session.wants_backchannel,
                    ring_call=provider_session.ring_call,
                    ring_preview=provider_session.ring_preview,
                    resource_id=provider_session.resource_id,
                    reason=reason,
                )
                # Serialize against CameraRtspOrchestrator's activation methods
                # (which take the same lock) so a concurrent new offer cannot
                # activate media while this stop is still tearing it down.
                async with self._rtsp_prepare_lock:
                    if self._webrtc_sessions.has_resource(provider_session.resource_id):
                        return
                    await self._async_wait_for_provider_rtsp_clients_to_drain()
                    await self._async_log_video_status_debug(
                        "provider_agent_stop_before_request",
                        session_id=session_id,
                        owner=provider_session.owner,
                        wants_audio=provider_session.wants_audio,
                        wants_backchannel=provider_session.wants_backchannel,
                        ring_call=provider_session.ring_call,
                        ring_preview=provider_session.ring_preview,
                        resource_id=provider_session.resource_id,
                        reason=reason,
                    )
                    if self._webrtc_sessions.has_resource(provider_session.resource_id):
                        return
                    if provider_session.is_home_call:
                        with suppress(Exception):
                            await self._runtime_data.api.async_stop_home_call()
                    elif provider_session.ring_call:
                        with suppress(Exception):
                            await self._runtime_data.api.async_hangup_doorbell_call()
                        with suppress(Exception):
                            await self._runtime_data.api.async_stop_doorbell_video()
                    else:
                        with suppress(Exception):
                            await self._runtime_data.api.async_stop_doorbell_video()
                    await self._async_log_video_status_debug(
                        "provider_agent_stop_after_request",
                        session_id=session_id,
                        owner=provider_session.owner,
                        wants_audio=provider_session.wants_audio,
                        wants_backchannel=provider_session.wants_backchannel,
                        ring_call=provider_session.ring_call,
                        ring_preview=provider_session.ring_preview,
                        resource_id=provider_session.resource_id,
                        reason=reason,
                    )
            return

        self._webrtc_sessions.candidates.pop(session_id, None)

    async def _async_prepare_rtsp_stream(self, *, audio: bool = False) -> str:
        """Activate video and return a URL only after RTSP answers."""

        await self._async_close_finished_home_call_sessions()
        return await self._rtsp_orchestrator.async_prepare_rtsp_stream(audio=audio)

    async def _async_close_finished_home_call_sessions(self) -> None:
        """Close stale local Home Call sessions before starting doorbell media."""

        # Keep both the status read and its cleanup indivisible with admission
        # and native start; an idle reply from before startup must not win later.
        async with self._rtsp_prepare_lock:
            session_ids = self._webrtc_sessions.active_ids("home_call")
            if not session_ids and not self._cached_home_call_state_needs_refresh():
                return

            try:
                status = await self._runtime_data.api.async_home_call_status()
            except Exception:  # noqa: BLE001 - preserve sessions on status errors
                return
            if _home_call_status_has_media(status):
                self._apply_home_call_status(status)
                return

            self._apply_home_call_ended(dict(status))
            for session_id in session_ids:
                await self._async_close_webrtc_session(
                    session_id,
                    stop_media=False,
                    notify_client=True,
                    reason="home_call_ended",
                )

    def _cached_home_call_state_needs_refresh(self) -> bool:
        """Return true when cached media facts still look like Home Call."""

        return (
            self._video_owner == "home_call"
            or self._bridge_status.get("media_owner") == "home_call"
            or bool(self._bridge_status.get("home_call_running"))
            or bool(self._bridge_status.get("home_call_active"))
            or bool(self._bridge_status.get("home_call_answered"))
        )

    async def _async_prepare_home_call_rtsp_stream(self) -> str:
        """Return the audio-only RTSP source for an active Home Call."""

        return await self._rtsp_orchestrator.async_prepare_home_call_rtsp_stream()

    def _apply_home_call_status(self, status: Mapping[str, Any]) -> None:
        """Mirror Home Call media into the audio bridge attributes."""

        self._bridge_available = bool(status.get("available", True))
        self._video_owner = "home_call"
        self._bridge_status = {
            **self._bridge_status,
            "media_owner": "home_call",
            "home_call_running": bool(status.get("running")),
            "home_call_active": bool(status.get("active")),
            "home_call_answered": bool(status.get("answered")),
            "home_call_rtp_proxy": bool(status.get("rtp_proxy")),
            "home_call_target_audio_port": status.get("target_audio_port"),
            "home_call_rtp_packets": status.get("rtp_packets", 0),
            "home_call_rtcp_packets": status.get("rtcp_packets", 0),
            "audio_codec": TALKBACK_CODEC,
            "talkback_supported": True,
            "talkback_codec": TALKBACK_CODEC,
            "talkback_payload_type": TALKBACK_RTP_PAYLOAD_TYPE,
        }
        self._audio_stream_path = "/doorbell"
        self._refresh_derived_media_state()

    async def _async_refresh_video_status(
        self,
        *,
        apply_status: bool = True,
    ) -> dict[str, Any]:
        status = cast(
            dict[str, Any],
            await self._runtime_data.api.async_doorbell_video_status(),
        )
        if apply_status:
            self._apply_status(status)
        return status

    async def _async_refresh_video_status_or_none(
        self,
        *,
        apply_status: bool = True,
    ) -> dict[str, Any] | None:
        with suppress(Exception):
            return await self._async_refresh_video_status(apply_status=apply_status)
        return None

    def _rtsp_event_revision(self) -> int:
        """Return the current RTSP-relevant agent-event revision."""

        return self._rtsp_state_event_revision

    async def _async_wait_for_rtsp_event(
        self,
        *,
        revision: int,
        wait_seconds: float,
    ) -> None:
        """Wait for an RTSP-relevant agent event or a bounded fallback timeout."""

        if wait_seconds <= 0 or self._rtsp_state_event_revision != revision:
            return
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()
        self._rtsp_state_event_waiters.add(future)
        try:
            if self._rtsp_state_event_revision != revision:
                return
            with suppress(TimeoutError):
                await asyncio.wait_for(future, timeout=wait_seconds)
        finally:
            self._rtsp_state_event_waiters.discard(future)

    def _wake_rtsp_event_waiters(self) -> None:
        """Wake RTSP readiness waiters after authoritative native media events."""

        self._rtsp_state_event_revision += 1
        waiters = tuple(self._rtsp_state_event_waiters)
        self._rtsp_state_event_waiters.clear()
        for waiter in waiters:
            if not waiter.done():
                waiter.set_result(None)


    def _webrtc_session_ids(self) -> list[str]:
        """Return all HA-side WebRTC provider session IDs."""

        return self._webrtc_sessions.active_ids()

    def _ring_preview_webrtc_session_ids(self) -> list[str]:
        """Return passive Ring preview session ids."""

        return [
            session_id
            for session_id, session in self._webrtc_sessions.active.items()
            if session.owner == "doorbell" and session.ring_preview
        ]

    def _talkback_supported(self) -> bool:
        """Return true when the bridge can accept WebRTC microphone audio."""

        if "talkback_supported" in self._bridge_status:
            return bool(self._bridge_status["talkback_supported"])
        return bool(
            self._audio_stream_path
            or self._bridge_status.get("audio_stream_path")
            or self._bridge_status.get("audio_codec") == TALKBACK_CODEC
        )

    def _agent_host(self) -> str:
        """Return the configured agent host without surrounding whitespace."""

        return str(entry_config_value(self._entry, CONF_AGENT_HOST, "")).strip()

    def _agent_host_for_socket(self) -> str:
        """Return the agent host in a form accepted by socket APIs."""

        return _agent_host_for_socket(self._agent_host())

    def _agent_host_for_url(self) -> str:
        """Return the agent host in a form accepted in RTSP URLs."""

        return _agent_host_for_url(self._agent_host())

    def _build_stream_url(self, *, audio: bool = False) -> str:
        if audio:
            path = self._audio_stream_path or self._bridge_status.get("audio_stream_path")
            path = str(path or "/doorbell")
        else:
            path = (
                self._video_stream_path
                or entry_config_value(
                    self._entry,
                    CONF_VIDEO_STREAM_PATH,
                    DEFAULT_VIDEO_STREAM_PATH,
                )
            )
            path = str(path or DEFAULT_VIDEO_STREAM_PATH)
        port = int(entry_config_value(self._entry, CONF_VIDEO_PORT, DEFAULT_VIDEO_PORT))
        return _build_rtsp_url(
            host=self._agent_host(),
            port=port,
            path=path,
            default_path=DEFAULT_VIDEO_STREAM_PATH,
            allow_absolute_url=True,
        )

    def _apply_status(self, status: Mapping[str, Any]) -> None:
        self._bridge_available = bool(status.get("available"))
        self._bridge_status = optional_mapping(status.get("bridge"))
        self._video_window_available = bool(status.get("window_available"))
        self._attr_is_streaming = self._video_window_available
        self._video_owner = str(status.get("media_owner") or "unknown")
        self._external_media_active = bool(status.get("external_media_active"))
        self._external_owner = optional_string(status.get("external_owner"))
        self._last_video_block_reason = optional_string(status.get("last_block_reason"))
        if status.get("stream_path"):
            self._video_stream_path = str(status["stream_path"])
        self._audio_stream_path = optional_string(status.get("audio_stream_path"))
        self._recorder_stream_path = optional_string(status.get("recorder_stream_path"))
        if CameraEntityCapabilities is not None:
            self._attr_camera_entity_capabilities = CameraEntityCapabilities(
                two_way_audio=(
                    entry_config_value(self._entry, CONF_NATIVE_TWO_WAY_AUDIO, False) is True
                    and self._bridge_status.get("talkback_supported") is True
                    and bool(self._audio_stream_path)
                )
            )
        self._refresh_derived_media_state()

    async def async_added_to_hass(self) -> None:
        """Subscribe to runtime event-state updates."""

        await super().async_added_to_hass()
        self._runtime_data.resources.prepare_doorbell_video_stop = (
            self.async_prepare_doorbell_video_stop
        )
        self._runtime_data.resources.prepare_home_call_stop = (
            self.async_prepare_home_call_stop
        )
        self.async_on_remove(
            self.hass.bus.async_listen(
                EVENT_AGENT_EVENT_RECEIVED,
                self._handle_agent_event,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_SYSTEM_METRICS_CHANGED,
                self._handle_system_metrics_changed,
            )
        )
        await self.async_update()
        self._async_write_ha_state_if_ready()

    @callback
    def _handle_system_metrics_changed(self, entry_id: str) -> None:
        """React to the periodic agent metrics heartbeat: run the CPU watchdog
        and self-heal a stale busy latch (the camera has no poll of its own)."""

        if self._background_tasks.closing:
            return
        handle_agent_cpu_metrics_changed(self, entry_id)
        if (
            entry_id == self._entry.entry_id
            and self._webrtc_sessions.active
            and not self._reconcile_in_flight
        ):
            self._reconcile_in_flight = True
            self._background_tasks.create(self.hass, self._async_reconcile_local_sessions(), key="reconcile")

    async def _async_reconcile_local_sessions(self) -> None:
        """Close stale ready doorbell/on-demand sessions an idle agent orphaned
        (no media-stop) so they stop latching and churning the heartbeat. Home
        Call is reconciled via its own status path; not-ready sessions are left."""

        self._reconcile_in_flight = True
        try:
            # Provider work continues after stream_source releases this lock.
            # Judge only sessions which had finished opening before this status
            # request, never an offer which becomes ready while it is in flight.
            async with self._rtsp_prepare_lock:
                sessions = [
                    (sid, session)
                    for sid, session in self._webrtc_sessions.active.items()
                    if session.ready
                    and sid not in self._webrtc_sessions.offers
                    and _owner_is_doorbell_media(session.owner)
                ]
                status = await self._async_refresh_video_status_or_none()
                if status is not None and status_reports_agent_idle(
                    status,
                    cached_video_owner=self._video_owner,
                    cached_video_window_available=self._video_window_available,
                    cached_external_media_active=self._external_media_active,
                ):
                    for session_id, session in sessions:
                        if self._webrtc_sessions.active.get(session_id) is not session:
                            continue
                        await self._async_close_webrtc_session(
                            session_id,
                            stop_media=False,
                            notify_client=True,
                            reason="agent_idle_reconcile",
                        )
            # Home Call is a separate status path: reconcile any held home-call
            # session against async_home_call_status() so a missed end event does
            # not leave it churning the heartbeat forever.
            if self._webrtc_sessions.active_ids("home_call"):
                await self._async_close_finished_home_call_sessions()
            self._async_write_ha_state_if_ready()
        finally:
            self._reconcile_in_flight = False

    @callback
    def _handle_agent_event(self, event: Any) -> None:
        if self._background_tasks.closing or event.data.get("entry_id") != self._entry.entry_id:
            return
        event_type = agent_event_key(event.data)
        if event_type in HOME_CALL_EVENTS:
            self._handle_home_call_event(event_type, event.data)
            self._record_media_timeline(
                "agent_event",
                event_type,
                details=_webrtc_debug.agent_event_timeline_details(event.data),
            )
            self._wake_rtsp_event_waiters()
            self._async_write_ha_state_if_ready()
            return
        if event_type not in VIDEO_WINDOW_EVENTS | VIDEO_WINDOW_CLOSED_EVENTS:
            return
        if event_type in VIDEO_WINDOW_CLOSED_EVENTS:
            self._clear_video_window()
            self._close_webrtc_sessions_from_event("doorbell", "doorbell_media_closed")
            self._record_media_timeline(
                "agent_event",
                event_type,
                details=_webrtc_debug.agent_event_timeline_details(event.data),
            )
            self._wake_rtsp_event_waiters()
            self._async_write_ha_state_if_ready()
            return
        self._video_window_available = bool(
            event.data.get("video_window_available", False)
        )
        self._attr_is_streaming = self._video_window_available
        self._bridge_available = bool(event.data.get("video_available", False))
        self._video_stream_path = event.data.get("stream_path")
        self._audio_stream_path = optional_string(event.data.get("audio_stream_path"))
        self._recorder_stream_path = optional_string(
            event.data.get("recorder_stream_path")
        )
        self._apply_event_media_facts(event.data)
        self._refresh_derived_media_state()
        self._record_media_timeline(
            "agent_event",
            event_type,
            details=_webrtc_debug.agent_event_timeline_details(event.data),
        )
        self._wake_rtsp_event_waiters()
        self._async_write_ha_state_if_ready()

    def _handle_home_call_event(self, event_type: str, data: dict[str, Any]) -> None:
        payload = _home_call_payload(data)
        if event_type == "home_call_ended":
            self._apply_home_call_ended(payload)
            self._close_webrtc_sessions_from_event("home_call", "home_call_ended")
            return
        if event_type == "home_call_answered":
            self._apply_home_call_status(
                {
                    **payload,
                    "running": payload.get("running", True),
                    "active": payload.get("active", True),
                    "answered": payload.get("answered", True),
                }
            )
            return
        self._apply_home_call_status(
            {
                **payload,
                "running": payload.get("running", True),
                "active": payload.get("active", True),
                "answered": payload.get("answered", False),
            }
        )

    def _close_webrtc_sessions_from_event(self, owner: str, reason: str) -> None:
        """Close local sessions after an authoritative agent media-end event."""

        session_ids = self._webrtc_sessions.ids_by_owner(owner)
        if not session_ids or getattr(self, "hass", None) is None:
            return
        for session_id in session_ids:
            self._webrtc_sessions.cancel_offer(session_id, reason=reason)

        async def _close_sessions() -> None:
            await self._webrtc_sessions.stop_owner(
                self._runtime_data.resources, owner, reason,
                self._async_close_webrtc_session, session_ids=session_ids,
            )
            self._refresh_derived_media_state()
            self._async_write_ha_state_if_ready()

        self._background_tasks.create(self.hass, _close_sessions())

    def _apply_home_call_ended(self, status: dict[str, Any]) -> None:
        self._mark_home_call_sessions_inactive()
        was_home_call = (
            self._video_owner == "home_call"
            or self._bridge_status.get("media_owner") == "home_call"
        )
        self._bridge_available = bool(status.get("available", True))
        self._bridge_status = {
            **self._bridge_status,
            "home_call_running": False,
            "home_call_active": False,
            "home_call_answered": False,
            "home_call_stopping": False,
            "home_call_rtp_proxy": False,
            "home_call_target_audio_port": 0,
            "home_call_rtp_packets": status.get("rtp_packets", 0),
            "home_call_rtcp_packets": status.get("rtcp_packets", 0),
        }
        if was_home_call:
            self._bridge_status["media_owner"] = "idle"
            self._bridge_status["media_active"] = False
            self._bridge_status["media_starting"] = False
            self._bridge_status["stop_in_progress"] = False
            self._bridge_status["call_active"] = False
            self._bridge_status["clients"] = 0
            self._video_owner = "idle"
            self._video_window_available = False
            self._attr_is_streaming = False
            self._video_stream_path = None
            self._audio_stream_path = None
            self._recorder_stream_path = None
        self._refresh_derived_media_state()

    def _mark_home_call_sessions_inactive(self) -> None:
        for session in self._webrtc_sessions.active.values():
            if session.is_home_call:
                session.ready = False

    def _clear_video_window(self) -> None:
        self._video_window_available = False
        self._attr_is_streaming = False
        self._video_stream_path = None
        self._audio_stream_path = None
        self._recorder_stream_path = None
        self._bridge_available = False
        self._video_owner = "idle"
        self._external_media_active = False
        self._external_owner = None
        self._last_video_block_reason = None
        self._bridge_status = {
            **self._bridge_status,
            "media_owner": "idle",
            "media_active": False,
            # Transient start/stop flags belong to the window that just closed,
            # like the home-call path already clears them. Leaving them behind
            # in this cumulative view republishes them as live state.
            "media_starting": False,
            "stop_in_progress": False,
            "external_media_active": False,
            "ring_call_active": False,
            "ring_media_active": False,
            "ring_audio_active": False,
            "ring_answer_requested": False,
            "ring_answered": False,
            "ring_hangup_requested": False,
            "unanswered_ring_call": False,
            "call_active": False,
            "clients": 0,
        }
        self._refresh_derived_media_state()

    def _async_write_ha_state_if_ready(self) -> None:
        if self._background_tasks.closing or not hasattr(self, "async_write_ha_state"):
            return
        snapshot = _camera_state_snapshot(self)
        if snapshot == self._last_state_snapshot:
            return
        self._last_state_snapshot = snapshot
        self.async_write_ha_state()

    def _record_media_timeline(
        self,
        kind: str,
        event: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        """Record a safe media transition using already-known runtime state."""

        runtime = self._runtime_data
        timeline = getattr(runtime, "media_timeline", None)
        record = getattr(timeline, "record", None)
        if not callable(record):
            return
        ready_sessions = sum(
            1 for session in self._webrtc_sessions.active.values() if session.ready
        )
        record(
            kind=kind,
            event=event,
            media_state=self._last_media_state.value,
            owner=self._video_owner,
            session_count=len(self._webrtc_sessions.active),
            ring_preview_sessions=len(self._ring_preview_webrtc_session_ids()),
            ready_sessions=ready_sessions,
            details=details,
        )

    def _refresh_derived_media_state(self) -> None:
        self._last_media_decision = self._derive_media_decision()
        self._last_media_state = self._last_media_decision.state
        if self._background_tasks.closing:
            return
        publish_agent_media_facts(
            getattr(self, "hass", None), self._entry, self._bridge_status
        )

    def _derive_media_decision(
        self,
        status: dict[str, Any] | None = None,
    ) -> MediaStateOutput:
        facts = self._media_state_input_from_status(status)
        return derive_media_state(facts)

    def _media_state_input_from_status(
        self,
        status: dict[str, Any] | None = None,
    ) -> MediaStateInput:
        source_status = status if status is not None else {"bridge": self._bridge_status}
        return media_state_input_from_video_status(
            source_status,
            cached_video_owner=self._video_owner,
            cached_video_window_available=self._video_window_available,
            cached_external_media_active=self._external_media_active,
            cached_external_owner=self._external_owner,
            local_sessions=self._active_local_media_sessions(source_status),
            last_error=(
                None if self._rtsp_cooldown_scope == "home_call" else self._last_rtsp_error
            ),
            cooldown_active=(
                self._rtsp_unavailable_until > time.monotonic()
                and self._rtsp_cooldown_scope != "home_call"
            ),
            capability_doorbell_video=_capability_supported_if_known(
                self._entry,
                "doorbell_video",
            ),
            capability_doorbell_call=_capability_supported_if_known(
                self._entry,
                "doorbell_call",
            ),
            capability_home_call=_capability_supported_if_known(
                self._entry,
                "home_call",
            ),
        )

    def _apply_event_media_facts(self, data: Mapping[str, Any]) -> None:
        bridge = optional_mapping(data.get("bridge"))
        if bridge:
            self._bridge_status = {**self._bridge_status, **bridge}
        for data_key, attr_name in (
            ("media_owner", "_video_owner"),
            ("video_owner", "_video_owner"),
        ):
            value = optional_string(data.get(data_key))
            if value is not None:
                setattr(self, attr_name, value)
        if "external_media_active" in data:
            self._external_media_active = bool(data["external_media_active"])
        if "external_owner" in data:
            self._external_owner = optional_string(data.get("external_owner"))
        if "last_block_reason" in data:
            self._last_video_block_reason = optional_string(
                data.get("last_block_reason")
            )

    def _active_local_media_sessions(
        self, status: Mapping[str, Any] | None = None
    ) -> int:
        # Agent is source of truth: when it reports idle, a still-tracked ready
        # session is stale -- discount it so it cannot latch media_state busy.
        if status_reports_agent_idle(
            status if status is not None else {"bridge": self._bridge_status},
            cached_video_owner=self._video_owner,
            cached_video_window_available=self._video_window_available,
            cached_external_media_active=self._external_media_active,
        ):
            return 0
        provider_resources = {
            session.resource_id
            for session in self._webrtc_sessions.active.values()
            if session.ready
        }
        return len(provider_resources)


@callback
def async_register_home_call_ws(hass: HomeAssistant) -> None:
    """Register Home Call audio WebRTC websocket commands."""

    _async_register_home_call_ws(hass, C300XDoorbellCamera)
