"""Camera entity for the C300X doorbell WebRTC stream."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Mapping, MutableMapping
from contextlib import suppress
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, cast

from homeassistant.components.camera import (
    Camera,
    CameraEntityFeature,
)
from homeassistant.components.stream import (
    CONF_RTSP_TRANSPORT,
    CONF_USE_WALLCLOCK_AS_TIMESTAMPS,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from propcache.api import cached_property

from .camera_media import webrtc_debug as _webrtc_debug
from .camera_media.home_call_ws import (
    async_register_home_call_ws as _async_register_home_call_ws,
)
from .camera_media.rtsp_orchestrator import (
    CameraRtspOrchestrator,
    CameraRtspOrchestratorSettings,
)
from .camera_media.rtsp_orchestrator import (
    rtsp_consumer_for_doorbell_request as _rtsp_consumer_for_doorbell_request,
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
from .camera_media.state_machine import (
    MediaState,
    MediaStateInput,
    MediaStateOutput,
    derive_media_state,
    media_state_input_from_video_status,
)
from .camera_media.webrtc_debug import WebRTCDebugMixin
from .camera_media.webrtc_session import (
    ProviderWebRTCSession as _ProviderWebRTCSession,
)
from .camera_media.webrtc_session import (
    ProviderWebRTCStreamContext as _ProviderWebRTCStreamContext,
)
from .camera_media.webrtc_session import (
    short_session_id as _short_session_id,
)
from .camera_media.webrtc_session import (
    webrtc_message_is_error as _webrtc_message_is_error,
)
from .const import (
    CONF_AGENT_HOST,
    CONF_VIDEO_PORT,
    CONF_VIDEO_STREAM_PATH,
    DEFAULT_VIDEO_PORT,
    DEFAULT_VIDEO_STREAM_PATH,
    EVENT_AGENT_EVENT_RECEIVED,
    SIGNAL_SYSTEM_METRICS_CHANGED,
)
from .device_user import media_user_attribute
from .entity import C300XEntity, entry_config_value, supports_capability
from .entry_types import BticinoC300XConfigEntry
from .event_payload import agent_event_key
from .media_status import (
    home_call_payload as _home_call_payload,
)
from .media_watchdog import AgentCpuWatchdog, handle_agent_cpu_metrics_changed
from .value_parsing import optional_mapping
from .video import (
    doorbell_camera_unique_id,
    optional_string,
)

if TYPE_CHECKING:
    from homeassistant.components.camera.webrtc import WebRTCError, WebRTCSendMessage
else:
    from homeassistant.components.camera import WebRTCError, WebRTCSendMessage

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
MAX_PRESESSION_WEBRTC_SESSIONS = 16
MAX_PRESESSION_WEBRTC_CANDIDATES = 64
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


def _freeze_state_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(
            (str(key), _freeze_state_value(item))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        )
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((_freeze_state_value(item) for item in value), key=repr))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_state_value(item) for item in value)
    return value


def _rtsp_client_count_from_status(status: Mapping[str, Any] | None) -> int | None:
    """Return the native RTSP client count if the agent reported it."""

    if status is None:
        return None
    bridge = optional_mapping(status.get("bridge"))
    clients = bridge.get("clients")
    if clients is None:
        return None
    try:
        return int(clients)
    except (TypeError, ValueError):
        return None


async def _async_get_supported_webrtc_provider(
    hass: HomeAssistant,
    stream_source: str,
) -> Any:
    """Return HA's active WebRTC provider without starting C300X media."""

    from homeassistant.components.camera.webrtc import (  # noqa: PLC0415
        DATA_WEBRTC_PROVIDERS,
    )

    providers = hass.data.get(DATA_WEBRTC_PROVIDERS)
    if not providers or not stream_source:
        return None
    for provider in providers:
        if provider.async_is_supported(stream_source):
            return provider
    return None


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
    _attr_frontend_stream_type = "web_rtc"
    _attr_should_poll = False
    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_translation_key = "doorbell_camera"

    def __init__(self, entry: BticinoC300XConfigEntry) -> None:
        Camera.__init__(self)
        C300XEntity.__init__(self, entry, "doorbell_camera")
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
        self._presession_webrtc_candidates: dict[str, list[Any]] = {}
        self._provider_webrtc_sessions: dict[str, _ProviderWebRTCSession] = {}
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
            **media_user_attribute(self._entry),
        }

    async def async_update(self) -> None:
        """Refresh doorbell video metadata on explicit HA update requests."""

        try:
            status = await self._entry.runtime_data.api.async_doorbell_video_status()
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
        if provider_context is not None:
            if provider_context.owner == "home_call":
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
        if owner == "home_call" and not wants_audio:
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

        if session_id in self._provider_webrtc_sessions:
            await self._async_close_webrtc_session(session_id)

        home_call_started = False
        stream_context = _ProviderWebRTCStreamContext(
            owner=owner,
            session_id=session_id,
            wants_audio=wants_audio,
            wants_backchannel=talkback_requested,
        )
        try:
            if owner == "home_call":
                await self._entry.runtime_data.api.async_start_home_call(
                    duration_seconds=duration_seconds
                )
                home_call_started = True
            await self._async_handle_provider_webrtc_offer(
                offer_sdp,
                session_id,
                send_message,
                owner=owner,
                wants_audio=wants_audio,
                talkback_requested=talkback_requested,
                stream_context=stream_context,
            )
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
            self._presession_webrtc_candidates.pop(session_id, None)
            await self._async_cleanup_failed_provider_offer(
                session_id,
                owner=owner,
                stream_context=stream_context,
            )
            if home_call_started:
                with suppress(Exception):
                    await self._entry.runtime_data.api.async_stop_home_call()
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
            self._presession_webrtc_candidates.pop(session_id, None)
            await self._async_cleanup_failed_provider_offer(
                session_id,
                owner=owner,
                stream_context=stream_context,
            )
            if home_call_started:
                with suppress(Exception):
                    await self._entry.runtime_data.api.async_stop_home_call()
            send_message(WebRTCError("bticino_webrtc_offer_failed", str(err)))

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
                ring_call=owner != "home_call" and _media_decision_is_ring_call(
                    decision
                ),
                ring_preview=owner != "home_call"
                and _media_decision_is_unanswered_ring(decision),
                pending_candidates=self._presession_webrtc_candidates.pop(
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
            self._provider_webrtc_sessions[session_id] = session
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
            current_session = self._provider_webrtc_sessions.get(session_id)
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
                        stop_media=stream_context.media_started,
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
                await self._async_flush_provider_webrtc_candidates(session_id)
        finally:
            _PROVIDER_WEBRTC_STREAM_CONTEXT.reset(token)

    async def _async_provider_webrtc_decision_snapshot(
        self,
        *,
        owner: str,
    ) -> MediaStateOutput:
        """Return a fresh media decision without starting native RTSP media."""

        if owner == "home_call":
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

        if owner == "home_call" or wants_audio:
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

        if owner == "home_call":
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

        had_provider_session = session_id in self._provider_webrtc_sessions
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
            stop_media=owner != "home_call" and stream_context.media_started,
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
                await self._entry.runtime_data.api.async_stop_doorbell_video()

    def _provider_offer_failure_should_stop_doorbell_media(
        self,
        owner: str,
        stream_context: _ProviderWebRTCStreamContext,
    ) -> bool:
        """Return true when a failed offer owns a started on-demand media path."""

        if owner == "home_call" or not stream_context.media_started:
            return False
        decision = self._last_media_decision
        return not (
            stream_context.ring_call
            or stream_context.ring_preview
            or _media_decision_is_ring_call(decision)
            or _media_decision_is_unanswered_ring(decision)
        )

    def _webrtc_diagnostic_label(
        self,
        session_id: str,
        *,
        owner: str,
        stream_url: str,
        wants_audio: bool,
        mode: str,
    ) -> str:
        """Return a compact, non-secret label for intermittent media RCA logs."""

        return (
            f"session={_short_session_id(session_id)} owner={owner} mode={mode} "
            f"audio={wants_audio}"
        )

    async def async_on_webrtc_candidate(self, session_id: str, candidate: Any) -> None:
        """Forward browser ICE candidates to the active WebRTC provider session."""

        provider_session = self._provider_webrtc_sessions.get(session_id)
        if provider_session is not None:
            if not provider_session.ready:
                if len(provider_session.pending_candidates) < MAX_PRESESSION_WEBRTC_CANDIDATES:
                    provider_session.pending_candidates.append(candidate)
                return
            await provider_session.provider.async_on_webrtc_candidate(
                session_id,
                candidate,
            )
            return

        pending = self._presession_webrtc_candidates.get(session_id)
        if pending is None:
            if len(self._presession_webrtc_candidates) >= MAX_PRESESSION_WEBRTC_SESSIONS:
                oldest_session_id = next(iter(self._presession_webrtc_candidates))
                self._presession_webrtc_candidates.pop(oldest_session_id, None)
            pending = []
            self._presession_webrtc_candidates[session_id] = pending
        if len(pending) < MAX_PRESESSION_WEBRTC_CANDIDATES:
            pending.append(candidate)

    async def _async_flush_provider_webrtc_candidates(self, session_id: str) -> None:
        """Replay ICE candidates that arrived before the provider session was ready."""

        session = self._provider_webrtc_sessions.get(session_id)
        if session is None or not session.ready:
            return
        while session.pending_candidates:
            await session.provider.async_on_webrtc_candidate(
                session_id,
                session.pending_candidates.pop(0),
            )

    @callback
    def close_webrtc_session(self, session_id: str) -> None:
        """Close an active WebRTC provider session."""

        self.hass.async_create_task(
            self._async_close_webrtc_session(
                session_id,
                stop_media=False,
                reason="webrtc_session_closed",
            )
        )

    async def async_will_remove_from_hass(self) -> None:
        """Stop active media sessions when HA removes the camera entity."""

        self._entry.runtime_data.prepare_doorbell_video_stop = None
        self._entry.runtime_data.prepare_home_call_stop = None
        for session_id in self._webrtc_session_ids():
            await self._async_close_webrtc_session(session_id, force_stop_media=True)
        with suppress(Exception):
            await self._entry.runtime_data.api.async_stop_doorbell_video()

    async def async_prepare_doorbell_video_stop(self) -> None:
        """Close HA-owned doorbell media before an explicit agent stop."""

        session_ids = self._webrtc_session_ids_by_owner("doorbell")
        await asyncio.gather(
            *(
                self._async_close_webrtc_session(
                    session_id,
                    stop_media=False,
                    notify_client=True,
                    reason="doorbell_video_stopped",
                )
                for session_id in session_ids
            )
        )
        if session_ids:
            await self._async_wait_for_provider_rtsp_clients_to_drain()

    async def async_prepare_home_call_stop(self) -> None:
        """Close HA-owned Home Call media before an explicit agent stop."""

        session_ids = self._webrtc_session_ids_by_owner("home_call")
        await asyncio.gather(
            *(
                self._async_close_webrtc_session(
                    session_id,
                    stop_media=False,
                    notify_client=True,
                    reason="home_call_stopped",
                )
                for session_id in session_ids
            )
        )
        if session_ids:
            await self._async_wait_for_provider_rtsp_clients_to_drain()

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
        provider_session = self._provider_webrtc_sessions.pop(session_id, None)
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
            self._presession_webrtc_candidates.pop(session_id, None)
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
            provider_close_path = await self._async_close_provider_webrtc_session(
                provider_session.provider,
                session_id,
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
            last_resource_session = not self._has_webrtc_sessions_for_resource(
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
                    if provider_session.owner == "home_call":
                        with suppress(Exception):
                            await self._entry.runtime_data.api.async_stop_home_call()
                    elif provider_session.ring_call:
                        with suppress(Exception):
                            await self._entry.runtime_data.api.async_hangup_doorbell_call()
                        with suppress(Exception):
                            await self._entry.runtime_data.api.async_stop_doorbell_video()
                    else:
                        with suppress(Exception):
                            await self._entry.runtime_data.api.async_stop_doorbell_video()
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

        self._presession_webrtc_candidates.pop(session_id, None)

    async def _async_warmup_video(self, *, audio: bool = False) -> None:
        """Mark the video window and refresh bridge metadata before RTSP opens."""

        await self._rtsp_orchestrator.async_warmup_video(audio=audio)

    async def _async_restart_video_reader(self, *, audio: bool = False) -> None:
        await self._rtsp_orchestrator.async_restart_video_reader(audio=audio)

    async def _async_restart_home_call_reader(self) -> None:
        await self._rtsp_orchestrator.async_restart_home_call_reader()

    async def _async_prepare_rtsp_stream(self, *, audio: bool = False) -> str:
        """Activate video and return a URL only after RTSP answers."""

        await self._async_close_finished_home_call_sessions()
        return await self._rtsp_orchestrator.async_prepare_rtsp_stream(audio=audio)

    async def _async_close_finished_home_call_sessions(self) -> None:
        """Close stale local Home Call sessions before starting doorbell media."""

        session_ids = self._webrtc_session_ids_by_owner("home_call")
        if not session_ids and not self._cached_home_call_state_needs_refresh():
            return

        try:
            status = await self._entry.runtime_data.api.async_home_call_status()
        except Exception:  # noqa: BLE001 - keep active-looking local sessions on status errors
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

    async def _async_wait_for_call_media_after_external_event(
        self,
        status: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Wait for a real SIP ring call after an OpenWebNet doorbell event."""

        return await self._rtsp_orchestrator.async_wait_for_call_media_after_external_event(
            status
        )

    async def _async_prepare_home_call_rtsp_stream(self) -> str:
        """Return the audio-only RTSP source for an active Home Call."""

        return await self._rtsp_orchestrator.async_prepare_home_call_rtsp_stream()

    async def _async_wait_for_home_call_active(
        self,
        *,
        apply_status: bool = True,
    ) -> Mapping[str, Any]:
        """Wait until the native agent reports the Home Call media as active."""

        return await self._rtsp_orchestrator.async_wait_for_home_call_active(
            apply_status=apply_status,
        )

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
            await self._entry.runtime_data.api.async_doorbell_video_status(),
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

    async def _async_wait_for_rtsp_ready(self, stream_url: str) -> None:
        """Wait briefly for the native RTSP bridge to accept RTSP requests."""

        await self._rtsp_orchestrator.async_wait_for_rtsp_ready(stream_url)

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

    def _raise_if_rtsp_cooling_down(self) -> None:
        self._rtsp_orchestrator.raise_if_rtsp_cooling_down()

    async def _async_probe_rtsp(self, stream_url: str) -> None:
        """Open a lightweight RTSP DESCRIBE request against the native bridge."""

        await self._rtsp_orchestrator.async_probe_rtsp(stream_url)

    async def _async_close_webrtc_sessions(
        self,
        session_ids: list[str],
        *,
        stop_media: bool = True,
        notify_client: bool = False,
        reason: str = "closed",
    ) -> None:
        for session_id in tuple(session_ids):
            await self._async_close_webrtc_session(
                session_id,
                stop_media=stop_media,
                notify_client=notify_client,
                reason=reason,
            )

    def _webrtc_session_ids(self) -> list[str]:
        """Return all HA-side WebRTC provider session IDs."""

        return list(self._provider_webrtc_sessions)

    def _webrtc_session_ids_by_owner(self, owner: str) -> list[str]:
        """Return HA-side WebRTC session ids for one logical media owner."""

        return [
            session_id
            for session_id, session in self._provider_webrtc_sessions.items()
            if session.owner == owner
        ]

    def _ring_preview_webrtc_session_ids(self) -> list[str]:
        """Return passive Ring preview session ids."""

        return [
            session_id
            for session_id, session in self._provider_webrtc_sessions.items()
            if session.owner == "doorbell" and session.ring_preview
        ]

    async def _async_close_provider_webrtc_session(
        self,
        provider: Any,
        session_id: str,
    ) -> str:
        """Close the provider session and await HA go2rtc consumer shutdown."""

        sessions = getattr(provider, "_sessions", None)
        if isinstance(sessions, MutableMapping):
            ws_client = sessions.pop(session_id, None)
            if ws_client is None:
                return "go2rtc_ws_missing"
            close = getattr(ws_client, "close", None)
            if not callable(close):
                return "go2rtc_ws_close_missing"
            try:
                result = close()
                if inspect.isawaitable(result):
                    await result
                    return "go2rtc_ws_awaited"
                return "go2rtc_ws_sync"
            except Exception as err:  # noqa: BLE001 - close cleanup must continue
                self._log_webrtc_debug(
                    "provider_go2rtc_ws_close_failed",
                    session_id=session_id,
                    provider=str(getattr(provider, "domain", type(provider).__name__)),
                    error_type=type(err).__name__,
                )
                return "go2rtc_ws_failed"

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
            self._log_webrtc_debug(
                "provider_close_failed",
                session_id=session_id,
                provider=str(getattr(provider, "domain", type(provider).__name__)),
                error_type=type(err).__name__,
            )
            return "provider_close_failed"

    def _has_webrtc_sessions(self) -> bool:
        """Return true when any HA-side WebRTC session remains registered."""

        return bool(self._provider_webrtc_sessions)

    def _has_webrtc_sessions_for_resource(self, resource_id: str) -> bool:
        """Return true while a local session still owns the same media resource."""

        return any(
            session.resource_id == resource_id
            for session in self._provider_webrtc_sessions.values()
        )

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

    def _apply_status(self, status: dict[str, Any]) -> None:
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
        self._refresh_derived_media_state()

    async def async_added_to_hass(self) -> None:
        """Subscribe to runtime event-state updates."""

        await super().async_added_to_hass()
        self._entry.runtime_data.prepare_doorbell_video_stop = (
            self.async_prepare_doorbell_video_stop
        )
        self._entry.runtime_data.prepare_home_call_stop = self.async_prepare_home_call_stop
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
        """Stop HA-held media if the device stays close to full CPU load."""

        handle_agent_cpu_metrics_changed(self, entry_id)

    @callback
    def _handle_agent_event(self, event: Any) -> None:
        if event.data.get("entry_id") != self._entry.entry_id:
            return
        event_type = agent_event_key(event.data)
        if event_type in HOME_CALL_EVENTS:
            self._handle_home_call_event(event_type, event.data)
            self._record_media_timeline(
                "agent_event",
                event_type,
                details=self._agent_event_timeline_details(event.data),
            )
            self._wake_rtsp_event_waiters()
            self._async_write_ha_state_if_ready()
            return
        if event_type not in VIDEO_WINDOW_EVENTS | VIDEO_WINDOW_CLOSED_EVENTS:
            return
        if event_type in VIDEO_WINDOW_CLOSED_EVENTS:
            self._clear_video_window()
            self._close_doorbell_webrtc_sessions_from_event()
            self._record_media_timeline(
                "agent_event",
                event_type,
                details=self._agent_event_timeline_details(event.data),
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
            details=self._agent_event_timeline_details(event.data),
        )
        self._wake_rtsp_event_waiters()
        self._async_write_ha_state_if_ready()

    def _handle_home_call_event(self, event_type: str, data: dict[str, Any]) -> None:
        payload = _home_call_payload(data)
        if event_type == "home_call_ended":
            self._apply_home_call_ended(payload)
            self._close_home_call_webrtc_sessions_from_event()
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

    def _close_home_call_webrtc_sessions_from_event(self) -> None:
        """Close HA Home Call WebRTC sessions after an authoritative agent end event."""

        session_ids = self._webrtc_session_ids_by_owner("home_call")
        if (
            not session_ids
            or not hasattr(self, "hass")
            or not hasattr(self.hass, "async_create_task")
        ):
            return

        async def _close_sessions() -> None:
            for session_id in session_ids:
                await self._async_close_webrtc_session(
                    session_id,
                    stop_media=False,
                    notify_client=True,
                    reason="home_call_ended",
                )

        self.hass.async_create_task(_close_sessions())

    def _close_doorbell_webrtc_sessions_from_event(self) -> None:
        """Close HA Doorbell WebRTC sessions after authoritative media close."""

        session_ids = self._webrtc_session_ids_by_owner("doorbell")
        if (
            not session_ids
            or not hasattr(self, "hass")
            or not hasattr(self.hass, "async_create_task")
        ):
            return

        async def _close_sessions() -> None:
            for session_id in session_ids:
                await self._async_close_webrtc_session(
                    session_id,
                    stop_media=False,
                    notify_client=True,
                    reason="doorbell_media_closed",
                )

        self.hass.async_create_task(_close_sessions())

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
        for session in self._provider_webrtc_sessions.values():
            if session.owner == "home_call":
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
        if not hasattr(self, "async_write_ha_state"):
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

        runtime = getattr(self._entry, "runtime_data", None)
        timeline = getattr(runtime, "media_timeline", None)
        record = getattr(timeline, "record", None)
        if not callable(record):
            return
        ready_sessions = sum(
            1 for session in self._provider_webrtc_sessions.values() if session.ready
        )
        record(
            kind=kind,
            event=event,
            media_state=self._last_media_state.value,
            owner=self._video_owner,
            session_count=len(self._provider_webrtc_sessions),
            ring_preview_sessions=len(self._ring_preview_webrtc_session_ids()),
            ready_sessions=ready_sessions,
            details=details,
        )

    def _agent_event_timeline_details(
        self,
        data: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Return safe media facts from one already-received agent event."""

        details: dict[str, Any] = {}
        for key in (
            "video_available",
            "video_window_available",
            "external_media_active",
        ):
            if key in data:
                details[key] = bool(data[key])
        bridge = optional_mapping(data.get("bridge"))
        if bridge:
            for key in (
                "clients",
                "media_active",
                "ring_call_active",
                "ring_media_active",
                "ring_audio_active",
                "ring_answer_requested",
                "ring_answered",
                "ring_hangup_requested",
                "home_call_running",
                "home_call_active",
            ):
                if key in bridge:
                    details[f"bridge_{key}"] = bridge[key]
        return details

    def _refresh_derived_media_state(self) -> None:
        self._last_media_decision = self._derive_media_decision()
        self._last_media_state = self._last_media_decision.state

    def _derive_media_decision(
        self,
        status: dict[str, Any] | None = None,
    ) -> MediaStateOutput:
        facts = self._media_state_input_from_status(status)
        return derive_media_state(facts)

    def _raise_if_rtsp_admission_denied(
        self,
        status: Mapping[str, Any],
        decision: MediaStateOutput,
    ) -> None:
        self._rtsp_orchestrator.raise_if_rtsp_admission_denied(
            status,
            decision,
            consumer=_rtsp_consumer_for_doorbell_request(decision),
        )

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
            local_sessions=self._active_local_media_sessions(),
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

    def _active_local_media_sessions(self) -> int:
        provider_resources = {
            session.resource_id
            for session in self._provider_webrtc_sessions.values()
            if session.ready
        }
        return len(provider_resources)


def _home_call_status_has_media(status: Mapping[str, Any]) -> bool:
    """Return true while the agent reports an active Home Call media path."""

    return bool(
        status.get("running")
        or status.get("active")
        or status.get("answered")
        or status.get("rtp_proxy")
        or status.get("target_audio_port")
    )


@callback
def async_register_home_call_ws(hass: HomeAssistant) -> None:
    """Register Home Call audio WebRTC websocket commands."""

    _async_register_home_call_ws(hass, C300XDoorbellCamera)
