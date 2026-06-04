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
    STILL_IMAGE_BYTES,
    STILL_IMAGE_CONTENT_TYPE,
    TALKBACK_CODEC,
    TALKBACK_RTP_PAYLOAD_TYPE,
    C300XDoorbellCamera,
    _filter_link_local_sdp_candidates,
    _NativeWebRTCSession,
    _new_restarting_rtsp_tracks,
    _preload_dns_mdns_modules,
)
from custom_components.bticino_c300x.video import resolve_doorbell_camera_entity_id


@dataclass
class _FakeEventState:
    video_stream_path: str | None = None
    video_available: bool = False
    video_active_until: str | None = None
    last_event_data: dict[str, Any] = field(default_factory=dict)


class _FakeApi:
    def __init__(self) -> None:
        self.activate_calls: list[bool] = []

    async def async_doorbell_video_status(self) -> dict[str, Any]:
        return {
            "available": True,
            "window_available": True,
            "active_until": "2099-05-26T12:00:30+00:00",
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


@dataclass
class _FakeRuntimeData:
    event_state: Any = field(default_factory=_FakeEventState)
    api: Any = field(default_factory=_FakeApi)
    connection_state: Any = field(
        default_factory=lambda: SimpleNamespace(available=True),
    )


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

    def _fake_import(module_name: str) -> object:
        imported.append(module_name)
        if module_name == "dns.rdtypes.ANY.TXT":
            raise ImportError(module_name)
        return object()

    _preload_dns_mdns_modules(_fake_import)

    assert imported == [
        "dns.rdtypes.IN.A",
        "dns.rdtypes.IN.AAAA",
        "dns.rdtypes.IN.PTR",
        "dns.rdtypes.ANY.SRV",
        "dns.rdtypes.ANY.TXT",
    ]


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
    assert "async_on_webrtc_candidate" in C300XDoorbellCamera.__dict__


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


def test_doorbell_camera_exposes_safe_audio_paths_from_bridge_status() -> None:
    camera = C300XDoorbellCamera(_FakeEntry())  # type: ignore[arg-type]
    camera._bridge_status = {
        "audio_stream_path": "/doorbell",
        "recorder_stream_path": "/doorbell-recorder",
        "talkback_supported": True,
        "talkback_running": True,
        "talkback_payload_type": TALKBACK_RTP_PAYLOAD_TYPE,
        "talkback_codec": TALKBACK_CODEC,
    }

    attrs = camera.extra_state_attributes

    assert attrs["stream_path"] == "/doorbell-video"
    assert attrs["audio_stream_path"] == "/doorbell"
    assert attrs["recorder_stream_path"] == "/doorbell-recorder"
    assert attrs["talkback_supported"] is True
    assert attrs["talkback_requires_https"] is True
    assert attrs["talkback_proxy_running"] is True
    assert attrs["talkback_payload_type"] == TALKBACK_RTP_PAYLOAD_TYPE
    assert attrs["talkback_codec"] == TALKBACK_CODEC
    assert attrs["talkback_last_error"] is None


def test_doorbell_camera_refresh_applies_bridge_audio_metadata() -> None:
    camera = C300XDoorbellCamera(_FakeEntry())  # type: ignore[arg-type]

    asyncio.run(camera.async_update())
    attrs = camera.extra_state_attributes

    assert attrs["video_available"] is True
    assert attrs["video_window_available"] is True
    assert attrs["video_active_until"] == "2099-05-26T12:00:30+00:00"
    assert attrs["audio_stream_path"] == "/doorbell"
    assert attrs["recorder_stream_path"] == "/doorbell-recorder"
    assert attrs["talkback_supported"] is True
    assert attrs["talkback_proxy_running"] is True


def test_doorbell_camera_reports_talkback_session_state() -> None:
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
    assert attrs["talkback_requested"] is True
    assert attrs["talkback_active"] is True
    assert attrs["talkback_packets_sent"] == 2
    assert attrs["talkback_last_error"] == "CodecUnavailable"


def test_webrtc_candidate_waits_for_remote_description() -> None:
    class _FakePeer:
        def __init__(self) -> None:
            self.candidates: list[Any] = []

        async def addIceCandidate(self, candidate: Any) -> None:
            self.candidates.append(candidate)

    class _Candidate:
        def to_dict(self) -> dict[str, Any]:
            return {
                "candidate": "candidate:1 1 udp 2130706431 192.0.2.10 5000 typ host",
                "sdpMid": "0",
                "sdpMLineIndex": 0,
            }

    async def _run() -> tuple[_NativeWebRTCSession, _FakePeer]:
        camera = C300XDoorbellCamera(_FakeEntry())  # type: ignore[arg-type]
        peer = _FakePeer()
        session = _NativeWebRTCSession(peer)
        camera._webrtc_sessions["session-1"] = session
        aiortc_modules = SimpleNamespace(
            candidate_from_sdp=lambda candidate: SimpleNamespace(candidate=candidate)
        )

        async def _load_aiortc_modules() -> SimpleNamespace:
            return aiortc_modules

        camera._async_load_aiortc_modules = _load_aiortc_modules  # type: ignore[method-assign]
        await camera.async_on_webrtc_candidate("session-1", _Candidate())

        assert peer.candidates == []
        assert len(session.pending_candidates) == 1

        session.remote_description_ready = True
        await camera._async_flush_webrtc_candidates(session, aiortc_modules)
        return session, peer

    session, peer = asyncio.run(_run())

    assert session.pending_candidates == []
    assert len(peer.candidates) == 1
    assert peer.candidates[0].sdpMid == "0"
    assert peer.candidates[0].sdpMLineIndex == 0


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
    assert entry.runtime_data.api.activate_calls == [True]


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

    async def _run() -> tuple[bytes, dict[str, Any]]:
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.bind(("127.0.0.1", 0))
        udp.setblocking(False)
        monkeypatch.setattr(camera_module, "TALKBACK_RTP_PORT", udp.getsockname()[1])
        entry = _FakeEntry(data={"agent_host": "127.0.0.1"})
        camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
        camera._bridge_status = {"talkback_supported": True}
        camera._webrtc_sessions["session-1"] = _NativeWebRTCSession(SimpleNamespace())
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
            return packet, camera.extra_state_attributes
        finally:
            udp.close()

    packet, attrs = asyncio.run(_run())
    version, marker_payload, sequence, _timestamp, _ssrc = struct.unpack(
        "!BBHII",
        packet[:12],
    )

    assert version == 0x80
    assert marker_payload == 0x80 | TALKBACK_RTP_PAYLOAD_TYPE
    assert sequence >= 0
    assert packet[12:] == b"speex-payload"
    assert attrs["talkback_packets_sent"] == 1
    assert attrs["talkback_active"] is False
    assert attrs["talkback_last_error"] is None


def test_doorbell_camera_reports_talkback_host_errors() -> None:
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

    assert attrs["talkback_last_error"] == "agent_host_missing"


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
            "video_active_until": "2099-05-27T12:00:00+00:00",
            "stream_path": "/doorbell-video",
        }
    )

    camera._handle_agent_event(event)

    attrs = camera.extra_state_attributes
    assert attrs["video_available"] is True
    assert attrs["video_window_available"] is True
    assert attrs["video_active_until"] == "2099-05-27T12:00:00+00:00"


def test_doorbell_camera_clears_state_on_video_closed_event() -> None:
    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera._video_window_available = True
    camera._video_active_until = "2099-05-27T12:00:00+00:00"
    camera._bridge_available = True

    event = SimpleNamespace(
        data={"entry_id": entry.entry_id, "event_key": "doorbell_media_closed"}
    )
    camera._handle_agent_event(event)

    attrs = camera.extra_state_attributes
    assert attrs["video_available"] is False
    assert attrs["video_window_available"] is False
    assert attrs["video_active_until"] is None


def test_doorbell_camera_ignores_expired_runtime_video_window() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            event_state=_FakeEventState(
                video_available=True,
                video_active_until="2020-01-01T00:00:00+00:00",
            )
        )
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    attrs = camera.extra_state_attributes

    assert attrs["video_window_available"] is False
    assert attrs["video_active_until"] is None


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
