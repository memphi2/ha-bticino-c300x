"""Camera entity for the C300X doorbell WebRTC stream."""

from __future__ import annotations

import asyncio
import importlib
import logging
import time
import warnings
from collections.abc import Mapping
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

from homeassistant.components.camera import (
    Camera,
    CameraEntityFeature,
    WebRTCError,
    WebRTCSendMessage,
)
from homeassistant.components.stream import (
    CONF_RTSP_TRANSPORT,
    CONF_USE_WALLCLOCK_AS_TIMESTAMPS,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from propcache.api import cached_property

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
from .camera_media.rtsp_reader import (
    SharedRTSPMediaSource,
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
from .camera_media.talkback import (
    TALKBACK_CODEC,
    TALKBACK_RTP_PAYLOAD_TYPE,
    async_forward_talkback_audio,
)
from .camera_media.webrtc_session import (
    NativeWebRTCSession as _NativeWebRTCSession,
)
from .camera_media.webrtc_session import (
    NativeWebRTCSessionRegistry as _NativeWebRTCSessionRegistry,
)
from .camera_media.webrtc_session import (
    async_flush_pending_webrtc_candidates as _async_flush_pending_webrtc_candidates,
)
from .camera_media.webrtc_session import (
    rtc_candidate_from_message as _rtc_candidate_from_message,
)
from .camera_media.webrtc_session import (
    webrtc_session_peer_closed as _webrtc_session_peer_closed_impl,
)
from .const import (
    CONF_AGENT_HOST,
    CONF_DOORSTATION_AUDIO_GAIN_DB,
    CONF_VIDEO_PORT,
    CONF_VIDEO_STREAM_PATH,
    DEFAULT_DOORSTATION_AUDIO_GAIN_DB,
    DEFAULT_VIDEO_PORT,
    DEFAULT_VIDEO_STREAM_PATH,
    EVENT_AGENT_EVENT_RECEIVED,
    SIGNAL_SYSTEM_METRICS_CHANGED,
)
from .device_user import media_user_attribute
from .entity import C300XEntity, entry_config_value, supports_capability
from .event_payload import agent_event_key
from .media_status import (
    home_call_payload as _home_call_payload,
)
from .media_watchdog import AgentCpuWatchdog, handle_agent_cpu_metrics_changed
from .video import (
    doorbell_camera_unique_id,
    optional_string,
)

PARALLEL_UPDATES = 0
VIDEO_WINDOW_EVENTS = {"doorbell_pressed", "doorbell_view_requested"}
VIDEO_WINDOW_CLOSED_EVENTS = {"doorbell_media_closed"}
HOME_CALL_EVENTS = {"home_call_started", "home_call_answered", "home_call_ended"}
CALL_MEDIA_STATES = {
    MediaState.RING_PENDING,
    MediaState.RING_PREVIEW_ACTIVE,
    MediaState.RING_ANSWERING,
    MediaState.RING_ACTIVE,
    MediaState.HOME_CALL_STARTING,
    MediaState.HOME_CALL_RINGING,
    MediaState.HOME_CALL_ACTIVE,
}
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
HOME_CALL_STATES = {
    MediaState.HOME_CALL_STARTING,
    MediaState.HOME_CALL_RINGING,
    MediaState.HOME_CALL_ACTIVE,
    MediaState.HOME_CALL_STOPPING,
}
RTSP_READY_CONNECT_TIMEOUT_SECONDS = 1.0
RTSP_READY_INTERVAL_SECONDS = 0.25
RTSP_READY_TIMEOUT_SECONDS = 6.0
RTSP_FAILURE_COOLDOWN_SECONDS = 20.0
RING_CALL_WAIT_INTERVAL_SECONDS = 0.2
RING_CALL_WAIT_TIMEOUT_SECONDS = 4.0
WEBRTC_RENEW_SECONDS = 60
MAX_PRESESSION_WEBRTC_SESSIONS = 16
MAX_PRESESSION_WEBRTC_CANDIDATES = 64
STILL_IMAGE_CONTENT_TYPE = "image/svg+xml"
STILL_IMAGE_BYTES = b"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360"><rect width="640" height="360" fill="#111820"/><g fill="none" stroke="#8da2b5" stroke-width="16" stroke-linecap="round" stroke-linejoin="round"><path d="M216 152h178v96H216z"/><path d="M394 180l82-46v132l-82-46z"/><path d="M250 152l-32-56h174l-32 56"/><path d="M305 248v48"/><path d="M250 296h142"/></g></svg>"""
_LOGGER = logging.getLogger(__name__)

_AIORTC_MODULES: SimpleNamespace | None = None
_PROVIDER_WEBRTC_STREAM_CONTEXT: ContextVar[_ProviderWebRTCStreamContext | None] = (
    ContextVar("bticino_c300x_provider_webrtc_stream_context", default=None)
)
_MDNS_CACHE_FLUSH_BIT = 0x8000
_DNS_MDNS_RDATA_MODULES = (
    "dns.rdtypes.IN.A",
    "dns.rdtypes.IN.AAAA",
    "dns.rdtypes.IN.PTR",
    "dns.rdtypes.ANY.A",
    "dns.rdtypes.ANY.AAAA",
    "dns.rdtypes.ANY.PTR",
    "dns.rdtypes.ANY.SRV",
    "dns.rdtypes.ANY.TXT",
    "dns.rdtypes.ANY.NSEC",
    "dns.rdtypes.CLASS32769.TXT",
    "dns.rdtypes.CLASS32769.NSEC",
)


def _preload_dns_mdns_modules(
    import_module: Any = importlib.import_module,
) -> None:
    """Preload dnspython mDNS record modules outside HA's event loop."""

    for module_name in _DNS_MDNS_RDATA_MODULES:
        with suppress(ImportError):
            import_module(module_name)
    with suppress(ImportError, AttributeError):
        dns_rdata = import_module("dns.rdata")
        dns_rdataclass = import_module("dns.rdataclass")
        dns_rdatatype = import_module("dns.rdatatype")
        mdns_rdclass = int(dns_rdataclass.IN) | _MDNS_CACHE_FLUSH_BIT
        for rdtype in (
            dns_rdatatype.A,
            dns_rdatatype.AAAA,
            dns_rdatatype.PTR,
            dns_rdatatype.SRV,
            dns_rdatatype.TXT,
            getattr(dns_rdatatype, "NSEC", 47),
        ):
            dns_rdata.get_rdata_class(mdns_rdclass, rdtype)


def _load_aiortc_modules() -> SimpleNamespace:
    """Import aiortc modules outside Home Assistant's event loop."""

    global _AIORTC_MODULES
    if _AIORTC_MODULES is not None:
        return _AIORTC_MODULES

    _preload_dns_mdns_modules()

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=(
                r"As the c extension couldn't be imported, "
                r"`google-crc32c` is using a pure python implementation.*"
            ),
            category=RuntimeWarning,
        )
        import av
        from aiortc import (
            RTCConfiguration,
            RTCIceServer,
            RTCPeerConnection,
            RTCRtpSender,
            RTCSessionDescription,
        )
        from aiortc.contrib.media import MediaPlayer, MediaRelay
        from aiortc.mediastreams import (
            AudioStreamTrack,
            MediaStreamError,
            VideoStreamTrack,
        )
        from aiortc.sdp import candidate_from_sdp
        from av.audio.resampler import AudioResampler

    _AIORTC_MODULES = SimpleNamespace(
        av=av,
        AudioResampler=AudioResampler,
        AudioStreamTrack=AudioStreamTrack,
        candidate_from_sdp=candidate_from_sdp,
        MediaPlayer=MediaPlayer,
        MediaRelay=MediaRelay,
        MediaStreamError=MediaStreamError,
        RTCConfiguration=RTCConfiguration,
        RTCIceServer=RTCIceServer,
        RTCPeerConnection=RTCPeerConnection,
        RTCRtpSender=RTCRtpSender,
        RTCSessionDescription=RTCSessionDescription,
        VideoStreamTrack=VideoStreamTrack,
    )
    return _AIORTC_MODULES


def _media_decision_is_call_media(decision: MediaStateOutput) -> bool:
    return decision.state in CALL_MEDIA_STATES


def _media_decision_is_ring_call(decision: MediaStateOutput) -> bool:
    return decision.state in RING_CALL_STATES


def _media_decision_is_unanswered_ring(decision: MediaStateOutput) -> bool:
    return decision.state in UNANSWERED_RING_STATES


def _media_decision_is_home_call(decision: MediaStateOutput) -> bool:
    return decision.state in HOME_CALL_STATES


def _capability_supported_if_known(entry: ConfigEntry, capability: str) -> bool:
    capabilities = getattr(getattr(entry, "runtime_data", None), "capabilities", None)
    if not isinstance(capabilities, dict) or not capabilities:
        return True
    return supports_capability(entry, capability)


async def _async_get_supported_webrtc_provider(hass: HomeAssistant, camera: Camera) -> Any:
    """Return HA's active WebRTC provider without importing it in test stubs."""

    from homeassistant.components.camera.webrtc import (  # noqa: PLC0415
        async_get_supported_provider,
    )

    return await async_get_supported_provider(hass, camera)


@dataclass(frozen=True)
class _ProviderWebRTCStreamContext:
    owner: str
    wants_audio: bool


@dataclass
class _ProviderWebRTCSession:
    provider: Any
    owner: str
    send_message: WebRTCSendMessage
    wants_audio: bool
    resource_id: str
    ring_call: bool = False
    ring_preview: bool = False
    ready: bool = False
    pending_candidates: list[Any] = field(default_factory=list)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the optional C300X WebRTC camera."""

    if supports_capability(entry, "doorbell_video"):
        async_add_entities([C300XDoorbellCamera(entry)])


class C300XDoorbellCamera(C300XEntity, Camera):
    """Camera that exposes the agent media bridge through native WebRTC."""

    _attr_icon = "mdi:cctv"
    _attr_frontend_stream_type = "web_rtc"
    _attr_should_poll = False
    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_translation_key = "doorbell_camera"

    def __init__(self, entry: ConfigEntry) -> None:
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
        self._talkback_last_error: str | None = None
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
        self._webrtc_sessions: dict[str, _NativeWebRTCSession] = {}
        self._presession_webrtc_candidates: dict[str, list[Any]] = {}
        self._webrtc_session_registry = _NativeWebRTCSessionRegistry(
            self._webrtc_sessions
        )
        self._provider_webrtc_sessions: dict[str, _ProviderWebRTCSession] = {}
        self._webrtc_resource_renew_tasks: dict[str, asyncio.Task[Any]] = {}
        self._shared_ring_rtsp_source: SharedRTSPMediaSource | None = None
        if not hasattr(self, "stream_options"):
            self.stream_options = {}
        self.stream_options[CONF_RTSP_TRANSPORT] = "tcp"
        self.stream_options[CONF_USE_WALLCLOCK_AS_TIMESTAMPS] = True

    @property
    def available(self) -> bool:
        """Return whether the configured RTSP endpoint is addressable."""

        return super().available

    @property
    def entity_picture(self) -> None:
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
                stream_url = await self._async_prepare_rtsp_stream(
                    audio=provider_context.wants_audio
                )
            if provider_context.wants_audio:
                return f"{stream_url}#backchannel=1"
            return stream_url
        return await self._async_prepare_rtsp_stream()

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
        if owner == "home_call" and not wants_audio:
            send_message(
                WebRTCError(
                    "bticino_webrtc_offer_failed",
                    "Home Call WebRTC offer must accept incoming audio",
                )
            )
            return

        if (
            session_id in self._webrtc_sessions
            or session_id in self._provider_webrtc_sessions
        ):
            await self._async_close_webrtc_session(session_id)

        home_call_started = False
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
            )
        except HomeAssistantError as err:
            self._presession_webrtc_candidates.pop(session_id, None)
            await self._async_close_webrtc_session(
                session_id,
                stop_media=False,
                notify_client=False,
            )
            if home_call_started:
                with suppress(Exception):
                    await self._entry.runtime_data.api.async_stop_home_call()
            send_message(WebRTCError("bticino_webrtc_unavailable", str(err)))
        except Exception as err:
            self._presession_webrtc_candidates.pop(session_id, None)
            await self._async_close_webrtc_session(
                session_id,
                stop_media=False,
                notify_client=False,
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
    ) -> None:
        """Delegate one browser WebRTC offer to HA/go2rtc."""

        stream_context = _ProviderWebRTCStreamContext(
            owner=owner,
            wants_audio=wants_audio,
        )
        token = _PROVIDER_WEBRTC_STREAM_CONTEXT.set(stream_context)
        try:
            provider = await _async_get_supported_webrtc_provider(self.hass, self)
            if provider is None:
                raise HomeAssistantError(
                    "No Home Assistant WebRTC provider is available for the C300X RTSP stream"
                )
            decision = self._last_media_decision
            session = _ProviderWebRTCSession(
                provider=provider,
                owner=owner,
                send_message=send_message,
                wants_audio=wants_audio,
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
            self._provider_webrtc_sessions[session_id] = session
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
            await provider.async_handle_async_webrtc_offer(
                self,
                offer_sdp,
                session_id,
                send_message,
            )
            current_session = self._provider_webrtc_sessions.get(session_id)
            if current_session is session:
                session.ready = True
                await self._async_flush_provider_webrtc_candidates(session_id)
        finally:
            _PROVIDER_WEBRTC_STREAM_CONTEXT.reset(token)

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

    def _ring_rtsp_tracks(
        self,
        aiortc_modules: SimpleNamespace,
        stream_url: str,
        *,
        restart_callback: Any,
        include_audio: bool,
        diagnostic_label: str,
    ) -> tuple[Any, Any, Any | None]:
        """Return relay tracks for Ring Call media backed by one RTSP reader."""

        source = self._shared_ring_rtsp_source
        if (
            source is None
            or source.closed
            or source.stream_url != stream_url
        ):
            if source is not None:
                source.stop()
            source = SharedRTSPMediaSource(
                resource_id=f"ring:{self._entry.entry_id}",
                av_module=aiortc_modules.av,
                media_relay_cls=aiortc_modules.MediaRelay,
                video_stream_track_cls=aiortc_modules.VideoStreamTrack,
                audio_stream_track_cls=aiortc_modules.AudioStreamTrack,
                media_stream_error_cls=aiortc_modules.MediaStreamError,
                media_player_cls=aiortc_modules.MediaPlayer,
                hass=self.hass,
                stream_url=stream_url,
                restart_callback=restart_callback,
                audio_gain_db=self._doorstation_audio_gain_db(),
                diagnostic_label=diagnostic_label,
            )
            self._shared_ring_rtsp_source = source
        return source.acquire(include_audio=include_audio)

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

        session = self._webrtc_sessions.get(session_id)
        if session is None:
            pending = self._presession_webrtc_candidates.get(session_id)
            if pending is None:
                if len(self._presession_webrtc_candidates) >= MAX_PRESESSION_WEBRTC_SESSIONS:
                    oldest_session_id = next(iter(self._presession_webrtc_candidates))
                    self._presession_webrtc_candidates.pop(oldest_session_id, None)
                pending = []
                self._presession_webrtc_candidates[session_id] = pending
            if len(pending) < MAX_PRESESSION_WEBRTC_CANDIDATES:
                pending.append(candidate)
            return

        try:
            aiortc_modules = await self._async_load_aiortc_modules()
        except ImportError:
            return

        rtc_candidate = _rtc_candidate_from_message(aiortc_modules, candidate)
        if rtc_candidate is None:
            return

        if getattr(session.peer, "remoteDescription", None) is None:
            session.pending_ice_candidates.append(rtc_candidate)
            return

        await session.peer.addIceCandidate(rtc_candidate)

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

    def _schedule_pending_webrtc_candidate_flush(self, session_id: str) -> None:
        """Flush early browser ICE candidates without blocking the WebRTC answer."""

        session = self._webrtc_sessions.get(session_id)
        if (
            session is None
            or not session.pending_ice_candidates
            or (session.ice_flush_task is not None and not session.ice_flush_task.done())
        ):
            return
        session.ice_flush_task = self.hass.async_create_task(
            self._async_flush_pending_webrtc_candidates(session_id)
        )

    async def _async_flush_pending_webrtc_candidates(self, session_id: str) -> None:
        """Replay ICE candidates that arrived before the remote description."""

        session = self._webrtc_sessions.get(session_id)
        if session is None:
            return
        try:
            await _async_flush_pending_webrtc_candidates(session)
        finally:
            current_session = self._webrtc_sessions.get(session_id)
            if current_session is session:
                session.ice_flush_task = None

    @callback
    def close_webrtc_session(self, session_id: str) -> None:
        """Close an active native WebRTC session."""

        self.hass.async_create_task(self._async_close_webrtc_session(session_id))

    async def async_will_remove_from_hass(self) -> None:
        """Stop active media sessions when HA removes the camera entity."""

        self._entry.runtime_data.prepare_doorbell_video_stop = None
        self._entry.runtime_data.prepare_home_call_stop = None
        for session_id in self._webrtc_session_ids():
            await self._async_close_webrtc_session(session_id)
        with suppress(Exception):
            await self._entry.runtime_data.api.async_stop_doorbell_video()

    async def async_prepare_doorbell_video_stop(self) -> None:
        """Close HA-owned doorbell media before an explicit agent stop."""

        await asyncio.gather(
            *(
                self._async_close_webrtc_session(
                    session_id,
                    stop_media=False,
                    notify_client=True,
                    reason="doorbell_video_stopped",
                )
                for session_id in self._webrtc_session_ids_by_owner("doorbell")
            )
        )

    async def async_prepare_home_call_stop(self) -> None:
        """Close HA-owned Home Call media before an explicit agent stop."""

        await asyncio.gather(
            *(
                self._async_close_webrtc_session(
                    session_id,
                    stop_media=False,
                    notify_client=True,
                    reason="home_call_stopped",
                )
                for session_id in self._webrtc_session_ids_by_owner("home_call")
            )
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
            self._presession_webrtc_candidates.pop(session_id, None)
            with suppress(Exception):
                provider_session.provider.async_close_session(session_id)
            if notify_client:
                with suppress(Exception):
                    provider_session.send_message(
                        {"type": "closed", "reason": reason}
                    )
            if provider_session.ring_preview:
                with suppress(Exception):
                    provider_session.ring_preview = _media_decision_is_unanswered_ring(
                        self._derive_media_decision(
                            await self._async_refresh_video_status(apply_status=False)
                        )
                    )
            if (
                not self._has_webrtc_sessions()
                and stop_media
                and (
                    force_stop_media
                    or (
                        not provider_session.ring_preview
                        and not provider_session.ring_call
                    )
                )
            ):
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
            return

        session = await self._webrtc_session_registry.async_close_session_resources(
            session_id,
            notify_client=notify_client,
            reason=reason,
        )
        self._presession_webrtc_candidates.pop(session_id, None)
        if session is None:
            return

        self._cancel_webrtc_resource_renewal_if_unused(session)

        if session.ring_preview:
            with suppress(Exception):
                session.ring_preview = _media_decision_is_unanswered_ring(
                    self._derive_media_decision(
                        await self._async_refresh_video_status(apply_status=False)
                    )
                )

        if (
            not self._has_webrtc_sessions()
            and stop_media
            and (
                force_stop_media
                or (not session.ring_preview and not session.ring_call)
            )
        ):
            if session.owner == "home_call":
                with suppress(Exception):
                    await self._entry.runtime_data.api.async_stop_home_call()
            elif session.ring_call:
                with suppress(Exception):
                    await self._entry.runtime_data.api.async_hangup_doorbell_call()
                with suppress(Exception):
                    await self._entry.runtime_data.api.async_stop_doorbell_video()
            else:
                with suppress(Exception):
                    await self._entry.runtime_data.api.async_stop_doorbell_video()

    async def _async_warmup_video(self, *, audio: bool = False) -> None:
        """Mark the video window and refresh bridge metadata before RTSP opens."""

        await self._rtsp_orchestrator.async_warmup_video(audio=audio)

    async def _async_restart_video_reader(self, *, audio: bool = False) -> None:
        await self._rtsp_orchestrator.async_restart_video_reader(audio=audio)

    async def _async_restart_home_call_reader(self) -> None:
        await self._rtsp_orchestrator.async_restart_home_call_reader()

    async def _async_prepare_rtsp_stream(self, *, audio: bool = False) -> str:
        """Activate video and return a URL only after RTSP answers."""

        await self._async_close_stale_webrtc_sessions()
        await self._async_close_finished_home_call_sessions()
        return await self._rtsp_orchestrator.async_prepare_rtsp_stream(audio=audio)

    async def _async_close_stale_webrtc_sessions(self) -> None:
        """Close terminal WebRTC peers before evaluating RTSP admission."""

        for session_id, session in list(self._webrtc_sessions.items()):
            if _webrtc_session_peer_closed(session):
                await self._async_close_webrtc_session(
                    session_id,
                    notify_client=True,
                    reason="webrtc_closed",
                )

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
        status = await self._entry.runtime_data.api.async_doorbell_video_status()
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

    def _raise_if_rtsp_cooling_down(self) -> None:
        self._rtsp_orchestrator.raise_if_rtsp_cooling_down()

    async def _async_probe_rtsp(self, stream_url: str) -> None:
        """Open a lightweight RTSP OPTIONS request against the native bridge."""

        await self._rtsp_orchestrator.async_probe_rtsp(stream_url)

    async def _async_renew_webrtc_until_closed(self, session_id: str) -> None:
        while session_id in self._webrtc_sessions:
            await asyncio.sleep(WEBRTC_RENEW_SECONDS)
            await self._async_renew_webrtc_session_once(session_id)

    def _schedule_webrtc_renewal(self, session_id: str) -> None:
        session = self._webrtc_sessions.get(session_id)
        if session is None:
            return
        resource_id = _webrtc_session_resource_id(session)
        if resource_id is None:
            session.renew_task = self.hass.async_create_task(
                self._async_renew_webrtc_until_closed(session_id)
            )
            return
        task = self._webrtc_resource_renew_tasks.get(resource_id)
        if task is not None and not task.done():
            return
        self._webrtc_resource_renew_tasks[resource_id] = self.hass.async_create_task(
            self._async_renew_webrtc_resource_until_closed(resource_id)
        )

    async def _async_renew_webrtc_resource_until_closed(self, resource_id: str) -> None:
        try:
            while self._webrtc_session_ids_for_resource(resource_id):
                await asyncio.sleep(WEBRTC_RENEW_SECONDS)
                await self._async_renew_webrtc_resource_once(resource_id)
        finally:
            if self._webrtc_resource_renew_tasks.get(resource_id) is asyncio.current_task():
                self._webrtc_resource_renew_tasks.pop(resource_id, None)

    async def _async_renew_webrtc_resource_once(self, resource_id: str) -> None:
        session_ids = self._webrtc_session_ids_for_resource(resource_id)
        if not session_ids:
            return
        for session_id in tuple(session_ids):
            session = self._webrtc_sessions.get(session_id)
            if session is None or not _webrtc_session_peer_closed(session):
                continue
            await self._async_close_webrtc_session(
                session_id,
                notify_client=True,
                reason="webrtc_closed",
            )

        session_ids = self._webrtc_session_ids_for_resource(resource_id)
        home_call_session_ids = [
            session_id
            for session_id in session_ids
            if self._webrtc_sessions[session_id].owner == "home_call"
        ]
        for session_id in home_call_session_ids:
            await self._async_renew_webrtc_session_once(session_id)

        session_ids = self._webrtc_session_ids_for_resource(resource_id)
        doorbell_session_ids = [
            session_id
            for session_id in session_ids
            if self._webrtc_sessions[session_id].owner != "home_call"
        ]
        if not doorbell_session_ids:
            return
        with suppress(Exception):
            decision = self._derive_media_decision(
                await self._async_refresh_video_status(apply_status=False)
            )
            if _media_decision_is_call_media(decision):
                return
            if not decision.webrtc_keepalive_allowed:
                await self._async_close_webrtc_sessions(
                    doorbell_session_ids,
                    stop_media=False,
                    notify_client=True,
                    reason=f"media_state_{decision.state.value}",
                )
                return

        ring_session_ids = [
            session_id
            for session_id in doorbell_session_ids
            if self._webrtc_sessions.get(session_id) is not None
            and self._webrtc_sessions[session_id].ring_call
        ]
        if ring_session_ids:
            await self._async_close_webrtc_sessions(
                ring_session_ids,
                stop_media=False,
                notify_client=True,
                reason="ring_call_closed",
            )
        if len(ring_session_ids) < len(doorbell_session_ids):
            with suppress(Exception):
                await self._async_warmup_video()

    async def _async_renew_webrtc_session_once(self, session_id: str) -> None:
        session = self._webrtc_sessions.get(session_id)
        if session is None:
            return
        if _webrtc_session_peer_closed(session):
            await self._async_close_webrtc_session(
                session_id,
                notify_client=True,
                reason="webrtc_closed",
            )
            return
        if session.owner == "home_call":
            try:
                home_call_status = await self._entry.runtime_data.api.async_home_call_status()
            except Exception:  # noqa: BLE001 - transient status errors must not tear down active calls
                return
            if not _home_call_status_has_media(home_call_status):
                self._apply_home_call_ended(dict(home_call_status))
                await self._async_close_webrtc_session(
                    session_id,
                    stop_media=False,
                    notify_client=True,
                    reason="home_call_ended",
                )
            return
        with suppress(Exception):
            decision = self._derive_media_decision(
                await self._async_refresh_video_status(apply_status=False)
            )
            if _media_decision_is_call_media(decision):
                return
            if not decision.webrtc_keepalive_allowed:
                await self._async_close_webrtc_session(
                    session_id,
                    stop_media=False,
                    notify_client=True,
                    reason=f"media_state_{decision.state.value}",
                )
                return
        if session.ring_call:
            await self._async_close_webrtc_session(
                session_id,
                stop_media=False,
                notify_client=True,
                reason="ring_call_closed",
            )
            return
        with suppress(Exception):
            await self._async_warmup_video()

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
        """Return all HA-side WebRTC session ids, native first for stable cleanup."""

        return [
            *self._webrtc_session_registry.session_ids(),
            *self._provider_webrtc_sessions,
        ]

    def _webrtc_session_ids_by_owner(self, owner: str) -> list[str]:
        """Return HA-side WebRTC session ids for one logical media owner."""

        return [
            *self._webrtc_session_registry.session_ids_by_owner(owner),
            *(
                session_id
                for session_id, session in self._provider_webrtc_sessions.items()
                if session.owner == owner
            ),
        ]

    def _webrtc_session_ids_for_ring_call(self) -> list[str]:
        """Return HA-side session ids that are bound to an answered ring call."""

        return [
            *self._webrtc_session_registry.session_ids_for_ring_call(),
            *(
                session_id
                for session_id, session in self._provider_webrtc_sessions.items()
                if session.ring_call
            ),
        ]

    def _has_webrtc_sessions(self) -> bool:
        """Return true when any HA-side WebRTC session remains registered."""

        return self._webrtc_session_registry.has_sessions() or bool(
            self._provider_webrtc_sessions
        )

    def _webrtc_session_ids_for_resource(self, resource_id: str) -> list[str]:
        return [
            session_id
            for session_id, session in self._webrtc_sessions.items()
            if _webrtc_session_resource_id(session) == resource_id
        ]

    def _cancel_webrtc_resource_renewal_if_unused(
        self,
        session: _NativeWebRTCSession,
    ) -> None:
        resource_id = _webrtc_session_resource_id(session)
        if resource_id is None or self._webrtc_session_ids_for_resource(resource_id):
            return
        task = self._webrtc_resource_renew_tasks.pop(resource_id, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    def _talkback_supported(self) -> bool:
        """Return true when the bridge can accept WebRTC microphone audio."""

        if "talkback_supported" in self._bridge_status:
            return bool(self._bridge_status["talkback_supported"])
        return bool(
            self._audio_stream_path
            or self._bridge_status.get("audio_stream_path")
            or self._bridge_status.get("audio_codec") == TALKBACK_CODEC
        )

    async def _async_forward_talkback_audio(
        self,
        track: Any,
        aiortc_modules: SimpleNamespace,
        session_id: str,
    ) -> None:
        """Encode browser microphone audio as Speex/8k RTP for C300X talkback."""

        await async_forward_talkback_audio(
            track,
            aiortc_modules,
            self._agent_host_for_socket(),
            on_active=lambda active: self._set_talkback_active(session_id, active),
            on_error=self._set_talkback_error,
            on_packet=lambda: self._increment_talkback_packets(session_id),
        )

    def _set_talkback_active(self, session_id: str, active: bool) -> None:
        session = self._webrtc_sessions.get(session_id)
        if session is None or session.talkback_active == active:
            return
        session.talkback_active = active
        self._async_write_ha_state_if_ready()

    def _set_talkback_error(self, error: str | None) -> None:
        if self._talkback_last_error == error:
            return
        self._talkback_last_error = error
        self._async_write_ha_state_if_ready()

    def _increment_talkback_packets(self, session_id: str) -> None:
        session = self._webrtc_sessions.get(session_id)
        if session is None:
            return
        session.talkback_packets_sent += 1
        if session.talkback_packets_sent == 1:
            self._async_write_ha_state_if_ready()

    async def _async_load_aiortc_modules(self) -> SimpleNamespace:
        return await self.hass.async_add_executor_job(_load_aiortc_modules)

    def _agent_host(self) -> str:
        """Return the configured agent host without surrounding whitespace."""

        return str(entry_config_value(self._entry, CONF_AGENT_HOST, "")).strip()

    def _agent_host_for_socket(self) -> str:
        """Return the agent host in a form accepted by socket APIs."""

        return _agent_host_for_socket(self._agent_host())

    def _agent_host_for_url(self) -> str:
        """Return the agent host in a form accepted in RTSP URLs."""

        return _agent_host_for_url(self._agent_host())

    def _doorstation_audio_gain_db(self) -> float:
        """Return the configured live doorstation audio gain in dB."""

        try:
            gain = float(
                entry_config_value(
                    self._entry,
                    CONF_DOORSTATION_AUDIO_GAIN_DB,
                    DEFAULT_DOORSTATION_AUDIO_GAIN_DB,
                )
            )
        except (TypeError, ValueError):
            return DEFAULT_DOORSTATION_AUDIO_GAIN_DB
        return min(12.0, max(-12.0, gain))

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
        self._bridge_status = status.get("bridge") or {}
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
            self._async_write_ha_state_if_ready()
            return
        if event_type not in VIDEO_WINDOW_EVENTS | VIDEO_WINDOW_CLOSED_EVENTS:
            return
        if event_type in VIDEO_WINDOW_CLOSED_EVENTS:
            self._clear_video_window()
            self._close_ring_webrtc_sessions_from_event()
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

    def _close_ring_webrtc_sessions_from_event(self) -> None:
        """Close HA Ring Call WebRTC sessions after an authoritative agent end event."""

        session_ids = self._webrtc_session_ids_for_ring_call()
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
                    reason="ring_call_closed",
                )

        self.hass.async_create_task(_close_sessions())

    def _apply_home_call_ended(self, status: dict[str, Any]) -> None:
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
            "home_call_rtp_proxy": False,
            "home_call_target_audio_port": 0,
            "home_call_rtp_packets": status.get("rtp_packets", 0),
            "home_call_rtcp_packets": status.get("rtcp_packets", 0),
        }
        if was_home_call:
            self._bridge_status["media_owner"] = "idle"
            self._video_owner = "idle"
            self._video_window_available = False
            self._attr_is_streaming = False
            self._video_stream_path = None
            self._audio_stream_path = None
            self._recorder_stream_path = None
        self._refresh_derived_media_state()

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
        if hasattr(self, "async_write_ha_state"):
            self.async_write_ha_state()

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
        bridge = data.get("bridge")
        if isinstance(bridge, Mapping):
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
        return (
            self._webrtc_session_registry.active_media_sessions()
            + len(provider_resources)
        )


def _home_call_status_has_media(status: Mapping[str, Any]) -> bool:
    """Return true while the agent reports an active Home Call media path."""

    return bool(
        status.get("running")
        or status.get("active")
        or status.get("answered")
        or status.get("rtp_proxy")
        or status.get("target_audio_port")
    )


def _short_session_id(session_id: str) -> str:
    """Return a compact WebRTC session id fragment for logs."""

    text = str(session_id)
    if len(text) <= 12:
        return text
    return f"...{text[-8:]}"


def _safe_stream_path_for_log(stream_url: str) -> str:
    """Return only the stream path, avoiding host data in production logs."""

    try:
        return urlsplit(stream_url).path or "/"
    except ValueError:
        return "<invalid>"


def _webrtc_session_resource_id(session: _NativeWebRTCSession) -> str | None:
    """Return a shared media resource id for grouped session maintenance."""

    resource_id = getattr(session.player, "resource_id", None)
    if not isinstance(resource_id, str) or not resource_id:
        return None
    return resource_id


def _webrtc_session_peer_closed(session: _NativeWebRTCSession) -> bool:
    return _webrtc_session_peer_closed_impl(session)


@callback
def async_register_home_call_ws(hass: HomeAssistant) -> None:
    """Register Home Call audio WebRTC websocket commands."""

    _async_register_home_call_ws(hass, C300XDoorbellCamera)
