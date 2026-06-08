"""Camera entity for the C300X doorbell native WebRTC stream."""

from __future__ import annotations

import asyncio
import importlib
import ipaddress
import random
import socket
import struct
import warnings
from contextlib import suppress
from fractions import Fraction
from functools import partial
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
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from propcache.api import cached_property

from .const import (
    CONF_AGENT_HOST,
    CONF_VIDEO_PORT,
    CONF_VIDEO_STREAM_PATH,
    DEFAULT_VIDEO_PORT,
    DEFAULT_VIDEO_STREAM_PATH,
    EVENT_AGENT_EVENT_RECEIVED,
    MAX_HOME_CALL_DURATION_SECONDS,
)
from .device_user import media_user_attribute
from .entity import C300XEntity, entry_config_value, supports_capability
from .event_payload import agent_event_key
from .video import (
    doorbell_camera_unique_id,
    optional_string,
)

PARALLEL_UPDATES = 0
VIDEO_WINDOW_EVENTS = {"doorbell_pressed", "doorbell_view_requested"}
VIDEO_WINDOW_CLOSED_EVENTS = {"doorbell_media_closed"}
HOME_CALL_EVENTS = {"home_call_started", "home_call_answered", "home_call_ended"}
RTSP_FRAME_TIMEOUT_SECONDS = 5.0
RTSP_READY_CONNECT_TIMEOUT_SECONDS = 1.0
RTSP_READY_INTERVAL_SECONDS = 0.25
RTSP_READY_TIMEOUT_SECONDS = 6.0
RTSP_FAILURE_COOLDOWN_SECONDS = 20.0
RTSP_MAX_SESSION_RESTARTS = 3
RING_CALL_WAIT_INTERVAL_SECONDS = 0.2
RING_CALL_WAIT_TIMEOUT_SECONDS = 4.0
WEBRTC_RENEW_SECONDS = 60
TALKBACK_RTP_PORT = 40004
TALKBACK_RTP_PAYLOAD_TYPE = 97
TALKBACK_SAMPLE_RATE = 8000
TALKBACK_CODEC = "speex/8000"
DOORSTATION_AUDIO_GAIN = 3.0
STILL_IMAGE_CONTENT_TYPE = "image/svg+xml"
STILL_IMAGE_BYTES = b"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360"><rect width="640" height="360" fill="#111820"/><g fill="none" stroke="#8da2b5" stroke-width="16" stroke-linecap="round" stroke-linejoin="round"><path d="M216 152h178v96H216z"/><path d="M394 180l82-46v132l-82-46z"/><path d="M250 152l-32-56h174l-32 56"/><path d="M305 248v48"/><path d="M250 296h142"/></g></svg>"""

_AIORTC_MODULES: SimpleNamespace | None = None
_MDNS_CACHE_FLUSH_BIT = 0x8000
_DNS_MDNS_RDATA_MODULES = (
    "dns.rdtypes.IN.A",
    "dns.rdtypes.IN.AAAA",
    "dns.rdtypes.IN.PTR",
    "dns.rdtypes.ANY.SRV",
    "dns.rdtypes.ANY.TXT",
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
        for rdtype in (dns_rdatatype.A, dns_rdatatype.AAAA):
            dns_rdata.get_rdata_class(mdns_rdclass, rdtype)


def _status_is_call_media_active(status: dict[str, Any]) -> bool:
    """Return true when the native bridge is already serving call media."""

    bridge = status.get("bridge") if isinstance(status.get("bridge"), dict) else {}
    owner = str(status.get("media_owner") or bridge.get("media_owner") or "").lower()
    return owner in {"ring", "home_call"} or bool(
        bridge.get("ring_call_active") or bridge.get("ring_media_active")
        or bridge.get("home_call_running") or bridge.get("home_call_active")
    )


def _status_is_external_media_active(status: dict[str, Any]) -> bool:
    """Return true while the native agent sees a non-HA doorbell media window."""

    bridge = status.get("bridge") if isinstance(status.get("bridge"), dict) else {}
    return bool(status.get("external_media_active") or bridge.get("external_media_active"))


def _status_is_home_call_media_active(status: dict[str, Any]) -> bool:
    """Return true when the native bridge is serving an audio-only home call."""

    bridge = status.get("bridge") if isinstance(status.get("bridge"), dict) else {}
    owner = str(status.get("media_owner") or bridge.get("media_owner") or "").lower()
    return owner == "home_call" or bool(
        bridge.get("home_call_running") or bridge.get("home_call_active")
    )


def _home_call_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = data.get("home_call")
    if isinstance(payload, dict):
        return payload
    nested = data.get("data")
    if isinstance(nested, dict):
        payload = nested.get("home_call")
        if isinstance(payload, dict):
            return payload
        return nested
    return {}


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


class _NativeWebRTCSession:
    """Runtime resources for one native WebRTC session."""

    def __init__(
        self,
        peer: Any,
        *,
        owner: str = "doorbell",
        send_message: WebRTCSendMessage | None = None,
    ) -> None:
        self.peer = peer
        self.owner = owner
        self.send_message = send_message
        self.player: Any | None = None
        self.ice_flush_task: asyncio.Task | None = None
        self.renew_task: asyncio.Task | None = None
        self.talkback_task: asyncio.Task | None = None
        self.talkback_requested = False
        self.ring_preview = False
        self.talkback_active = False
        self.talkback_packets_sent = 0
        self.pending_ice_candidates: list[Any | None] = []


def _new_restarting_rtsp_tracks(
    av_module: Any,
    video_stream_track_cls: Any,
    audio_stream_track_cls: Any,
    media_stream_error_cls: type[Exception],
    media_player_cls: Any,
    hass: HomeAssistant,
    stream_url: str,
    restart_callback: Any,
) -> tuple[Any, Any, Any]:
    """Create shared audio/video tracks over one C300X RTSP reader."""

    class RestartingRTSPMedia:
        def __init__(self) -> None:
            self._player: Any | None = None
            self._video_track: Any | None = None
            self._audio_track: Any | None = None
            self._opened_once = False
            self._restart_pending = False
            self._restart_attempts = 0
            self._retry_delay = 0.2
            self._stopped = False
            self._lock = asyncio.Lock()

        async def recv(self, kind: str) -> Any:
            while not self._stopped:
                had_reader = self._player is not None
                try:
                    await self._ensure_reader()
                    track = self._video_track if kind == "video" else self._audio_track
                    if track is None:
                        raise media_stream_error_cls
                    frame = await asyncio.wait_for(
                        track.recv(),
                        timeout=RTSP_FRAME_TIMEOUT_SECONDS,
                    )
                    self._restart_attempts = 0
                    self._retry_delay = 0.2
                    return frame
                except Exception:
                    if had_reader and self._opened_once:
                        self._restart_pending = True
                    await self._async_close_reader()
                    await asyncio.sleep(self._retry_delay)
                    self._retry_delay = min(self._retry_delay * 2, 2.0)

            raise media_stream_error_cls

        async def _ensure_reader(self) -> None:
            if self._player is not None:
                return

            async with self._lock:
                if self._player is not None:
                    return
                await self._async_open_reader()

        async def _async_open_reader(self) -> None:
            await self._async_close_reader()
            if self._restart_pending:
                self._restart_pending = False
                if self._restart_attempts >= RTSP_MAX_SESSION_RESTARTS:
                    raise media_stream_error_cls
                self._restart_attempts += 1
                await restart_callback()
            self._opened_once = True
            player = await hass.async_add_executor_job(
                lambda: media_player_cls(
                    stream_url,
                    options={
                        "rtsp_transport": "tcp",
                        "timeout": "5000000",
                        "fflags": "nobuffer",
                        "flags": "low_delay",
                        "probesize": "32768",
                        "analyzeduration": "0",
                    },
                )
            )
            if player.video is None or player.audio is None:
                with suppress(Exception):
                    if player.video is not None:
                        player.video.stop()
                with suppress(Exception):
                    if player.audio is not None:
                        player.audio.stop()
                raise media_stream_error_cls

            self._player = player
            self._video_track = player.video
            self._audio_track = player.audio

        async def _async_close_reader(self) -> None:
            self._close_reader_sync()

        def _close_reader_sync(self) -> None:
            video_track = self._video_track
            audio_track = self._audio_track
            self._player = None
            self._video_track = None
            self._audio_track = None

            with suppress(Exception):
                if video_track is not None:
                    video_track.stop()
            with suppress(Exception):
                if audio_track is not None:
                    audio_track.stop()

        def stop(self) -> None:
            self._stopped = True
            self._close_reader_sync()

    media = RestartingRTSPMedia()

    class RestartingRTSPVideoTrack(video_stream_track_cls):
        kind = "video"

        async def recv(self) -> Any:
            frame = await media.recv("video")
            frame.pts, frame.time_base = await self.next_timestamp()
            return frame

        def stop(self) -> None:
            media.stop()
            super().stop()

    class RestartingRTSPAudioTrack(audio_stream_track_cls):
        kind = "audio"

        async def recv(self) -> Any:
            return _apply_audio_gain(
                av_module,
                await media.recv("audio"),
                DOORSTATION_AUDIO_GAIN,
            )

        def stop(self) -> None:
            media.stop()
            super().stop()

    return media, RestartingRTSPVideoTrack(), RestartingRTSPAudioTrack()


def _apply_audio_gain(av_module: Any, frame: Any, gain: float) -> Any:
    """Boost decoded doorstation audio before HA sends it through WebRTC."""

    if gain <= 1:
        return frame
    try:
        import numpy as np

        samples = frame.to_ndarray()
        if np.issubdtype(samples.dtype, np.integer):
            limits = np.iinfo(samples.dtype)
            boosted = np.clip(
                samples.astype(np.float32) * gain,
                limits.min,
                limits.max,
            ).astype(samples.dtype)
        else:
            boosted = np.clip(samples * gain, -1.0, 1.0).astype(samples.dtype)

        boosted_frame = av_module.AudioFrame.from_ndarray(
            boosted,
            format=frame.format.name,
            layout=frame.layout.name,
        )
        boosted_frame.sample_rate = frame.sample_rate
        boosted_frame.pts = frame.pts
        boosted_frame.time_base = frame.time_base
        return boosted_frame
    except Exception:
        return frame


def _new_restarting_rtsp_video_track(
    video_stream_track_cls: Any,
    media_stream_error_cls: type[Exception],
    media_player_cls: Any,
    hass: HomeAssistant,
    stream_url: str,
    restart_callback: Any,
) -> Any:
    """Create the proven video-only RTSP track for the C300X bridge."""

    class RestartingRTSPVideoTrack(video_stream_track_cls):
        kind = "video"

        def __init__(self) -> None:
            super().__init__()
            self._player: Any | None = None
            self._track: Any | None = None
            self._opened_once = False
            self._restart_pending = False
            self._restart_attempts = 0
            self._retry_delay = 0.2
            self._stopped = False
            self._lock = asyncio.Lock()

        async def recv(self) -> Any:
            while not self._stopped:
                had_reader = self._track is not None
                try:
                    await self._ensure_reader()
                    frame = await asyncio.wait_for(
                        self._track.recv(),
                        timeout=RTSP_FRAME_TIMEOUT_SECONDS,
                    )
                    frame.pts, frame.time_base = await self.next_timestamp()
                    self._restart_attempts = 0
                    self._retry_delay = 0.2
                    return frame
                except Exception:
                    if had_reader and self._opened_once:
                        self._restart_pending = True
                    await self._async_close_reader()
                    await asyncio.sleep(self._retry_delay)
                    self._retry_delay = min(self._retry_delay * 2, 2.0)

            raise media_stream_error_cls

        async def _ensure_reader(self) -> None:
            if self._track is not None:
                return

            async with self._lock:
                if self._track is not None:
                    return
                await self._async_open_reader()

        async def _async_open_reader(self) -> None:
            await self._async_close_reader()
            if self._restart_pending:
                self._restart_pending = False
                if self._restart_attempts >= RTSP_MAX_SESSION_RESTARTS:
                    raise media_stream_error_cls
                self._restart_attempts += 1
                await restart_callback()
            self._opened_once = True
            player = await hass.async_add_executor_job(
                lambda: media_player_cls(
                    stream_url,
                    options={
                        "rtsp_transport": "tcp",
                        "timeout": "5000000",
                        "fflags": "nobuffer",
                        "flags": "low_delay",
                        "probesize": "32768",
                        "analyzeduration": "0",
                    },
                )
            )
            if player.video is None:
                with suppress(Exception):
                    if player.audio is not None:
                        player.audio.stop()
                raise media_stream_error_cls

            self._player = player
            self._track = player.video

        async def _async_close_reader(self) -> None:
            player = self._player
            track = self._track
            self._player = None
            self._track = None

            with suppress(Exception):
                if track is not None:
                    track.stop()
            with suppress(Exception):
                if player is not None and player.audio is not None:
                    player.audio.stop()

        def stop(self) -> None:
            self._stopped = True
            player = self._player
            track = self._track
            self._player = None
            self._track = None
            with suppress(Exception):
                if track is not None:
                    track.stop()
            with suppress(Exception):
                if player is not None and player.audio is not None:
                    player.audio.stop()
            super().stop()

    return RestartingRTSPVideoTrack()


def _new_restarting_rtsp_audio_track(
    audio_stream_track_cls: Any,
    media_stream_error_cls: type[Exception],
    media_player_cls: Any,
    hass: HomeAssistant,
    stream_url: str,
    restart_callback: Any,
) -> Any:
    """Create an audio-only RTSP track for app-style Home Call media."""

    class RestartingRTSPAudioTrack(audio_stream_track_cls):
        kind = "audio"

        def __init__(self) -> None:
            super().__init__()
            self._player: Any | None = None
            self._track: Any | None = None
            self._opened_once = False
            self._restart_pending = False
            self._restart_attempts = 0
            self._retry_delay = 0.2
            self._stopped = False
            self._lock = asyncio.Lock()

        async def recv(self) -> Any:
            while not self._stopped:
                had_reader = self._track is not None
                try:
                    await self._ensure_reader()
                    frame = await asyncio.wait_for(
                        self._track.recv(),
                        timeout=RTSP_FRAME_TIMEOUT_SECONDS,
                    )
                    self._restart_attempts = 0
                    self._retry_delay = 0.2
                    return frame
                except Exception:
                    if had_reader and self._opened_once:
                        self._restart_pending = True
                    await self._async_close_reader()
                    await asyncio.sleep(self._retry_delay)
                    self._retry_delay = min(self._retry_delay * 2, 2.0)

            raise media_stream_error_cls

        async def _ensure_reader(self) -> None:
            if self._track is not None:
                return

            async with self._lock:
                if self._track is not None:
                    return
                await self._async_open_reader()

        async def _async_open_reader(self) -> None:
            await self._async_close_reader()
            if self._restart_pending:
                self._restart_pending = False
                if self._restart_attempts >= RTSP_MAX_SESSION_RESTARTS:
                    raise media_stream_error_cls
                self._restart_attempts += 1
                await restart_callback()
            self._opened_once = True
            player = await hass.async_add_executor_job(
                lambda: media_player_cls(
                    stream_url,
                    options={
                        "rtsp_transport": "tcp",
                        "timeout": "5000000",
                        "fflags": "nobuffer",
                        "flags": "low_delay",
                        "probesize": "32768",
                        "analyzeduration": "0",
                    },
                )
            )
            if player.audio is None:
                with suppress(Exception):
                    if player.video is not None:
                        player.video.stop()
                raise media_stream_error_cls

            with suppress(Exception):
                if player.video is not None:
                    player.video.stop()
            self._player = player
            self._track = player.audio

        async def _async_close_reader(self) -> None:
            player = self._player
            track = self._track
            self._player = None
            self._track = None
            with suppress(Exception):
                if track is not None:
                    track.stop()
            with suppress(Exception):
                if player is not None and player.video is not None:
                    player.video.stop()

        def stop(self) -> None:
            self._stopped = True
            player = self._player
            track = self._track
            self._player = None
            self._track = None
            with suppress(Exception):
                if track is not None:
                    track.stop()
            with suppress(Exception):
                if player is not None and player.video is not None:
                    player.video.stop()
            super().stop()

    return RestartingRTSPAudioTrack()


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
        self._rtsp_prepare_lock = asyncio.Lock()
        self._rtsp_ready_lock = asyncio.Lock()
        self._rtsp_unavailable_until = 0.0
        self._last_rtsp_error: str | None = None
        self._talkback_last_error: str | None = None
        self._webrtc_sessions: dict[str, _NativeWebRTCSession] = {}
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

        has_audio_media = self._offer_has_audio(offer_sdp)
        talkback_requested = self._offer_can_send_microphone(offer_sdp)
        wants_audio = has_audio_media and self._offer_should_use_audio_stream(offer_sdp)
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
            configuration=self._webrtc_server_configuration(aiortc_modules)
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
            async def _restart_reader() -> None:
                if owner == "home_call":
                    await self._async_restart_home_call_reader()
                else:
                    await self._async_restart_video_reader(audio=wants_audio)

            if owner == "home_call":
                await self._entry.runtime_data.api.async_start_home_call(
                    duration_seconds=duration_seconds
                )
                stream_url = await self._async_prepare_home_call_rtsp_stream()
                home_call_audio_only = True
            else:
                stream_url = await self._async_prepare_rtsp_stream(audio=wants_audio)
                home_call_audio_only = wants_audio and _status_is_home_call_media_active(
                    {
                        "media_owner": self._video_owner,
                        "bridge": self._bridge_status,
                    }
                )
                session.ring_preview = (
                    not wants_audio
                    and self._video_owner == "ring"
                    and bool(self._bridge_status.get("ring_call_active"))
                )

            if home_call_audio_only:
                audio_track = _new_restarting_rtsp_audio_track(
                    aiortc_modules.AudioStreamTrack,
                    aiortc_modules.MediaStreamError,
                    aiortc_modules.MediaPlayer,
                    self.hass,
                    stream_url,
                    _restart_reader,
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
            self._prefer_webrtc_codecs(peer, aiortc_modules)
            await peer.setRemoteDescription(
                aiortc_modules.RTCSessionDescription(sdp=offer_sdp, type="offer")
            )
            answer = await peer.createAnswer()
            await peer.setLocalDescription(answer)
            await self._async_wait_for_ice_gathering(peer)
            send_message(WebRTCAnswer(_filter_link_local_sdp_candidates(peer.localDescription.sdp)))
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

        candidate_dict = candidate.to_dict() if hasattr(candidate, "to_dict") else {}
        candidate_sdp = str(
            candidate_dict.get("candidate")
            or getattr(candidate, "candidate", "")
            or ""
        )
        if not candidate_sdp:
            rtc_candidate = None
        else:
            if candidate_sdp.startswith("candidate:"):
                candidate_sdp = candidate_sdp[len("candidate:") :]

            rtc_candidate = aiortc_modules.candidate_from_sdp(candidate_sdp)
            sdp_mid = candidate_dict.get("sdpMid")
            if sdp_mid is None:
                sdp_mid = getattr(candidate, "sdpMid", None)
            sdp_mline_index = candidate_dict.get("sdpMLineIndex")
            if sdp_mline_index is None:
                sdp_mline_index = getattr(candidate, "sdpMLineIndex", None)
            rtc_candidate.sdpMid = sdp_mid
            rtc_candidate.sdpMLineIndex = sdp_mline_index

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
            if getattr(session.peer, "remoteDescription", None) is None:
                return
            while session.pending_ice_candidates:
                await session.peer.addIceCandidate(session.pending_ice_candidates.pop(0))
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

        for session_id in list(self._webrtc_sessions):
            await self._async_close_webrtc_session(session_id)
        with suppress(Exception):
            await self._entry.runtime_data.api.async_stop_doorbell_video()

    async def _async_close_webrtc_session(
        self,
        session_id: str,
        *,
        stop_media: bool = True,
        notify_client: bool = False,
        reason: str = "closed",
    ) -> None:
        session = self._webrtc_sessions.pop(session_id, None)
        if session is None:
            return

        if session.renew_task is not None and session.renew_task is not asyncio.current_task():
            session.renew_task.cancel()
            session.renew_task = None
        if (
            session.ice_flush_task is not None
            and session.ice_flush_task is not asyncio.current_task()
        ):
            session.ice_flush_task.cancel()
            session.ice_flush_task = None
        if session.talkback_task is not None and session.talkback_task is not asyncio.current_task():
            session.talkback_task.cancel()
            session.talkback_task = None
        if session.player is not None:
            with suppress(Exception):
                session.player.stop()
        if notify_client and session.send_message is not None:
            with suppress(Exception):
                session.send_message({"type": "closed", "reason": reason})
        with suppress(Exception):
            await session.peer.close()

        if not self._webrtc_sessions and stop_media and not session.ring_preview:
            if session.owner == "home_call":
                with suppress(Exception):
                    await self._entry.runtime_data.api.async_stop_home_call()
            else:
                with suppress(Exception):
                    await self._entry.runtime_data.api.async_stop_doorbell_video()

    async def _async_warmup_video(self, *, audio: bool = False) -> None:
        """Mark the video window and refresh bridge metadata before RTSP opens."""

        try:
            await self._entry.runtime_data.api.async_activate_doorbell_video(audio=audio)
        except Exception:  # noqa: BLE001 - refresh status before re-raising API failure
            with suppress(Exception):
                await self._async_refresh_video_status()
                self._async_write_ha_state_if_ready()
            raise
        with suppress(Exception):
            await self._async_refresh_video_status()

    async def _async_restart_video_reader(self, *, audio: bool = False) -> None:
        async with self._rtsp_prepare_lock:
            status = await self._async_refresh_video_status_or_none()
            if status is not None and _status_is_call_media_active(status):
                await self._async_wait_for_rtsp_ready(self._build_stream_url(audio=audio))
                return
            if status is not None and _status_is_external_media_active(status):
                status = await self._async_wait_for_call_media_after_external_event(status)
                if status is not None and _status_is_call_media_active(status):
                    await self._async_wait_for_rtsp_ready(self._build_stream_url(audio=audio))
                    return
            await self._entry.runtime_data.api.async_stop_doorbell_video()
            await asyncio.sleep(1.0)
            await self._async_warmup_video(audio=audio)
            await self._async_wait_for_rtsp_ready(self._build_stream_url(audio=audio))

    async def _async_restart_home_call_reader(self) -> None:
        async with self._rtsp_prepare_lock:
            await self._async_wait_for_home_call_active()
            await self._async_wait_for_rtsp_ready(self._build_stream_url(audio=True))

    async def _async_prepare_rtsp_stream(self, *, audio: bool = False) -> str:
        """Activate video and return a URL only after RTSP answers."""

        async with self._rtsp_prepare_lock:
            self._raise_if_rtsp_cooling_down()
            status = await self._async_refresh_video_status_or_none()
            if status is not None and _status_is_external_media_active(status):
                status = await self._async_wait_for_call_media_after_external_event(status)
            if status is None or not _status_is_call_media_active(status):
                await self._async_warmup_video(audio=audio)
            stream_url = self._build_stream_url(audio=audio)
            await self._async_wait_for_rtsp_ready(stream_url)
            return stream_url

    async def _async_wait_for_call_media_after_external_event(
        self,
        status: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Wait for a real SIP ring call after an OpenWebNet doorbell event."""

        if _status_is_call_media_active(status) or not _status_is_external_media_active(status):
            return status

        loop = asyncio.get_running_loop()
        deadline = loop.time() + RING_CALL_WAIT_TIMEOUT_SECONDS
        current: dict[str, Any] | None = status
        while loop.time() < deadline:
            await asyncio.sleep(RING_CALL_WAIT_INTERVAL_SECONDS)
            refreshed = await self._async_refresh_video_status_or_none()
            if refreshed is None:
                continue
            current = refreshed
            if _status_is_call_media_active(refreshed) or not _status_is_external_media_active(refreshed):
                return refreshed
        return current

    async def _async_prepare_home_call_rtsp_stream(self) -> str:
        """Return the audio-only RTSP source for an active Home Call."""

        async with self._rtsp_prepare_lock:
            self._raise_if_rtsp_cooling_down()
            await self._async_wait_for_home_call_active()
            stream_url = self._build_stream_url(audio=True)
            await self._async_wait_for_rtsp_ready(stream_url)
            return stream_url

    async def _async_wait_for_home_call_active(
        self,
        *,
        apply_status: bool = True,
    ) -> dict[str, Any]:
        """Wait until the native agent reports the Home Call media as active."""

        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(RTSP_READY_TIMEOUT_SECONDS, 20.0)
        last_status: dict[str, Any] = {}
        while True:
            with suppress(Exception):
                status = await self._entry.runtime_data.api.async_home_call_status()
                last_status = status
                if (
                    status.get("answered")
                    or status.get("rtp_proxy")
                    or status.get("target_audio_port")
                ):
                    if apply_status:
                        self._apply_home_call_status(status)
                    return status
            if loop.time() >= deadline:
                last_error = last_status.get("last_error") if last_status else None
                raise HomeAssistantError(
                    f"C300X Home Call did not become active: {last_error or last_status}"
                )
            await asyncio.sleep(RTSP_READY_INTERVAL_SECONDS)

    def _apply_home_call_status(self, status: dict[str, Any]) -> None:
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

        self._raise_if_rtsp_cooling_down()
        async with self._rtsp_ready_lock:
            self._raise_if_rtsp_cooling_down()
            loop = asyncio.get_running_loop()
            deadline = loop.time() + RTSP_READY_TIMEOUT_SECONDS
            last_error: Exception | None = None
            while True:
                try:
                    await self._async_probe_rtsp(stream_url)
                except Exception as err:  # noqa: BLE001 - probe errors become HA errors
                    last_error = err
                else:
                    self._last_rtsp_error = None
                    self._rtsp_unavailable_until = 0.0
                    return

                if loop.time() >= deadline:
                    self._last_rtsp_error = (
                        type(last_error).__name__ if last_error else "timeout"
                    )
                    self._rtsp_unavailable_until = (
                        loop.time() + RTSP_FAILURE_COOLDOWN_SECONDS
                    )
                    raise HomeAssistantError(
                        f"C300X RTSP bridge did not become ready: {last_error}"
                    ) from last_error
                await asyncio.sleep(RTSP_READY_INTERVAL_SECONDS)

    def _raise_if_rtsp_cooling_down(self) -> None:
        loop = asyncio.get_running_loop()
        if self._rtsp_unavailable_until > loop.time():
            raise HomeAssistantError(
                f"C300X RTSP bridge is cooling down after failure: {self._last_rtsp_error}"
            )

    async def _async_probe_rtsp(self, stream_url: str) -> None:
        """Open a lightweight RTSP OPTIONS request against the native bridge."""

        host = self._agent_host_for_socket()
        port = int(entry_config_value(self._entry, CONF_VIDEO_PORT, DEFAULT_VIDEO_PORT))
        reader: asyncio.StreamReader | None = None
        writer: asyncio.StreamWriter | None = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host=host, port=port),
                timeout=RTSP_READY_CONNECT_TIMEOUT_SECONDS,
            )
            request = (
                f"OPTIONS {stream_url} RTSP/1.0\r\n"
                "CSeq: 1\r\n"
                "User-Agent: HomeAssistant-BTicino-C300X\r\n"
                "\r\n"
            )
            writer.write(request.encode("ascii"))
            await asyncio.wait_for(
                writer.drain(),
                timeout=RTSP_READY_CONNECT_TIMEOUT_SECONDS,
            )
            response = await asyncio.wait_for(
                reader.read(64),
                timeout=RTSP_READY_CONNECT_TIMEOUT_SECONDS,
            )
            if not response.startswith(b"RTSP/1.0 "):
                raise HomeAssistantError("RTSP bridge returned a non-RTSP response")
        finally:
            if writer is not None:
                writer.close()
                with suppress(Exception):
                    await writer.wait_closed()

    async def _async_renew_webrtc_until_closed(self, session_id: str) -> None:
        while session_id in self._webrtc_sessions:
            await asyncio.sleep(WEBRTC_RENEW_SECONDS)
            session = self._webrtc_sessions.get(session_id)
            if session is None:
                return
            if session.owner == "home_call":
                with suppress(Exception):
                    await self._async_wait_for_home_call_active(apply_status=False)
                continue
            with suppress(Exception):
                if _status_is_call_media_active(
                    await self._async_refresh_video_status(apply_status=False)
                ):
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

    def _offer_has_audio(self, offer_sdp: str) -> bool:
        """Return whether the WebRTC offer contains an audio media section."""

        return self._offer_audio_section(offer_sdp) is not None

    def _offer_accepts_incoming_audio(self, offer_sdp: str) -> bool:
        """Return whether HA should add the doorbell audio track to the answer."""

        section = self._offer_audio_section(offer_sdp)
        if section is None:
            return False
        directions = self._offer_audio_directions(section)
        return "a=inactive" not in directions and "a=sendonly" not in directions

    def _offer_should_use_audio_stream(self, offer_sdp: str) -> bool:
        """Return whether HA should request doorbell audio for this offer."""

        return self._offer_accepts_incoming_audio(offer_sdp)

    def _offer_can_send_microphone(self, offer_sdp: str) -> bool:
        """Return whether the browser offer can send microphone audio to HA."""

        section = self._offer_audio_section(offer_sdp)
        if section is None:
            return False
        directions = self._offer_audio_directions(section)
        return "a=inactive" not in directions and "a=recvonly" not in directions

    def _offer_audio_directions(self, audio_section: str) -> set[str]:
        """Return SDP direction attributes from an audio media section."""

        return {
            line.strip()
            for line in audio_section.splitlines()
            if line.strip() in {"a=sendonly", "a=recvonly", "a=sendrecv", "a=inactive"}
        }

    def _offer_audio_section(self, offer_sdp: str) -> str | None:
        """Return the SDP audio media section from a WebRTC offer."""

        normalized = offer_sdp.replace("\r\n", "\n")
        sections = normalized.split("\nm=")
        for index, section in enumerate(sections):
            if index > 0:
                section = "m=" + section
            if section.startswith("m=audio "):
                return section
        return None

    async def _async_forward_talkback_audio(
        self,
        track: Any,
        aiortc_modules: SimpleNamespace,
        session_id: str,
    ) -> None:
        """Encode browser microphone audio as Speex/8k RTP for C300X talkback."""

        loop = asyncio.get_running_loop()
        host = self._agent_host_for_socket()
        if not host:
            self._set_talkback_error("agent_host_missing")
            return

        sock: socket.socket | None = None
        target: tuple[Any, ...] | None = None
        encoder: Any | None = None
        sequence = random.randrange(0, 65536)
        timestamp = random.randrange(0, 2**32)
        ssrc = random.randrange(1, 2**32)
        marker = True

        try:
            infos = await loop.getaddrinfo(
                host,
                TALKBACK_RTP_PORT,
                type=socket.SOCK_DGRAM,
            )
            family, socktype, proto, _canonname, target = infos[0]
            sock = socket.socket(family, socktype, proto)
            sock.setblocking(False)
            self._set_talkback_error(None)
            self._set_talkback_active(session_id, True)

            encoder = aiortc_modules.av.CodecContext.create("libspeex", "w")
            encoder.sample_rate = TALKBACK_SAMPLE_RATE
            encoder.layout = "mono"
            encoder.format = "s16"
            encoder.time_base = Fraction(1, TALKBACK_SAMPLE_RATE)
            encoder.bit_rate = 15000
            encoder.open()
            resampler = aiortc_modules.AudioResampler(
                format="s16",
                layout="mono",
                rate=TALKBACK_SAMPLE_RATE,
            )

            while True:
                frame = await track.recv()
                for resampled in resampler.resample(frame):
                    samples = max(1, int(getattr(resampled, "samples", 160) or 160))
                    for packet in encoder.encode(resampled):
                        payload = bytes(packet)
                        if not payload:
                            continue
                        rtp = self._build_talkback_rtp_packet(
                            payload,
                            sequence,
                            timestamp,
                            ssrc,
                            marker,
                        )
                        await loop.sock_sendto(sock, rtp, target)
                        self._increment_talkback_packets(session_id)
                        sequence = (sequence + 1) & 0xFFFF
                        timestamp = (
                            timestamp
                            + max(1, int(getattr(packet, "duration", None) or samples))
                        ) & 0xFFFFFFFF
                        marker = False
        except asyncio.CancelledError:
            raise
        except Exception as err:
            media_stream_error = getattr(aiortc_modules, "MediaStreamError", None)
            if media_stream_error is None or not isinstance(err, media_stream_error):
                self._set_talkback_error(type(err).__name__)
            return
        finally:
            if encoder is not None and sock is not None and target is not None:
                with suppress(Exception):
                    for packet in encoder.encode(None):
                        payload = bytes(packet)
                        if not payload:
                            continue
                        rtp = self._build_talkback_rtp_packet(
                            payload,
                            sequence,
                            timestamp,
                            ssrc,
                            marker,
                        )
                        await loop.sock_sendto(sock, rtp, target)
                        sequence = (sequence + 1) & 0xFFFF
                        timestamp = (
                            timestamp
                            + max(1, int(getattr(packet, "duration", None) or 160))
                        ) & 0xFFFFFFFF
                        marker = False
            if sock is not None:
                sock.close()
            self._set_talkback_active(session_id, False)

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

    def _build_talkback_rtp_packet(
        self,
        payload: bytes,
        sequence: int,
        timestamp: int,
        ssrc: int,
        marker: bool,
    ) -> bytes:
        marker_payload = TALKBACK_RTP_PAYLOAD_TYPE | (0x80 if marker else 0)
        header = struct.pack("!BBHII", 0x80, marker_payload, sequence, timestamp, ssrc)
        return header + payload

    async def _async_load_aiortc_modules(self) -> SimpleNamespace:
        return await self.hass.async_add_executor_job(_load_aiortc_modules)

    def _webrtc_server_configuration(self, aiortc_modules: SimpleNamespace) -> Any:
        """Mirror HA's WebRTC ICE servers into the server-side aiortc peer."""

        ice_servers = []
        get_client_config = getattr(self, "async_get_webrtc_client_configuration", None)
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

    def _prefer_webrtc_codecs(self, peer: Any, aiortc_modules: SimpleNamespace) -> None:
        self._prefer_h264(peer, aiortc_modules)
        self._prefer_browser_audio(peer, aiortc_modules)

    def _prefer_h264(self, peer: Any, aiortc_modules: SimpleNamespace) -> None:
        capabilities = aiortc_modules.RTCRtpSender.getCapabilities("video")
        h264_codecs = [
            codec
            for codec in capabilities.codecs
            if codec.mimeType.lower() == "video/h264"
        ]
        other_codecs = [
            codec
            for codec in capabilities.codecs
            if codec.mimeType.lower() != "video/h264"
        ]
        if not h264_codecs:
            return

        for transceiver in peer.getTransceivers():
            if transceiver.kind == "video":
                with suppress(Exception):
                    transceiver.setCodecPreferences([*h264_codecs, *other_codecs])

    def _prefer_browser_audio(self, peer: Any, aiortc_modules: SimpleNamespace) -> None:
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
                    transceiver.setCodecPreferences(
                        [*preferred_codecs, *other_codecs]
                    )

    async def _async_wait_for_ice_gathering(self, peer: Any) -> None:
        if peer.iceGatheringState == "complete":
            return

        done = asyncio.Event()

        @peer.on("icegatheringstatechange")
        def _on_icegatheringstatechange() -> None:
            if peer.iceGatheringState == "complete":
                done.set()

        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(done.wait(), timeout=1.0)

    def _agent_host(self) -> str:
        """Return the configured agent host without surrounding whitespace."""

        return str(entry_config_value(self._entry, CONF_AGENT_HOST, "")).strip()

    def _agent_host_for_socket(self) -> str:
        """Return the agent host in a form accepted by socket APIs."""

        host = self._agent_host()
        if host.startswith("[") and "]" in host:
            host = host[1 : host.index("]")]
        return host.replace("%25", "%")

    def _agent_host_for_url(self) -> str:
        """Return the agent host in a form accepted in RTSP URLs."""

        host = self._agent_host_for_socket()
        if ":" in host and not host.startswith("["):
            host = host.replace("%", "%25")
            return f"[{host}]"
        return host

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
        if path.startswith("rtsp://"):
            return path
        host = self._agent_host_for_url()
        port = int(entry_config_value(self._entry, CONF_VIDEO_PORT, DEFAULT_VIDEO_PORT))
        if not path.startswith("/"):
            path = f"/{path}"
        return f"rtsp://{host}:{port}{path}"

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

    async def async_added_to_hass(self) -> None:
        """Subscribe to runtime event-state updates."""

        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(
                EVENT_AGENT_EVENT_RECEIVED,
                self._handle_agent_event,
            )
        )

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

        session_ids = [
            session_id
            for session_id, session in self._webrtc_sessions.items()
            if session.owner == "home_call"
        ]
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
            "call_active": False,
        }

    def _async_write_ha_state_if_ready(self) -> None:
        if hasattr(self, "async_write_ha_state"):
            self.async_write_ha_state()


@callback
def async_register_home_call_ws(hass: HomeAssistant) -> None:
    """Register Home Call audio WebRTC websocket commands."""

    import voluptuous as vol
    from homeassistant.components import websocket_api
    from homeassistant.components.camera.helper import get_camera_from_entity_id
    from homeassistant.components.camera.webrtc import WebRTCSession
    from homeassistant.helpers import config_validation as cv
    from homeassistant.util.ulid import ulid

    def _home_call_camera(entity_id: str) -> C300XDoorbellCamera | None:
        camera = get_camera_from_entity_id(hass, entity_id)
        return camera if isinstance(camera, C300XDoorbellCamera) else None

    def _parse_candidate(value: Any) -> Any:
        if not isinstance(value, dict):
            raise vol.Invalid("candidate must be an object")
        return SimpleNamespace(
            candidate=str(value.get("candidate") or ""),
            sdpMid=value.get("sdpMid"),
            sdpMLineIndex=value.get("sdpMLineIndex"),
        )

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "bticino_c300x/home_call/webrtc/get_client_config",
            vol.Required("entity_id"): cv.entity_id,
        }
    )
    @websocket_api.async_response
    async def ws_home_call_get_client_config(
        _hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        camera = _home_call_camera(msg["entity_id"])
        if camera is None:
            connection.send_error(
                msg["id"],
                "home_call_webrtc_not_found",
                "C300X doorbell camera entity not found",
            )
            return
        connection.send_result(
            msg["id"],
            camera.async_get_webrtc_client_configuration().to_frontend_dict(),
        )

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "bticino_c300x/home_call/webrtc/offer",
            vol.Required("entity_id"): cv.entity_id,
            vol.Required("offer"): str,
            vol.Optional("duration_seconds"): vol.All(
                vol.Coerce(int),
                vol.Range(min=0, max=MAX_HOME_CALL_DURATION_SECONDS),
            ),
        }
    )
    @websocket_api.async_response
    async def ws_home_call_webrtc_offer(
        _hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        camera = _home_call_camera(msg["entity_id"])
        if camera is None:
            connection.send_error(
                msg["id"],
                "home_call_webrtc_not_found",
                "C300X doorbell camera entity not found",
            )
            return

        session_id = ulid()
        connection.subscriptions[msg["id"]] = partial(
            camera.close_webrtc_session,
            session_id,
        )
        connection.send_message(websocket_api.result_message(msg["id"]))

        @callback
        def send_message(message: Any) -> None:
            connection.send_message(
                websocket_api.event_message(
                    msg["id"],
                    message.as_dict() if hasattr(message, "as_dict") else message,
                )
            )

        send_message(WebRTCSession(session_id))
        try:
            await camera.async_handle_home_call_webrtc_offer(
                msg["offer"],
                session_id,
                send_message,
                duration_seconds=msg.get("duration_seconds"),
            )
        except HomeAssistantError as err:
            send_message(WebRTCError("home_call_webrtc_offer_failed", str(err)))

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "bticino_c300x/home_call/webrtc/candidate",
            vol.Required("entity_id"): cv.entity_id,
            vol.Required("session_id"): str,
            vol.Required("candidate"): _parse_candidate,
        }
    )
    @websocket_api.async_response
    async def ws_home_call_candidate(
        _hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        camera = _home_call_camera(msg["entity_id"])
        if camera is None:
            connection.send_error(
                msg["id"],
                "home_call_webrtc_not_found",
                "C300X doorbell camera entity not found",
            )
            return
        await camera.async_on_webrtc_candidate(msg["session_id"], msg["candidate"])
        connection.send_message(websocket_api.result_message(msg["id"]))

    websocket_api.async_register_command(hass, ws_home_call_get_client_config)
    websocket_api.async_register_command(hass, ws_home_call_webrtc_offer)
    websocket_api.async_register_command(hass, ws_home_call_candidate)


def _filter_link_local_sdp_candidates(sdp: str) -> str:
    """Drop link-local/.local ICE candidates when better candidates exist."""

    lines = sdp.splitlines()
    candidate_lines = [line for line in lines if line.startswith("a=candidate:")]
    if not candidate_lines:
        return sdp

    usable_candidates = [
        line for line in candidate_lines if not _candidate_is_link_local(line)
    ]
    if not usable_candidates:
        return sdp

    filtered = [
        line
        for line in lines
        if not line.startswith("a=candidate:") or not _candidate_is_link_local(line)
    ]
    line_ending = "\r\n" if "\r\n" in sdp else "\n"
    suffix = line_ending if sdp.endswith(("\r\n", "\n")) else ""
    return line_ending.join(filtered) + suffix


def _candidate_is_link_local(line: str) -> bool:
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
