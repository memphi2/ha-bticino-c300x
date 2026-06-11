from __future__ import annotations

import asyncio
import socket
import struct
import sys
import types
from contextlib import suppress
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

if "homeassistant.components.camera" not in sys.modules:
    homeassistant = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    camera = types.ModuleType("homeassistant.components.camera")
    stream = types.ModuleType("homeassistant.components.stream")
    config_entries = types.ModuleType("homeassistant.config_entries")
    core = types.ModuleType("homeassistant.core")
    exceptions = types.ModuleType("homeassistant.exceptions")
    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    helpers = types.ModuleType("homeassistant.helpers")
    config_validation = types.ModuleType("homeassistant.helpers.config_validation")
    dispatcher = types.ModuleType("homeassistant.helpers.dispatcher")
    entity = types.ModuleType("homeassistant.helpers.entity")
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    event = types.ModuleType("homeassistant.helpers.event")

    class Camera:  # pragma: no cover - import-time stub only
        pass

    class ConfigEntry:  # pragma: no cover - import-time stub only
        pass

    class HomeAssistant:  # pragma: no cover - import-time stub only
        pass

    class Entity:  # pragma: no cover - import-time stub only
        pass

    class DeviceInfo(dict):  # pragma: no cover - import-time stub only
        pass

    camera.Camera = Camera
    camera.CameraEntityFeature = types.SimpleNamespace(STREAM=1)
    camera.WebRTCAnswer = lambda sdp: {"type": "answer", "sdp": sdp}
    camera.WebRTCError = lambda code, message: {
        "type": "error",
        "code": code,
        "message": message,
    }
    camera.WebRTCSendMessage = object
    config_entries.ConfigEntry = ConfigEntry
    core.HomeAssistant = HomeAssistant
    core.callback = lambda func: func
    config_validation.config_entry_only_config_schema = lambda _domain: dict
    exceptions.HomeAssistantError = Exception
    entity.Entity = Entity
    entity.DeviceInfo = DeviceInfo
    dispatcher.async_dispatcher_connect = lambda *args, **kwargs: (lambda: None)
    dispatcher.async_dispatcher_send = (
        lambda hass, signal, entry_id: dispatcher_signals.append((signal, entry_id))
    )
    entity_registry.async_get = lambda hass: None
    event.async_call_later = lambda *args, **kwargs: (lambda: None)
    entity_platform.AddEntitiesCallback = object
    stream.CONF_RTSP_TRANSPORT = "rtsp_transport"
    stream.CONF_USE_WALLCLOCK_AS_TIMESTAMPS = "use_wallclock_as_timestamps"
    helpers.config_validation = config_validation
    helpers.event = event
    helpers.entity_registry = entity_registry
    sys.modules.setdefault("homeassistant", homeassistant)
    sys.modules["homeassistant.components"] = components
    sys.modules["homeassistant.components.camera"] = camera
    sys.modules["homeassistant.components.stream"] = stream
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.exceptions"] = exceptions
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.config_validation"] = config_validation
    sys.modules["homeassistant.helpers.dispatcher"] = dispatcher
    sys.modules["homeassistant.helpers.entity"] = entity
    sys.modules["homeassistant.helpers.entity_registry"] = entity_registry
    sys.modules["homeassistant.helpers.event"] = event
    sys.modules["homeassistant.helpers.entity_platform"] = entity_platform

try:
    from homeassistant.components.camera import _async_get_image as ha_async_get_image
except ImportError:  # pragma: no cover - only used by the lightweight stub fallback
    ha_async_get_image = None

from custom_components.bticino_c300x import camera as camera_module
from custom_components.bticino_c300x.camera import (
    DOORSTATION_AUDIO_GAIN,
    STILL_IMAGE_BYTES,
    STILL_IMAGE_CONTENT_TYPE,
    TALKBACK_CODEC,
    TALKBACK_RTP_PAYLOAD_TYPE,
    C300XDoorbellCamera,
    _apply_audio_gain,
    _filter_link_local_sdp_candidates,
    _NativeWebRTCSession,
    _new_restarting_rtsp_audio_track,
    _new_restarting_rtsp_tracks,
    _preload_dns_mdns_modules,
    _status_is_home_call_media_active,
)
from custom_components.bticino_c300x.video import resolve_doorbell_camera_entity_id

dispatcher_signals: list[tuple[str, str]] = []


@dataclass
class _FakeEventState:
    video_stream_path: str | None = None
    video_available: bool = False
    last_event_data: dict[str, Any] = field(default_factory=dict)


class _FakeApi:
    def __init__(self) -> None:
        self.activate_calls: list[bool] = []
        self.stop_calls = 0
        self.home_call_start_calls: list[int | None] = []
        self.home_call_stop_calls = 0
        self.home_call_status_calls = 0

    async def async_doorbell_video_status(self) -> dict[str, Any]:
        return {
            "available": True,
            "window_available": True,
            "stream_path": "/doorbell-video",
            "audio_stream_path": "/doorbell",
            "recorder_stream_path": "/doorbell-recorder",
            "bridge": {
                "running": True,
                "audio_codec": "speex/8000",
                "talkback_supported": True,
                "talkback_running": True,
                "talkback_payload_type": 97,
                "talkback_codec": "speex/8000",
            },
        }

    async def async_activate_doorbell_video(self, audio: bool = True) -> dict[str, Any]:
        self.activate_calls.append(audio)
        return {"ok": True, "audio": audio}

    async def async_stop_doorbell_video(self) -> dict[str, Any]:
        self.stop_calls += 1
        return {"ok": True}

    async def async_home_call_status(self) -> dict[str, Any]:
        self.home_call_status_calls += 1
        return {
            "available": True,
            "running": True,
            "active": True,
            "answered": True,
            "rtp_proxy": True,
            "target_audio_port": 62012,
            "rtp_packets": 0,
            "rtcp_packets": 0,
        }

    async def async_start_home_call(
        self,
        duration_seconds: int | None = None,
    ) -> dict[str, Any]:
        self.home_call_start_calls.append(duration_seconds)
        return {"ok": True}

    async def async_stop_home_call(self) -> dict[str, Any]:
        self.home_call_stop_calls += 1
        return {"ok": True}


@dataclass
class _FakeRuntimeData:
    event_state: Any = field(default_factory=_FakeEventState)
    api: Any = field(default_factory=_FakeApi)
    connection_state: Any = field(
        default_factory=lambda: SimpleNamespace(available=True),
    )


def _webrtc_message_value(message: Any, key: str) -> Any:
    if isinstance(message, dict):
        return message.get(key)
    if hasattr(message, "as_dict"):
        return message.as_dict().get(key)
    return getattr(message, key, None)


def test_resolve_doorbell_camera_entity_id_handles_missing_registry() -> None:
    assert (
        resolve_doorbell_camera_entity_id(
            SimpleNamespace(),
            SimpleNamespace(entry_id="entry-1"),
        )
        is None
    )


@dataclass
class _FakeEntry:
    entry_id: str = "entry-1"
    title: str = "C300X"
    data: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    runtime_data: _FakeRuntimeData = field(default_factory=_FakeRuntimeData)


def test_doorbell_camera_sets_visible_entity_icon() -> None:
    assert C300XDoorbellCamera._attr_icon == "mdi:cctv"


def test_doorbell_camera_advertises_native_webrtc_frontend_stream() -> None:
    assert C300XDoorbellCamera._attr_frontend_stream_type == "web_rtc"


def test_doorbell_camera_advertises_stream_feature_for_ha_frontend() -> None:
    assert C300XDoorbellCamera._attr_supported_features == 1


def test_doorbell_camera_does_not_use_background_stream_for_stills() -> None:
    camera = C300XDoorbellCamera(_FakeEntry())  # type: ignore[arg-type]

    assert camera.use_stream_for_stills is False


def test_doorbell_camera_exposes_stream_source_without_changing_native_webrtc_type() -> None:
    assert "stream_source" in C300XDoorbellCamera.__dict__
    assert C300XDoorbellCamera._attr_frontend_stream_type == "web_rtc"


def test_doorbell_camera_suppresses_entity_picture_for_icon_display() -> None:
    camera = C300XDoorbellCamera(_FakeEntry())  # type: ignore[arg-type]

    assert camera.entity_picture is None


def test_doorbell_camera_returns_local_still_without_device_warmup() -> None:
    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    assert "async_camera_image" in C300XDoorbellCamera.__dict__
    assert "camera_image" in C300XDoorbellCamera.__dict__
    assert camera.content_type == STILL_IMAGE_CONTENT_TYPE
    assert camera.camera_image() == STILL_IMAGE_BYTES
    assert asyncio.run(camera.async_camera_image()) == STILL_IMAGE_BYTES
    assert STILL_IMAGE_BYTES.startswith(b"<svg ")
    assert entry.runtime_data.api.activate_calls == []


def test_webrtc_preloads_dnspython_mdns_records_without_failing_on_missing_modules() -> None:
    imported: list[str] = []
    generic_rdata_classes: list[tuple[int, int]] = []

    def _fake_get_rdata_class(rdclass: int, rdtype: int) -> object:
        generic_rdata_classes.append((rdclass, rdtype))
        return object()

    def _fake_import(module_name: str) -> object:
        imported.append(module_name)
        if module_name == "dns.rdtypes.ANY.TXT":
            raise ImportError(module_name)
        if module_name == "dns.rdata":
            return SimpleNamespace(get_rdata_class=_fake_get_rdata_class)
        if module_name == "dns.rdataclass":
            return SimpleNamespace(IN=1)
        if module_name == "dns.rdatatype":
            return SimpleNamespace(A=1, AAAA=28)
        return object()

    _preload_dns_mdns_modules(_fake_import)

    assert imported == [
        "dns.rdtypes.IN.A",
        "dns.rdtypes.IN.AAAA",
        "dns.rdtypes.IN.PTR",
        "dns.rdtypes.ANY.SRV",
        "dns.rdtypes.ANY.TXT",
        "dns.rdata",
        "dns.rdataclass",
        "dns.rdatatype",
    ]
    assert generic_rdata_classes == [(32769, 1), (32769, 28)]


def test_doorbell_camera_proxy_still_uses_local_fallback() -> None:
    if ha_async_get_image is None:
        return
    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    image = asyncio.run(ha_async_get_image(camera, timeout=1))

    assert image.content_type == STILL_IMAGE_CONTENT_TYPE
    assert image.content == STILL_IMAGE_BYTES
    assert entry.runtime_data.api.activate_calls == []


def test_doorbell_camera_exposes_native_webrtc_offer_handler() -> None:
    assert "async_handle_async_webrtc_offer" in C300XDoorbellCamera.__dict__
    assert "async_handle_home_call_webrtc_offer" in C300XDoorbellCamera.__dict__
    assert "async_on_webrtc_candidate" in C300XDoorbellCamera.__dict__


def test_doorbell_camera_buffers_ice_candidate_before_remote_description() -> None:
    class _Peer:
        def __init__(self) -> None:
            self.remoteDescription: object | None = None
            self.candidates: list[Any] = []

        async def addIceCandidate(self, candidate: Any) -> None:  # noqa: N802
            self.candidates.append(candidate)

    async def _load_aiortc_modules() -> SimpleNamespace:
        return SimpleNamespace(candidate_from_sdp=lambda sdp: SimpleNamespace(sdp=sdp))

    camera = C300XDoorbellCamera(_FakeEntry())  # type: ignore[arg-type]
    peer = _Peer()
    camera._webrtc_sessions["session-1"] = _NativeWebRTCSession(peer)
    camera._async_load_aiortc_modules = _load_aiortc_modules  # type: ignore[method-assign]

    asyncio.run(
        camera.async_on_webrtc_candidate(
            "session-1",
            SimpleNamespace(
                candidate="candidate:1 1 udp 2122260223 192.0.2.10 5000 typ host",
                sdpMid="0",
                sdpMLineIndex=0,
            ),
        )
    )

    assert peer.candidates == []
    pending = camera._webrtc_sessions["session-1"].pending_ice_candidates
    assert len(pending) == 1
    assert pending[0].sdp == "1 1 udp 2122260223 192.0.2.10 5000 typ host"
    assert pending[0].sdpMid == "0"
    assert pending[0].sdpMLineIndex == 0


def test_doorbell_camera_flushes_buffered_ice_candidate_after_remote_description() -> None:
    class _Peer:
        remoteDescription = object()

        def __init__(self) -> None:
            self.candidates: list[Any] = []

        async def addIceCandidate(self, candidate: Any) -> None:  # noqa: N802
            self.candidates.append(candidate)

    camera = C300XDoorbellCamera(_FakeEntry())  # type: ignore[arg-type]
    peer = _Peer()
    session = _NativeWebRTCSession(peer)
    session.pending_ice_candidates.append(SimpleNamespace(sdp="candidate-1"))
    camera._webrtc_sessions["session-1"] = session

    asyncio.run(camera._async_flush_pending_webrtc_candidates("session-1"))

    assert len(peer.candidates) == 1
    assert peer.candidates[0].sdp == "candidate-1"
    assert session.pending_ice_candidates == []
    assert session.ice_flush_task is None


def test_doorbell_camera_forwards_ice_candidate_after_remote_description() -> None:
    class _Peer:
        remoteDescription = object()

        def __init__(self) -> None:
            self.candidates: list[Any] = []

        async def addIceCandidate(self, candidate: Any) -> None:  # noqa: N802
            self.candidates.append(candidate)

    async def _load_aiortc_modules() -> SimpleNamespace:
        return SimpleNamespace(candidate_from_sdp=lambda sdp: SimpleNamespace(sdp=sdp))

    camera = C300XDoorbellCamera(_FakeEntry())  # type: ignore[arg-type]
    peer = _Peer()
    camera._webrtc_sessions["session-1"] = _NativeWebRTCSession(peer)
    camera._async_load_aiortc_modules = _load_aiortc_modules  # type: ignore[method-assign]

    asyncio.run(
        camera.async_on_webrtc_candidate(
            "session-1",
            SimpleNamespace(
                candidate="candidate:1 1 udp 2122260223 192.0.2.10 5000 typ host",
                sdpMid="0",
                sdpMLineIndex=0,
            ),
        )
    )

    assert len(peer.candidates) == 1
    assert peer.candidates[0].sdp == "1 1 udp 2122260223 192.0.2.10 5000 typ host"
    assert peer.candidates[0].sdpMid == "0"
    assert peer.candidates[0].sdpMLineIndex == 0


def test_doorbell_camera_mirrors_ha_ice_servers_for_cloud_webrtc() -> None:
    class _AiortcIceServer:
        def __init__(
            self,
            urls: str | list[str],
            username: str | None = None,
            credential: str | None = None,
        ) -> None:
            self.urls = urls
            self.username = username
            self.credential = credential

    class _AiortcConfiguration:
        def __init__(self, iceServers: list[_AiortcIceServer]) -> None:
            self.iceServers = iceServers

    camera = C300XDoorbellCamera(_FakeEntry())  # type: ignore[arg-type]
    camera.async_get_webrtc_client_configuration = lambda: SimpleNamespace(
        configuration=SimpleNamespace(
            ice_servers=[
                SimpleNamespace(
                    urls=["turn:relay.example:3478"],
                    username="cloud-user",
                    credential="cloud-credential",
                ),
                SimpleNamespace(urls=["stun:stun.home-assistant.io:3478"]),
            ]
        )
    )

    config = camera._webrtc_server_configuration(
        SimpleNamespace(
            RTCConfiguration=_AiortcConfiguration,
            RTCIceServer=_AiortcIceServer,
        )
    )

    assert [server.urls for server in config.iceServers] == [
        ["turn:relay.example:3478"],
        ["stun:stun.home-assistant.io:3478"],
    ]
    assert config.iceServers[0].username == "cloud-user"
    assert config.iceServers[0].credential == "cloud-credential"


def test_doorbell_camera_prefers_browser_audio_codecs_for_webrtc() -> None:
    class _Codec:
        def __init__(self, mime_type: str) -> None:
            self.mimeType = mime_type

    class _Sender:
        @staticmethod
        def getCapabilities(kind: str) -> SimpleNamespace:  # noqa: N802
            if kind == "video":
                return SimpleNamespace(
                    codecs=[_Codec("video/VP8"), _Codec("video/H264")]
                )
            return SimpleNamespace(
                codecs=[
                    _Codec("audio/G722"),
                    _Codec("audio/opus"),
                    _Codec("audio/PCMU"),
                ]
            )

    class _Transceiver:
        def __init__(self, kind: str) -> None:
            self.kind = kind
            self.preferences: list[str] = []

        def setCodecPreferences(self, codecs: list[_Codec]) -> None:  # noqa: N802
            self.preferences = [codec.mimeType for codec in codecs]

    video = _Transceiver("video")
    audio = _Transceiver("audio")
    peer = SimpleNamespace(getTransceivers=lambda: [video, audio])
    camera = C300XDoorbellCamera(_FakeEntry())  # type: ignore[arg-type]

    camera._prefer_webrtc_codecs(peer, SimpleNamespace(RTCRtpSender=_Sender))

    assert video.preferences == ["video/H264", "video/VP8"]
    assert audio.preferences == ["audio/opus", "audio/PCMU", "audio/G722"]


def test_webrtc_answer_filters_link_local_candidates_when_relay_exists() -> None:
    sdp = (
        "v=0\r\n"
        "a=candidate:1 1 udp 2130706431 fe80::1 5000 typ host\r\n"
        "a=candidate:2 1 udp 2130706431 ha-local.local 5001 typ host\r\n"
        "a=candidate:3 1 udp 1677729535 192.0.2.10 5002 typ relay\r\n"
        "a=end-of-candidates\r\n"
    )

    filtered = _filter_link_local_sdp_candidates(sdp)

    assert "fe80::1" not in filtered
    assert "ha-local.local" not in filtered
    assert "192.0.2.10" in filtered
    assert filtered.endswith("\r\n")


def test_webrtc_answer_keeps_link_local_candidates_when_no_alternative_exists() -> None:
    sdp = "v=0\r\na=candidate:1 1 udp 2130706431 fe80::1 5000 typ host\r\n"

    assert _filter_link_local_sdp_candidates(sdp) == sdp


def test_doorbell_camera_exposes_only_user_facing_media_attributes() -> None:
    entry = _FakeEntry()
    entry.runtime_data.device_user_status = {
        "media_identity_source": "homeassistant",
        "account_label": "Home Assistant Test",
    }
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera._video_window_available = True
    camera._video_owner = "ring"
    camera._external_media_active = True
    camera._external_owner = "app"
    camera._last_video_block_reason = "external_session_active"
    camera._bridge_status = {
        "rtsp_port": 6554,
        "audio_stream_path": "/doorbell",
        "recorder_stream_path": "/doorbell-recorder",
        "talkback_supported": True,
        "talkback_running": True,
        "talkback_payload_type": TALKBACK_RTP_PAYLOAD_TYPE,
        "talkback_codec": TALKBACK_CODEC,
    }

    attrs = camera.extra_state_attributes

    assert attrs == {
        "video_window_available": True,
        "video_owner": "ring",
        "external_media_active": True,
        "external_owner": "app",
        "last_video_block_reason": "external_session_active",
        "talkback_supported": True,
        "media_user": {
            "source": "homeassistant",
            "account": "homeassistant",
            "label": "Home Assistant Test",
        },
    }


def test_doorbell_camera_refresh_applies_bridge_audio_metadata() -> None:
    camera = C300XDoorbellCamera(_FakeEntry())  # type: ignore[arg-type]

    asyncio.run(camera.async_update())
    attrs = camera.extra_state_attributes

    assert attrs["video_window_available"] is True
    assert attrs["talkback_supported"] is True
    assert camera._bridge_available is True
    assert camera._attr_is_streaming is True
    assert camera._audio_stream_path == "/doorbell"
    assert camera._recorder_stream_path == "/doorbell-recorder"


def test_doorbell_camera_does_not_expose_talkback_session_state() -> None:
    camera = C300XDoorbellCamera(_FakeEntry())  # type: ignore[arg-type]
    camera._bridge_status = {"audio_codec": TALKBACK_CODEC}
    session = _NativeWebRTCSession(SimpleNamespace())
    session.talkback_requested = True
    session.talkback_active = True
    session.talkback_packets_sent = 2
    camera._webrtc_sessions["session-1"] = session
    camera._set_talkback_error("CodecUnavailable")

    attrs = camera.extra_state_attributes

    assert attrs["talkback_supported"] is True
    assert "talkback_requested" not in attrs
    assert "talkback_active" not in attrs
    assert "talkback_packets_sent" not in attrs
    assert "talkback_last_error" not in attrs


def test_doorbell_camera_closing_last_webrtc_session_stops_video_call() -> None:
    class _Peer:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    class _Player:
        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera.hass = SimpleNamespace()
    peer = _Peer()
    player = _Player()
    session = _NativeWebRTCSession(peer)
    session.player = player
    camera._webrtc_sessions["session-1"] = session

    asyncio.run(camera._async_close_webrtc_session("session-1"))

    assert entry.runtime_data.api.stop_calls == 1
    assert peer.closed is True
    assert player.stopped is True
    assert camera.extra_state_attributes["video_window_available"] is False


def test_doorbell_camera_closing_one_of_multiple_webrtc_sessions_keeps_agent_state() -> None:
    class _Peer:
        async def close(self) -> None:
            return None

    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera.hass = SimpleNamespace()
    camera._webrtc_sessions["session-1"] = _NativeWebRTCSession(_Peer())
    camera._webrtc_sessions["session-2"] = _NativeWebRTCSession(_Peer())
    camera._video_window_available = True
    camera._video_stream_path = "/doorbell-video"

    asyncio.run(camera._async_close_webrtc_session("session-1"))

    assert entry.runtime_data.api.stop_calls == 0
    assert "session-2" in camera._webrtc_sessions
    assert camera.extra_state_attributes["video_window_available"] is True


def test_doorbell_camera_webrtc_stream_url_does_not_pre_warm_video_call_path() -> None:
    entry = _FakeEntry(data={"agent_host": "127.0.0.1", "video_port": 6554})
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    source = camera._build_stream_url(audio=False)

    assert source == "rtsp://127.0.0.1:6554/doorbell-video"
    assert entry.runtime_data.api.activate_calls == []


def test_doorbell_camera_stream_source_warms_video_once() -> None:
    entry = _FakeEntry(data={"agent_host": "127.0.0.1", "video_port": 6554})
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    async def _run() -> str:
        server = await asyncio.start_server(
            _rtsp_options_server,
            "127.0.0.1",
            0,
        )
        port = server.sockets[0].getsockname()[1]
        entry.data["video_port"] = port
        try:
            return await camera.stream_source()
        finally:
            server.close()
            await server.wait_closed()

    source = asyncio.run(_run())

    assert source.startswith("rtsp://127.0.0.1:")
    assert source.endswith("/doorbell-video")
    assert entry.runtime_data.api.activate_calls == [False]


def test_doorbell_camera_audio_stream_source_uses_audio_video_path() -> None:
    entry = _FakeEntry(data={"agent_host": "127.0.0.1", "video_port": 6554})
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    async def _run() -> str:
        server = await asyncio.start_server(
            _rtsp_options_server,
            "127.0.0.1",
            0,
        )
        port = server.sockets[0].getsockname()[1]
        entry.data["video_port"] = port
        try:
            return await camera._async_prepare_rtsp_stream(audio=True)
        finally:
            server.close()
            await server.wait_closed()

    source = asyncio.run(_run())

    assert source.startswith("rtsp://127.0.0.1:")
    assert source.endswith("/doorbell")
    assert entry.runtime_data.api.activate_calls == [True]


def test_doorbell_camera_uses_active_ring_media_without_on_demand_activation() -> None:
    class _RingApi(_FakeApi):
        async def async_doorbell_video_status(self) -> dict[str, Any]:
            status = await super().async_doorbell_video_status()
            status["media_owner"] = "ring"
            status["bridge"] = {
                **status["bridge"],
                "media_owner": "ring",
                "ring_call_active": True,
                "ring_media_active": True,
            }
            return status

    api = _RingApi()
    entry = _FakeEntry(
        data={"agent_host": "127.0.0.1", "video_port": 6554},
        runtime_data=_FakeRuntimeData(api=api),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    async def _run() -> str:
        server = await asyncio.start_server(
            _rtsp_options_server,
            "127.0.0.1",
            0,
        )
        port = server.sockets[0].getsockname()[1]
        entry.data["video_port"] = port
        try:
            return await camera._async_prepare_rtsp_stream(audio=True)
        finally:
            server.close()
            await server.wait_closed()

    source = asyncio.run(_run())

    assert source.startswith("rtsp://127.0.0.1:")
    assert source.endswith("/doorbell")
    assert api.activate_calls == []


def test_doorbell_camera_waits_for_ring_call_after_external_event(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(camera_module, "RING_CALL_WAIT_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(camera_module, "RING_CALL_WAIT_TIMEOUT_SECONDS", 0.1)

    class _DelayedRingApi(_FakeApi):
        def __init__(self) -> None:
            super().__init__()
            self.status_calls = 0

        async def async_doorbell_video_status(self) -> dict[str, Any]:
            self.status_calls += 1
            status = await super().async_doorbell_video_status()
            if self.status_calls == 1:
                status["external_media_active"] = True
                status["bridge"] = {
                    **status["bridge"],
                    "external_media_active": True,
                    "external_owner": "external_media",
                }
                return status
            status["media_owner"] = "ring"
            status["bridge"] = {
                **status["bridge"],
                "media_owner": "ring",
                "ring_call_active": True,
                "ring_media_active": False,
            }
            return status

    api = _DelayedRingApi()
    entry = _FakeEntry(
        data={"agent_host": "127.0.0.1", "video_port": 6554},
        runtime_data=_FakeRuntimeData(api=api),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    async def _run() -> str:
        server = await asyncio.start_server(
            _rtsp_options_server,
            "127.0.0.1",
            0,
        )
        port = server.sockets[0].getsockname()[1]
        entry.data["video_port"] = port
        try:
            return await camera._async_prepare_rtsp_stream(audio=True)
        finally:
            server.close()
            await server.wait_closed()

    source = asyncio.run(_run())

    assert source.startswith("rtsp://127.0.0.1:")
    assert source.endswith("/doorbell")
    assert api.status_calls == 2
    assert api.activate_calls == []


def test_doorbell_camera_ring_reader_restart_does_not_restart_on_demand() -> None:
    class _RingApi(_FakeApi):
        async def async_doorbell_video_status(self) -> dict[str, Any]:
            status = await super().async_doorbell_video_status()
            status["media_owner"] = "ring"
            status["bridge"] = {
                **status["bridge"],
                "media_owner": "ring",
                "ring_call_active": True,
                "ring_media_active": True,
            }
            return status

        async def async_stop_doorbell_video(self) -> dict[str, Any]:
            raise AssertionError("ring RTSP restart must not stop the ring call")

    api = _RingApi()
    entry = _FakeEntry(
        data={"agent_host": "127.0.0.1", "video_port": 6554},
        runtime_data=_FakeRuntimeData(api=api),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    async def _run() -> None:
        server = await asyncio.start_server(
            _rtsp_options_server,
            "127.0.0.1",
            0,
        )
        port = server.sockets[0].getsockname()[1]
        entry.data["video_port"] = port
        try:
            await camera._async_restart_video_reader(audio=True)
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(_run())

    assert api.activate_calls == []


def test_doorbell_camera_uses_active_home_call_media_without_on_demand_activation() -> None:
    class _HomeCallApi(_FakeApi):
        async def async_doorbell_video_status(self) -> dict[str, Any]:
            status = await super().async_doorbell_video_status()
            status["media_owner"] = "home_call"
            status["bridge"] = {
                **status["bridge"],
                "media_owner": "home_call",
                "home_call_running": True,
                "home_call_active": True,
                "home_call_answered": True,
            }
            return status

    api = _HomeCallApi()
    entry = _FakeEntry(
        data={"agent_host": "127.0.0.1", "video_port": 6554},
        runtime_data=_FakeRuntimeData(api=api),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    async def _run() -> str:
        server = await asyncio.start_server(
            _rtsp_options_server,
            "127.0.0.1",
            0,
        )
        port = server.sockets[0].getsockname()[1]
        entry.data["video_port"] = port
        try:
            return await camera._async_prepare_rtsp_stream(audio=True)
        finally:
            server.close()
            await server.wait_closed()

    source = asyncio.run(_run())

    assert source.startswith("rtsp://127.0.0.1:")
    assert source.endswith("/doorbell")
    assert api.activate_calls == []


def test_doorbell_camera_home_call_reader_restart_does_not_restart_on_demand() -> None:
    class _HomeCallApi(_FakeApi):
        async def async_doorbell_video_status(self) -> dict[str, Any]:
            status = await super().async_doorbell_video_status()
            status["media_owner"] = "home_call"
            status["bridge"] = {
                **status["bridge"],
                "media_owner": "home_call",
                "home_call_running": True,
                "home_call_active": True,
                "home_call_answered": True,
            }
            return status

        async def async_stop_doorbell_video(self) -> dict[str, Any]:
            raise AssertionError("home-call RTSP restart must not stop the call")

    api = _HomeCallApi()
    entry = _FakeEntry(
        data={"agent_host": "127.0.0.1", "video_port": 6554},
        runtime_data=_FakeRuntimeData(api=api),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    async def _run() -> None:
        server = await asyncio.start_server(
            _rtsp_options_server,
            "127.0.0.1",
            0,
        )
        port = server.sockets[0].getsockname()[1]
        entry.data["video_port"] = port
        try:
            await camera._async_restart_video_reader(audio=True)
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(_run())

    assert api.activate_calls == []


def test_doorbell_camera_serializes_parallel_rtsp_warmups() -> None:
    class _DelayedApi(_FakeApi):
        def __init__(self) -> None:
            super().__init__()
            self.active_activate_calls = 0
            self.max_active_activate_calls = 0

        async def async_activate_doorbell_video(
            self,
            audio: bool = True,
        ) -> dict[str, Any]:
            self.active_activate_calls += 1
            self.max_active_activate_calls = max(
                self.max_active_activate_calls,
                self.active_activate_calls,
            )
            try:
                await asyncio.sleep(0.02)
                return await super().async_activate_doorbell_video(audio=audio)
            finally:
                self.active_activate_calls -= 1

    api = _DelayedApi()
    entry = _FakeEntry(
        data={"agent_host": "127.0.0.1", "video_port": 6554},
        runtime_data=_FakeRuntimeData(api=api),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    async def _run() -> None:
        server = await asyncio.start_server(
            _rtsp_options_server,
            "127.0.0.1",
            0,
        )
        port = server.sockets[0].getsockname()[1]
        entry.data["video_port"] = port
        try:
            await asyncio.gather(
                camera._async_prepare_rtsp_stream(audio=True),
                camera._async_prepare_rtsp_stream(audio=True),
            )
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(_run())

    assert api.activate_calls == [True, True]
    assert api.max_active_activate_calls == 1


def test_doorbell_camera_detects_audio_webrtc_offer() -> None:
    camera = C300XDoorbellCamera(_FakeEntry())  # type: ignore[arg-type]

    assert camera._offer_has_audio("v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n")
    assert camera._offer_accepts_incoming_audio(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=recvonly\r\n"
    )
    assert camera._offer_accepts_incoming_audio(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=sendrecv\r\n"
    )
    assert camera._offer_accepts_incoming_audio(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
    )
    assert not camera._offer_accepts_incoming_audio(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=sendonly\r\n"
    )
    assert not camera._offer_accepts_incoming_audio(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=inactive\r\n"
    )
    assert not camera._offer_has_audio("v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n")

    assert camera._offer_can_send_microphone(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=sendrecv\r\n"
    )
    assert camera._offer_can_send_microphone(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=sendonly\r\n"
    )
    assert camera._offer_can_send_microphone(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
    )
    assert not camera._offer_can_send_microphone(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=recvonly\r\n"
    )
    assert not camera._offer_can_send_microphone(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=inactive\r\n"
    )


def test_doorbell_camera_uses_audio_whenever_offer_accepts_incoming_audio() -> None:
    camera = C300XDoorbellCamera(_FakeEntry())  # type: ignore[arg-type]

    assert camera._offer_should_use_audio_stream(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=recvonly\r\n"
    )
    assert camera._offer_should_use_audio_stream(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=sendrecv\r\n"
    )
    assert camera._offer_should_use_audio_stream(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
    )
    assert not camera._offer_should_use_audio_stream(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=sendonly\r\n"
    )
    assert not camera._offer_should_use_audio_stream(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=inactive\r\n"
    )


def test_doorbell_camera_home_call_webrtc_offer_starts_audio_only_session() -> None:
    sent_messages: list[Any] = []
    ready_urls: list[str] = []
    peers: list[Any] = []

    class _FakeHass:
        def async_create_task(self, coro: Any) -> asyncio.Task:
            return asyncio.create_task(coro)

        async def async_add_executor_job(self, func: Any) -> Any:
            return func()

    class _Peer:
        connectionState = "new"
        iceGatheringState = "complete"

        def __init__(self, configuration: Any) -> None:
            self.configuration = configuration
            self.remoteDescription = None
            self.localDescription = SimpleNamespace(
                sdp="v=0\r\na=candidate:1 1 udp 1 192.0.2.10 9 typ host\r\n"
            )
            self.tracks: list[Any] = []
            self.handlers: dict[str, Any] = {}
            self.closed = False
            peers.append(self)

        def on(self, event: str) -> Any:
            def _decorator(func: Any) -> Any:
                self.handlers[event] = func
                return func

            return _decorator

        def addTrack(self, track: Any) -> None:  # noqa: N802
            self.tracks.append(track)

        def getTransceivers(self) -> list[Any]:  # noqa: N802
            return []

        async def setRemoteDescription(self, description: Any) -> None:  # noqa: N802
            self.remoteDescription = description

        async def createAnswer(self) -> Any:  # noqa: N802
            return SimpleNamespace(sdp="v=0\r\n", type="answer")

        async def setLocalDescription(self, answer: Any) -> None:  # noqa: N802
            self.localDescription = answer

        async def close(self) -> None:
            self.closed = True

    class _AudioTrack:
        kind = "audio"

        def stop(self) -> None:
            return None

    async def _load_aiortc_modules() -> SimpleNamespace:
        return SimpleNamespace(
            AudioStreamTrack=_AudioTrack,
            MediaPlayer=object,
            MediaStreamError=Exception,
            RTCConfiguration=lambda iceServers: SimpleNamespace(
                iceServers=iceServers
            ),
            RTCIceServer=lambda **kwargs: SimpleNamespace(**kwargs),
            RTCPeerConnection=_Peer,
            RTCRtpSender=SimpleNamespace(
                getCapabilities=lambda _kind: SimpleNamespace(codecs=[])
            ),
            RTCSessionDescription=lambda *, sdp, type: SimpleNamespace(
                sdp=sdp,
                type=type,
            ),
        )

    async def _wait_for_rtsp_ready(stream_url: str) -> None:
        ready_urls.append(stream_url)

    api = _FakeApi()
    entry = _FakeEntry(
        data={"agent_host": "127.0.0.1", "video_port": 6554},
        runtime_data=_FakeRuntimeData(api=api),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera.hass = _FakeHass()
    camera._async_load_aiortc_modules = _load_aiortc_modules  # type: ignore[method-assign]
    camera._async_wait_for_rtsp_ready = _wait_for_rtsp_ready  # type: ignore[method-assign]

    offer = "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=sendrecv\r\n"

    async def _run() -> None:
        await camera.async_handle_home_call_webrtc_offer(
            offer,
            "session-home",
            sent_messages.append,
            duration_seconds=30,
        )

        session = camera._webrtc_sessions["session-home"]
        assert session.owner == "home_call"
        assert session.talkback_requested is True
        assert peers[0].tracks and peers[0].tracks[0].kind == "audio"
        assert entry.runtime_data.event_state.video_available is False
        assert camera.extra_state_attributes["video_owner"] == "home_call"
        assert camera.extra_state_attributes["video_window_available"] is False

        await camera._async_close_webrtc_session("session-home")

        await camera.async_handle_home_call_webrtc_offer(
            "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=recvonly\r\n",
            "session-home-listen",
            sent_messages.append,
            duration_seconds=30,
        )

        listen_session = camera._webrtc_sessions["session-home-listen"]
        assert listen_session.owner == "home_call"
        assert listen_session.talkback_requested is False
        assert peers[1].tracks and peers[1].tracks[0].kind == "audio"

        await camera._async_close_webrtc_session("session-home-listen")

    asyncio.run(_run())

    assert api.home_call_start_calls == [30, 30]
    assert api.home_call_status_calls == 2
    assert api.home_call_stop_calls == 2
    assert api.activate_calls == []
    assert api.stop_calls == 0
    assert ready_urls == [
        "rtsp://127.0.0.1:6554/doorbell",
        "rtsp://127.0.0.1:6554/doorbell",
    ]
    assert peers[0].closed is True
    assert peers[1].closed is True
    assert any(
        _webrtc_message_value(message, "type") == "answer"
        for message in sent_messages
    )
    assert not any(
        _webrtc_message_value(message, "type") == "error"
        for message in sent_messages
    )


def test_doorbell_camera_home_call_webrtc_offer_requires_incoming_audio() -> None:
    class _FakeHass:
        async def async_add_executor_job(self, func: Any) -> Any:
            return func()

    async def _load_aiortc_modules() -> SimpleNamespace:
        return SimpleNamespace(
            RTCPeerConnection=lambda **_kwargs: (_ for _ in ()).throw(
                AssertionError("invalid Home Call SDP must not create a peer")
            )
        )

    api = _FakeApi()
    entry = _FakeEntry(runtime_data=_FakeRuntimeData(api=api))
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera.hass = _FakeHass()
    camera._async_load_aiortc_modules = _load_aiortc_modules  # type: ignore[method-assign]
    sent_messages: list[Any] = []

    asyncio.run(
        camera.async_handle_home_call_webrtc_offer(
            "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=sendonly\r\n",
            "session-home",
            sent_messages.append,
        )
    )

    assert camera._webrtc_sessions == {}
    assert api.home_call_start_calls == []
    assert api.home_call_stop_calls == 0
    assert any(
        _webrtc_message_value(message, "type") == "error"
        for message in sent_messages
    )


def test_doorbell_camera_home_call_renew_does_not_warm_video(
    monkeypatch,
) -> None:  # noqa: ANN001
    monkeypatch.setattr(camera_module, "WEBRTC_RENEW_SECONDS", 0.01)
    api = _FakeApi()
    entry = _FakeEntry(runtime_data=_FakeRuntimeData(api=api))
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera._webrtc_sessions["session-home"] = _NativeWebRTCSession(
        SimpleNamespace(),
        owner="home_call",
    )

    async def _run() -> None:
        task = asyncio.create_task(
            camera._async_renew_webrtc_until_closed("session-home")
        )
        await asyncio.sleep(0.03)
        camera._webrtc_sessions.pop("session-home", None)
        await asyncio.wait_for(task, 1)

    asyncio.run(_run())

    assert api.home_call_status_calls >= 1
    assert api.activate_calls == []
    assert camera._bridge_status.get("home_call_active") is None


def test_doorbell_camera_home_call_wait_ignores_pre_answer_running_state(
    monkeypatch,
) -> None:  # noqa: ANN001
    monkeypatch.setattr(camera_module, "RTSP_READY_INTERVAL_SECONDS", 0.01)

    class _HomeCallApi(_FakeApi):
        def __init__(self) -> None:
            super().__init__()
            self._statuses = [
                {
                    "available": True,
                    "running": True,
                    "active": True,
                    "answered": False,
                    "rtp_proxy": False,
                    "target_audio_port": 0,
                },
                {
                    "available": True,
                    "running": True,
                    "active": True,
                    "answered": True,
                    "rtp_proxy": True,
                    "target_audio_port": 20290,
                },
            ]

        async def async_home_call_status(self) -> dict[str, Any]:
            self.home_call_status_calls += 1
            return self._statuses.pop(0) if self._statuses else {
                "available": True,
                "running": True,
                "active": True,
                "answered": True,
                "rtp_proxy": True,
                "target_audio_port": 20290,
            }

    api = _HomeCallApi()
    entry = _FakeEntry(runtime_data=_FakeRuntimeData(api=api))
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    status = asyncio.run(camera._async_wait_for_home_call_active())

    assert api.home_call_status_calls == 2
    assert status["active"] is True
    assert camera._bridge_status["home_call_active"] is True
    assert camera._bridge_status["home_call_target_audio_port"] == 20290


def test_doorbell_camera_builds_speex_talkback_rtp_packet() -> None:
    camera = C300XDoorbellCamera(_FakeEntry())  # type: ignore[arg-type]

    packet = camera._build_talkback_rtp_packet(
        b"speex-payload",
        sequence=7,
        timestamp=8000,
        ssrc=1234,
        marker=True,
    )

    version, marker_payload, sequence, timestamp, ssrc = struct.unpack(
        "!BBHII",
        packet[:12],
    )
    assert version == 0x80
    assert marker_payload == 0x80 | TALKBACK_RTP_PAYLOAD_TYPE
    assert sequence == 7
    assert timestamp == 8000
    assert ssrc == 1234
    assert packet[12:] == b"speex-payload"


def test_doorbell_camera_forwards_browser_audio_as_talkback_rtp(monkeypatch) -> None:  # noqa: ANN001
    class _MediaStreamError(Exception):
        pass

    class _FakeFrame:
        samples = 160

    class _FakeTrack:
        def __init__(self) -> None:
            self._sent = False

        async def recv(self) -> _FakeFrame:
            if self._sent:
                raise _MediaStreamError
            self._sent = True
            return _FakeFrame()

    class _FakePacket:
        duration = 160

        def __bytes__(self) -> bytes:
            return b"speex-payload"

    class _FakeEncoder:
        sample_rate = 0
        layout = ""
        format = ""
        time_base = None
        bit_rate = 0

        def open(self) -> None:
            pass

        def encode(self, frame: Any) -> list[_FakePacket]:
            if frame is None:
                return []
            return [_FakePacket()]

    class _FakeCodecContext:
        @staticmethod
        def create(codec: str, mode: str) -> _FakeEncoder:
            assert codec == "libspeex"
            assert mode == "w"
            return _FakeEncoder()

    class _FakeResampler:
        def __init__(self, *, format: str, layout: str, rate: int) -> None:
            assert format == "s16"
            assert layout == "mono"
            assert rate == 8000

        def resample(self, frame: Any) -> list[Any]:
            return [frame]

    async def _run() -> tuple[bytes, _NativeWebRTCSession, dict[str, Any]]:
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.bind(("127.0.0.1", 0))
        udp.setblocking(False)
        monkeypatch.setattr(camera_module, "TALKBACK_RTP_PORT", udp.getsockname()[1])
        entry = _FakeEntry(data={"agent_host": "127.0.0.1"})
        camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
        camera._bridge_status = {"talkback_supported": True}
        session = _NativeWebRTCSession(SimpleNamespace())
        camera._webrtc_sessions["session-1"] = session
        aiortc_modules = SimpleNamespace(
            av=SimpleNamespace(CodecContext=_FakeCodecContext),
            AudioResampler=_FakeResampler,
            MediaStreamError=_MediaStreamError,
        )
        loop = asyncio.get_running_loop()
        try:
            task = asyncio.create_task(
                camera._async_forward_talkback_audio(
                    _FakeTrack(),
                    aiortc_modules,
                    "session-1",
                )
            )
            packet, _addr = await asyncio.wait_for(loop.sock_recvfrom(udp, 2048), 1)
            await asyncio.wait_for(task, 1)
            return packet, session, camera.extra_state_attributes
        finally:
            udp.close()

    packet, session, attrs = asyncio.run(_run())
    version, marker_payload, sequence, _timestamp, _ssrc = struct.unpack(
        "!BBHII",
        packet[:12],
    )

    assert version == 0x80
    assert marker_payload == 0x80 | TALKBACK_RTP_PAYLOAD_TYPE
    assert sequence >= 0
    assert packet[12:] == b"speex-payload"
    assert session.talkback_packets_sent == 1
    assert session.talkback_active is False
    assert "talkback_packets_sent" not in attrs
    assert "talkback_active" not in attrs
    assert "talkback_last_error" not in attrs


def test_doorbell_camera_keeps_talkback_host_errors_out_of_attributes() -> None:
    async def _run() -> dict[str, Any]:
        entry = _FakeEntry(data={"agent_host": ""})
        camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
        camera._webrtc_sessions["session-1"] = _NativeWebRTCSession(SimpleNamespace())
        await camera._async_forward_talkback_audio(
            SimpleNamespace(),
            SimpleNamespace(),
            "session-1",
        )
        return camera.extra_state_attributes

    attrs = asyncio.run(_run())

    assert "talkback_last_error" not in attrs


def test_restarting_rtsp_tracks_share_one_audio_video_reader() -> None:
    opened_urls: list[str] = []

    class _Frame:
        pts: int | None = None
        time_base: object | None = None

    class _SourceTrack:
        def __init__(self, kind: str) -> None:
            self.kind = kind
            self.stopped = False

        async def recv(self) -> _Frame:
            return _Frame()

        def stop(self) -> None:
            self.stopped = True

    class _VideoTrack:
        kind = "video"

        async def next_timestamp(self) -> tuple[int, str]:
            return 1, "1/90000"

        def stop(self) -> None:
            pass

    class _AudioTrack:
        kind = "audio"

        def stop(self) -> None:
            pass

    class _MediaPlayer:
        def __init__(self, url: str, options: dict[str, str]) -> None:
            opened_urls.append(url)
            self.video = _SourceTrack("video")
            self.audio = _SourceTrack("audio")

    class _Hass:
        async def async_add_executor_job(self, func: Any) -> Any:
            return func()

    async def _run() -> tuple[_Frame, _Frame]:
        media, video_track, audio_track = _new_restarting_rtsp_tracks(
            SimpleNamespace(),
            _VideoTrack,
            _AudioTrack,
            Exception,
            _MediaPlayer,
            _Hass(),  # type: ignore[arg-type]
            "rtsp://agent.local:6554/doorbell",
            lambda: None,
        )
        try:
            return await video_track.recv(), await audio_track.recv()
        finally:
            media.stop()

    video_frame, audio_frame = asyncio.run(_run())

    assert opened_urls == ["rtsp://agent.local:6554/doorbell"]
    assert video_frame.pts == 1
    assert video_frame.time_base == "1/90000"
    assert audio_frame.pts is None


def test_restarting_rtsp_audio_track_accepts_home_call_audio_only_reader() -> None:
    opened_urls: list[str] = []

    class _Frame:
        pass

    class _SourceTrack:
        def __init__(self, kind: str) -> None:
            self.kind = kind
            self.stopped = False

        async def recv(self) -> _Frame:
            return _Frame()

        def stop(self) -> None:
            self.stopped = True

    class _AudioTrack:
        kind = "audio"

        def stop(self) -> None:
            pass

    class _MediaPlayer:
        def __init__(self, url: str, options: dict[str, str]) -> None:
            opened_urls.append(url)
            self.video = None
            self.audio = _SourceTrack("audio")

    class _Hass:
        async def async_add_executor_job(self, func: Any) -> Any:
            return func()

    async def _run() -> _Frame:
        audio_track = _new_restarting_rtsp_audio_track(
            _AudioTrack,
            Exception,
            _MediaPlayer,
            _Hass(),  # type: ignore[arg-type]
            "rtsp://agent.local:6554/doorbell",
            lambda: None,
        )
        try:
            return await audio_track.recv()
        finally:
            audio_track.stop()

    frame = asyncio.run(_run())

    assert opened_urls == ["rtsp://agent.local:6554/doorbell"]
    assert isinstance(frame, _Frame)


def test_doorbell_camera_detects_home_call_media_for_audio_only() -> None:
    assert _status_is_home_call_media_active(
        {"media_owner": "home_call", "bridge": {}}
    )
    assert _status_is_home_call_media_active(
        {"bridge": {"media_owner": "home_call"}}
    )
    assert _status_is_home_call_media_active(
        {"bridge": {"home_call_active": True}}
    )
    assert not _status_is_home_call_media_active(
        {"media_owner": "ring", "bridge": {"ring_call_active": True}}
    )


def test_doorbell_camera_stream_url_brackets_ipv6_host() -> None:
    entry = _FakeEntry(data={"agent_host": "fe80::1%wlan0", "video_port": 6554})
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    assert camera._build_stream_url(audio=False) == (
        "rtsp://[fe80::1%25wlan0]:6554/doorbell-video"
    )
    assert camera._agent_host_for_socket() == "fe80::1%wlan0"


def test_doorbell_camera_rtsp_cooldown_avoids_repeated_activate() -> None:
    entry = _FakeEntry(data={"agent_host": "127.0.0.1", "video_port": 9})
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera._rtsp_unavailable_until = 999999999.0
    camera._last_rtsp_error = "ConnectionRefusedError"

    async def _run() -> None:
        try:
            await camera.stream_source()
        except Exception:
            return
        raise AssertionError("stream_source did not fail during RTSP cooldown")

    asyncio.run(_run())

    assert entry.runtime_data.api.activate_calls == []


def test_doorbell_camera_webrtc_stream_url_uses_options_agent_host() -> None:
    entry = _FakeEntry(
        data={"agent_host": "stale-agent.local", "video_port": 6554},
        options={"agent_host": "agent.local"},
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    source = camera._build_stream_url(audio=False)

    assert source == "rtsp://agent.local:6554/doorbell-video"


def test_doorbell_camera_preserves_connection_availability() -> None:
    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    entry.runtime_data.connection_state.available = False
    assert camera.available is False

    entry.runtime_data.connection_state.available = True
    camera._attr_available = False
    assert camera.available is False

    camera._attr_available = True
    assert camera.available is True


def test_doorbell_camera_updates_state_on_doorbell_view_event() -> None:
    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    event = SimpleNamespace(
        data={
            "entry_id": entry.entry_id,
            "event_key": "doorbell_view_requested",
            "video_window_available": True,
            "video_available": True,
            "stream_path": "/doorbell-video",
        }
    )

    camera._handle_agent_event(event)

    attrs = camera.extra_state_attributes
    assert attrs["video_window_available"] is True
    assert camera._bridge_available is True
    assert camera._attr_is_streaming is True


def test_doorbell_camera_does_not_mark_external_view_as_ha_available() -> None:
    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    event = SimpleNamespace(
        data={
            "entry_id": entry.entry_id,
            "event_key": "doorbell_view_requested",
        }
    )

    camera._handle_agent_event(event)

    attrs = camera.extra_state_attributes
    assert attrs["video_window_available"] is False
    assert camera._bridge_available is False
    assert camera._attr_is_streaming is False


def test_doorbell_camera_keeps_agent_video_until_close_event() -> None:
    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    camera._video_window_available = True
    camera._video_stream_path = "/doorbell-video"
    camera._bridge_available = True

    attrs = camera.extra_state_attributes
    assert attrs["video_window_available"] is True
    assert camera._bridge_available is True


def test_doorbell_camera_clears_state_on_video_closed_event() -> None:
    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera._video_window_available = True
    camera._bridge_available = True
    camera._video_owner = "external_media"
    camera._external_media_active = True
    camera._external_owner = "external_media"
    camera._last_video_block_reason = "external_session_active"
    camera._bridge_status = {
        "media_owner": "external_media",
        "media_active": False,
        "external_media_active": True,
        "ring_call_active": False,
        "ring_media_active": False,
        "call_active": False,
    }

    event = SimpleNamespace(
        data={"entry_id": entry.entry_id, "event_key": "doorbell_media_closed"}
    )
    camera._handle_agent_event(event)

    attrs = camera.extra_state_attributes
    assert attrs["video_window_available"] is False
    assert attrs["video_owner"] == "idle"
    assert attrs["external_media_active"] is False
    assert attrs["external_owner"] is None
    assert attrs["last_video_block_reason"] is None
    assert camera._bridge_available is False
    assert camera._attr_is_streaming is False
    assert camera._bridge_status["media_owner"] == "idle"
    assert camera._bridge_status["external_media_active"] is False


def test_doorbell_camera_closes_ring_webrtc_session_on_video_closed_event() -> None:
    class _Peer:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    class _FakeHass:
        def __init__(self) -> None:
            self.tasks: list[Any] = []

        def async_create_task(self, coro: Any) -> Any:
            task = asyncio.create_task(coro)
            self.tasks.append(task)
            return task

    async def _run() -> tuple[C300XDoorbellCamera, _Peer]:
        entry = _FakeEntry()
        camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
        hass = _FakeHass()
        camera.hass = hass  # type: ignore[assignment]
        peer = _Peer()
        session = _NativeWebRTCSession(peer)
        session.ring_call = True
        camera._webrtc_sessions["ring-session"] = session

        camera._handle_agent_event(
            SimpleNamespace(
                data={
                    "entry_id": entry.entry_id,
                    "event_key": "doorbell_media_closed",
                }
            )
        )
        await asyncio.gather(*hass.tasks)
        return camera, peer

    camera, peer = asyncio.run(_run())

    assert "ring-session" not in camera._webrtc_sessions
    assert peer.closed is True
    assert camera._entry.runtime_data.api.stop_calls == 0


def test_doorbell_camera_applies_home_call_answered_event_without_polling() -> None:
    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    event = SimpleNamespace(
        data={
            "entry_id": entry.entry_id,
            "event_key": "home_call_answered",
            "home_call": {
                "running": True,
                "active": True,
                "answered": True,
                "rtp_proxy": True,
                "target_audio_port": 62012,
                "rtp_packets": 4,
                "rtcp_packets": 1,
            },
        }
    )

    camera._handle_agent_event(event)

    attrs = camera.extra_state_attributes
    assert attrs["video_owner"] == "home_call"
    assert attrs["video_window_available"] is False
    assert camera._audio_stream_path == "/doorbell"
    assert camera._bridge_status["media_owner"] == "home_call"
    assert camera._bridge_status["home_call_running"] is True
    assert camera._bridge_status["home_call_active"] is True
    assert camera._bridge_status["home_call_answered"] is True
    assert camera._bridge_status["home_call_target_audio_port"] == 62012
    assert entry.runtime_data.api.home_call_status_calls == 0


def test_doorbell_camera_applies_home_call_ended_event_without_polling() -> None:
    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera._bridge_available = True
    camera._video_owner = "home_call"
    camera._audio_stream_path = "/doorbell"
    camera._bridge_status = {
        "media_owner": "home_call",
        "home_call_running": True,
        "home_call_active": True,
        "home_call_answered": True,
        "home_call_rtp_proxy": True,
        "home_call_target_audio_port": 62012,
    }
    event = SimpleNamespace(
        data={
            "entry_id": entry.entry_id,
            "event_key": "home_call_ended",
            "home_call": {
                "rtp_packets": 69,
                "rtcp_packets": 2,
            },
        }
    )

    camera._handle_agent_event(event)

    attrs = camera.extra_state_attributes
    assert attrs["video_owner"] == "idle"
    assert attrs["video_window_available"] is False
    assert camera._audio_stream_path is None
    assert camera._bridge_status["media_owner"] == "idle"
    assert camera._bridge_status["home_call_running"] is False
    assert camera._bridge_status["home_call_active"] is False
    assert camera._bridge_status["home_call_answered"] is False
    assert camera._bridge_status["home_call_rtp_proxy"] is False
    assert camera._bridge_status["home_call_target_audio_port"] == 0
    assert camera._bridge_status["home_call_rtp_packets"] == 69
    assert camera._bridge_status["home_call_rtcp_packets"] == 2
    assert entry.runtime_data.api.home_call_status_calls == 0


def test_doorbell_camera_home_call_ended_closes_home_call_webrtc_without_stop() -> None:
    class _FakeHass:
        def __init__(self) -> None:
            self.tasks: list[asyncio.Task[Any]] = []

        def async_create_task(self, coro: Any) -> asyncio.Task[Any]:
            task = asyncio.create_task(coro)
            self.tasks.append(task)
            return task

    class _Peer:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    class _Player:
        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    async def _run() -> None:
        entry = _FakeEntry()
        camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
        hass = _FakeHass()
        camera.hass = hass
        camera._video_owner = "home_call"
        sent_messages: list[Any] = []
        peer = _Peer()
        player = _Player()
        session = _NativeWebRTCSession(
            peer,
            owner="home_call",
            send_message=sent_messages.append,
        )
        session.player = player
        camera._webrtc_sessions["session-home"] = session

        camera._handle_agent_event(
            SimpleNamespace(
                data={
                    "entry_id": entry.entry_id,
                    "event_key": "home_call_ended",
                    "home_call": {"rtp_packets": 9, "rtcp_packets": 1},
                }
            )
        )

        assert len(hass.tasks) == 1
        await hass.tasks[0]

        assert "session-home" not in camera._webrtc_sessions
        assert peer.closed is True
        assert player.stopped is True
        assert sent_messages == [{"type": "closed", "reason": "home_call_ended"}]
        assert entry.runtime_data.api.home_call_stop_calls == 0
        assert entry.runtime_data.api.stop_calls == 0
        attrs = camera.extra_state_attributes
        assert attrs["video_owner"] == "idle"
        assert camera._bridge_status["home_call_active"] is False

    asyncio.run(_run())


def test_doorbell_camera_home_call_ended_keeps_other_video_owner() -> None:
    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera._bridge_available = True
    camera._video_owner = "ring"
    camera._video_window_available = True
    camera._video_stream_path = "/doorbell-video"
    camera._audio_stream_path = "/doorbell"
    camera._bridge_status = {
        "media_owner": "ring",
        "home_call_running": True,
        "home_call_active": True,
    }
    event = SimpleNamespace(
        data={
            "entry_id": entry.entry_id,
            "event_key": "home_call_ended",
            "home_call": {
                "rtp_packets": 1,
                "rtcp_packets": 0,
            },
        }
    )

    camera._handle_agent_event(event)

    attrs = camera.extra_state_attributes
    assert attrs["video_owner"] == "ring"
    assert attrs["video_window_available"] is True
    assert camera._video_stream_path == "/doorbell-video"
    assert camera._audio_stream_path == "/doorbell"
    assert camera._bridge_status["media_owner"] == "ring"
    assert camera._bridge_status["home_call_running"] is False
    assert camera._bridge_status["home_call_active"] is False
    assert entry.runtime_data.api.home_call_status_calls == 0


def test_doorbell_camera_does_not_infer_runtime_video_window() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            event_state=_FakeEventState(
                video_available=True,
            )
        )
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    attrs = camera.extra_state_attributes

    assert attrs["video_window_available"] is False
    assert "video_active_until" not in attrs


def test_doorbell_audio_gain_is_applied_to_decoded_webrtc_frames() -> None:
    import numpy as np

    class _FakeFormat:
        name = "s16"

    class _FakeLayout:
        name = "mono"

    class _FakeAudioFrame:
        format = _FakeFormat()
        layout = _FakeLayout()
        sample_rate = 8000
        pts = 160
        time_base = "time-base"

        def __init__(self, samples: Any) -> None:
            self.samples = samples

        def to_ndarray(self) -> Any:
            return self.samples

    class _FakeAudioFrameFactory:
        @staticmethod
        def from_ndarray(samples: Any, *, format: str, layout: str) -> Any:
            assert format == "s16"
            assert layout == "mono"
            return _FakeAudioFrame(samples)

    frame = _FakeAudioFrame(np.array([[1000, -1000, 20000]], dtype=np.int16))

    boosted = _apply_audio_gain(
        SimpleNamespace(AudioFrame=_FakeAudioFrameFactory),
        frame,
        DOORSTATION_AUDIO_GAIN,
    )

    assert boosted is not frame
    assert boosted.to_ndarray().tolist() == [[3000, -3000, 32767]]
    assert boosted.sample_rate == frame.sample_rate
    assert boosted.pts == frame.pts
    assert boosted.time_base == frame.time_base


async def _rtsp_options_server(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    with suppress(Exception):
        await reader.read(256)
        writer.write(
            b"RTSP/1.0 200 OK\r\n"
            b"CSeq: 1\r\n"
            b"Public: OPTIONS, DESCRIBE, SETUP, PLAY\r\n"
            b"Content-Length: 0\r\n\r\n"
        )
        await writer.drain()
    writer.close()
    with suppress(Exception):
        await writer.wait_closed()
