"""Camera entity for the C300X doorbell native WebRTC stream."""

from __future__ import annotations

import asyncio
import importlib
import time
import warnings
from collections.abc import Mapping
from contextlib import suppress
from types import SimpleNamespace
from typing import Any

from homeassistant.components.camera import (
    Camera,
    CameraEntityFeature,
    WebRTCAnswer,
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
    _new_restarting_rtsp_audio_track,
    _new_restarting_rtsp_tracks,
    _new_restarting_rtsp_video_track,
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
    async_wait_for_ice_gathering as _async_wait_for_ice_gathering,
)
from .camera_media.webrtc_session import (
    filter_link_local_sdp_candidates as _filter_link_local_sdp_candidates,
)
from .camera_media.webrtc_session import (
    prefer_webrtc_codecs as _prefer_webrtc_codecs,
)
from .camera_media.webrtc_session import (
    rtc_candidate_from_message as _rtc_candidate_from_message,
)
from .camera_media.webrtc_session import (
    webrtc_server_configuration as _webrtc_server_configuration,
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
STILL_IMAGE_CONTENT_TYPE = "image/svg+xml"
STILL_IMAGE_BYTES = b"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360"><rect width="640" height="360" fill="#111820"/><g fill="none" stroke="#8da2b5" stroke-width="16" stroke-linecap="round" stroke-linejoin="round"><path d="M216 152h178v96H216z"/><path d="M394 180l82-46v132l-82-46z"/><path d="M250 152l-32-56h174l-32 56"/><path d="M305 248v48"/><path d="M250 296h142"/></g></svg>"""

_AIORTC_MODULES: SimpleNamespace | None = None
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
        from aiortc.contrib.media import MediaPlayer
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
        self._webrtc_session_registry = _NativeWebRTCSessionRegistry(
            self._webrtc_sessions
        )
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
        """Return the RTSP source HA expects while native WebRTC remains preferred."""

        return await self._async_prepare_rtsp_stream()

    async def async_handle_async_webrtc_offer(
        self,
        offer_sdp: str,
        session_id: str,
        send_message: WebRTCSendMessage,
    ) -> None:
        """Handle native WebRTC offers directly."""

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
        """Handle an audio-only Home Call WebRTC offer."""

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
        """Handle a native WebRTC offer for doorbell video or Home Call audio."""

        try:
            aiortc_modules = await self._async_load_aiortc_modules()
        except ImportError as err:
            send_message(
                WebRTCError("bticino_webrtc_unavailable", "aiortc is not installed")
            )
            raise HomeAssistantError("aiortc is not installed") from err

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

        if session_id in self._webrtc_sessions:
            await self._async_close_webrtc_session(session_id)

        peer = aiortc_modules.RTCPeerConnection(
            configuration=_webrtc_server_configuration(
                aiortc_modules,
                getattr(self, "async_get_webrtc_client_configuration", None),
            )
        )
        session = _NativeWebRTCSession(peer, owner=owner, send_message=send_message)
        session.talkback_requested = talkback_requested
        self._webrtc_sessions[session_id] = session

        @peer.on("connectionstatechange")
        async def _on_connectionstatechange() -> None:
            if peer.connectionState in {"failed", "closed", "disconnected"}:
                await self._async_close_webrtc_session(session_id)

        @peer.on("track")
        def _on_remote_track(track: Any) -> None:
            if track.kind != "audio":
                return
            if session.talkback_task is not None:
                session.talkback_task.cancel()
            session.talkback_task = self.hass.async_create_task(
                self._async_forward_talkback_audio(
                    track,
                    aiortc_modules,
                    session_id,
                )
            )

        try:
            async def _restart_reader() -> bool | None:
                current_session = self._webrtc_sessions.get(session_id)
                if current_session is None:
                    return False
                if current_session.ring_preview:
                    status = await self._async_refresh_video_status_or_none(
                        apply_status=False
                    )
                    decision = (
                        self._derive_media_decision(status)
                        if status is not None
                        else self._last_media_decision
                    )
                    if not _media_decision_is_unanswered_ring(decision):
                        current_session.ring_preview = False
                        return False
                if owner == "home_call":
                    await self._async_restart_home_call_reader()
                else:
                    await self._async_restart_video_reader(audio=wants_audio)
                return None

            if owner == "home_call":
                await self._entry.runtime_data.api.async_start_home_call(
                    duration_seconds=duration_seconds
                )
                stream_url = await self._async_prepare_home_call_rtsp_stream()
                home_call_audio_only = True
            else:
                stream_url = await self._async_prepare_rtsp_stream(audio=wants_audio)
                decision = self._last_media_decision
                session.ring_call = _media_decision_is_ring_call(decision)
                home_call_audio_only = wants_audio and _media_decision_is_home_call(
                    decision
                )
                session.ring_preview = _media_decision_is_unanswered_ring(decision)

            if home_call_audio_only:
                audio_track = _new_restarting_rtsp_audio_track(
                    aiortc_modules.AudioStreamTrack,
                    aiortc_modules.MediaStreamError,
                    aiortc_modules.MediaPlayer,
                    self.hass,
                    stream_url,
                    _restart_reader,
                    av_module=getattr(aiortc_modules, "av", None),
                    audio_gain_db=self._doorstation_audio_gain_db(),
                )
                session.player = audio_track
                peer.addTrack(audio_track)
            elif wants_audio:
                media, video_track, audio_track = _new_restarting_rtsp_tracks(
                    aiortc_modules.av,
                    aiortc_modules.VideoStreamTrack,
                    aiortc_modules.AudioStreamTrack,
                    aiortc_modules.MediaStreamError,
                    aiortc_modules.MediaPlayer,
                    self.hass,
                    stream_url,
                    _restart_reader,
                    audio_gain_db=self._doorstation_audio_gain_db(),
                )
                session.player = media
                peer.addTrack(video_track)
                peer.addTrack(audio_track)
            else:
                video_track = _new_restarting_rtsp_video_track(
                    aiortc_modules.VideoStreamTrack,
                    aiortc_modules.MediaStreamError,
                    aiortc_modules.MediaPlayer,
                    self.hass,
                    stream_url,
                    _restart_reader,
                )
                session.player = video_track
                peer.addTrack(video_track)
            _prefer_webrtc_codecs(peer, aiortc_modules)
            await peer.setRemoteDescription(
                aiortc_modules.RTCSessionDescription(sdp=offer_sdp, type="offer")
            )
            answer = await peer.createAnswer()
            await peer.setLocalDescription(answer)
            await _async_wait_for_ice_gathering(peer)
            send_message(
                WebRTCAnswer(
                    _filter_link_local_sdp_candidates(peer.localDescription.sdp)
                )
            )
            self._schedule_pending_webrtc_candidate_flush(session_id)
            session.renew_task = self.hass.async_create_task(
                self._async_renew_webrtc_until_closed(session_id)
            )
        except Exception as err:
            send_message(WebRTCError("bticino_webrtc_offer_failed", str(err)))
            await self._async_close_webrtc_session(session_id)

    async def async_on_webrtc_candidate(self, session_id: str, candidate: Any) -> None:
        """Forward browser ICE candidates to the native WebRTC peer."""

        session = self._webrtc_sessions.get(session_id)
        if session is None:
            return

        try:
            aiortc_modules = await self._async_load_aiortc_modules()
        except ImportError:
            return

        rtc_candidate = _rtc_candidate_from_message(aiortc_modules, candidate)

        if getattr(session.peer, "remoteDescription", None) is None:
            session.pending_ice_candidates.append(rtc_candidate)
            return

        await session.peer.addIceCandidate(rtc_candidate)

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

        for session_id in self._webrtc_session_registry.session_ids():
            await self._async_close_webrtc_session(session_id)
        with suppress(Exception):
            await self._entry.runtime_data.api.async_stop_doorbell_video()

    async def _async_close_webrtc_session(
        self,
        session_id: str,
        *,
        stop_media: bool = True,
        force_stop_media: bool = False,
        notify_client: bool = False,
        reason: str = "closed",
    ) -> None:
        session = await self._webrtc_session_registry.async_close_session_resources(
            session_id,
            notify_client=notify_client,
            reason=reason,
        )
        if session is None:
            return

        if session.ring_preview:
            with suppress(Exception):
                session.ring_preview = _media_decision_is_unanswered_ring(
                    self._derive_media_decision(
                        await self._async_refresh_video_status(apply_status=False)
                    )
                )

        if (
            not self._webrtc_session_registry.has_sessions()
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

        session_ids = self._webrtc_session_registry.session_ids_by_owner("home_call")
        if not session_ids:
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
            session = self._webrtc_sessions.get(session_id)
            if session is None:
                return
            if _webrtc_session_peer_closed(session):
                await self._async_close_webrtc_session(
                    session_id,
                    notify_client=True,
                    reason="webrtc_closed",
                )
                continue
            if session.owner == "home_call":
                try:
                    home_call_status = await self._entry.runtime_data.api.async_home_call_status()
                except Exception:  # noqa: BLE001 - transient status errors must not tear down active calls
                    continue
                if not _home_call_status_has_media(home_call_status):
                    self._apply_home_call_ended(dict(home_call_status))
                    await self._async_close_webrtc_session(
                        session_id,
                        stop_media=False,
                        notify_client=True,
                        reason="home_call_ended",
                    )
                    continue
                continue
            with suppress(Exception):
                decision = self._derive_media_decision(
                    await self._async_refresh_video_status(apply_status=False)
                )
                if _media_decision_is_call_media(decision):
                    continue
                if not decision.webrtc_keepalive_allowed:
                    await self._async_close_webrtc_session(
                        session_id,
                        stop_media=False,
                        notify_client=True,
                        reason=f"media_state_{decision.state.value}",
                    )
                    continue
            if session.ring_call:
                await self._async_close_webrtc_session(
                    session_id,
                    stop_media=False,
                    notify_client=True,
                    reason="ring_call_closed",
                )
                continue
            with suppress(Exception):
                await self._async_warmup_video()

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

        session_ids = self._webrtc_session_registry.session_ids_by_owner("home_call")
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

        session_ids = self._webrtc_session_registry.session_ids_for_ring_call()
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
        return self._webrtc_session_registry.active_media_sessions()


def _home_call_status_has_media(status: Mapping[str, Any]) -> bool:
    """Return true while the agent reports an active Home Call media path."""

    return bool(
        status.get("running")
        or status.get("active")
        or status.get("answered")
        or status.get("rtp_proxy")
        or status.get("target_audio_port")
    )


def _webrtc_session_peer_closed(session: _NativeWebRTCSession) -> bool:
    return _webrtc_session_peer_closed_impl(session)


@callback
def async_register_home_call_ws(hass: HomeAssistant) -> None:
    """Register Home Call audio WebRTC websocket commands."""

    _async_register_home_call_ws(hass, C300XDoorbellCamera)
