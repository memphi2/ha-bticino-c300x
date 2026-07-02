from __future__ import annotations

import asyncio
import socket
import struct
import sys
import types
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

if "homeassistant.components.camera" not in sys.modules:
    homeassistant = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    camera = types.ModuleType("homeassistant.components.camera")
    stream = types.ModuleType("homeassistant.components.stream")
    config_entries = types.ModuleType("homeassistant.config_entries")
    const = types.ModuleType("homeassistant.const")
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

    class ServiceValidationError(Exception):  # pragma: no cover - import-time stub only
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args)
            self.translation_key = kwargs.get("translation_key")
            self.translation_domain = kwargs.get("translation_domain")
            self.translation_placeholders = kwargs.get(
                "translation_placeholders",
            )

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
    const.ATTR_ENTITY_ID = "entity_id"
    core.HomeAssistant = HomeAssistant
    core.callback = lambda func: func
    config_validation.config_entry_only_config_schema = lambda _domain: dict
    exceptions.HomeAssistantError = Exception
    exceptions.ServiceValidationError = ServiceValidationError
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
    sys.modules["homeassistant.const"] = const
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

from homeassistant.exceptions import HomeAssistantError

from custom_components.bticino_c300x import camera as camera_module
from custom_components.bticino_c300x import media_watchdog
from custom_components.bticino_c300x.camera import (
    STILL_IMAGE_BYTES,
    STILL_IMAGE_CONTENT_TYPE,
    TALKBACK_CODEC,
    TALKBACK_RTP_PAYLOAD_TYPE,
    C300XDoorbellCamera,
    _NativeWebRTCSession,
    _preload_dns_mdns_modules,
    async_setup_entry,
)
from custom_components.bticino_c300x.camera_media import talkback as talkback_module
from custom_components.bticino_c300x.camera_media.state_machine import MediaState
from custom_components.bticino_c300x.const import CONF_VIDEO_ENABLED
from custom_components.bticino_c300x.use_cases.doorbell_video import (
    DoorbellVideoUseCase,
)
from custom_components.bticino_c300x.use_cases.home_call import HomeCallUseCase
from custom_components.bticino_c300x.use_cases.ring_call import RingCallUseCase
from custom_components.bticino_c300x.video import resolve_doorbell_camera_entity_id

dispatcher_signals: list[tuple[str, str]] = []


def _stub_rtsp_ready(
    camera: C300XDoorbellCamera,
    ready_urls: list[str] | None = None,
) -> None:
    async def _wait_for_rtsp_ready(stream_url: str, **_kwargs: Any) -> None:
        if ready_urls is not None:
            ready_urls.append(stream_url)

    camera._async_wait_for_rtsp_ready = _wait_for_rtsp_ready  # type: ignore[method-assign]
    camera._rtsp_orchestrator.async_wait_for_rtsp_ready = _wait_for_rtsp_ready  # type: ignore[method-assign]


@dataclass
class _FakeEventState:
    video_stream_path: str | None = None
    video_available: bool = False
    last_event_data: dict[str, Any] = field(default_factory=dict)


class _FakeApi:
    def __init__(self) -> None:
        self.activate_calls: list[bool] = []
        self.stop_calls = 0
        self.hangup_calls = 0
        self.home_call_start_calls: list[int | None] = []
        self.home_call_stop_calls = 0
        self.home_call_status_calls = 0
        self.reload_gui_calls = 0

    async def async_doorbell_video_status(self) -> dict[str, Any]:
        return {
            "available": True,
            "window_available": True,
            "stream_path": "/doorbell-video",
            "audio_stream_path": "/doorbell",
            "recorder_stream_path": "/doorbell-recorder",
            "bridge": {
                "running": True,
                "audio_codec": "PCMU/8000",
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

    async def async_hangup_doorbell_call(self) -> dict[str, Any]:
        self.hangup_calls += 1
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

    async def async_reload_gui(self) -> dict[str, Any]:
        self.reload_gui_calls += 1
        return {"ok": True}


@dataclass
class _FakeRuntimeData:
    event_state: Any = field(default_factory=_FakeEventState)
    api: Any = field(default_factory=_FakeApi)
    connection_state: Any = field(
        default_factory=lambda: SimpleNamespace(available=True),
    )
    capabilities: dict[str, Any] = field(
        default_factory=lambda: {"doorbell_video": {"supported": True}},
    )
    agent_cpu_watchdog: Any = field(default_factory=media_watchdog.AgentCpuWatchdog)
    agent_cpu_watchdog_task: Any = None
    prepare_doorbell_video_stop: Any = None
    prepare_home_call_stop: Any = None


def _webrtc_message_value(message: Any, key: str) -> Any:
    if isinstance(message, dict):
        return message.get(key)
    if hasattr(message, "as_dict"):
        return message.as_dict().get(key)
    return getattr(message, key, None)


class _FakeWebRTCProvider:
    domain = "go2rtc"

    def __init__(self) -> None:
        self.support_sources: list[str] = []
        self.offer_sources: list[str] = []
        self.offers: list[tuple[str, str]] = []
        self.candidates: list[tuple[str, Any]] = []
        self.closed: list[str] = []

    async def async_handle_async_webrtc_offer(
        self,
        camera: C300XDoorbellCamera,
        offer_sdp: str,
        session_id: str,
        send_message: Any,
    ) -> None:
        self.offer_sources.append(await camera.stream_source())
        self.offers.append((session_id, offer_sdp))
        send_message({"type": "answer", "sdp": "v=0\r\n"})

    async def async_on_webrtc_candidate(
        self,
        session_id: str,
        candidate: Any,
    ) -> None:
        self.candidates.append((session_id, candidate))

    def async_close_session(self, session_id: str) -> None:
        self.closed.append(session_id)


def _install_fake_webrtc_provider(
    monkeypatch: pytest.MonkeyPatch,
    provider: _FakeWebRTCProvider | None,
) -> None:
    async def _provider(hass: Any, camera: C300XDoorbellCamera) -> Any:
        if provider is not None:
            provider.support_sources.append(await camera.stream_source())
        return provider

    monkeypatch.setattr(
        camera_module,
        "_async_get_supported_webrtc_provider",
        _provider,
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


def test_camera_setup_entry_adds_entity_only_when_capability_is_supported() -> None:
    async def _run() -> None:
        unsupported = _FakeEntry()
        unsupported.runtime_data.capabilities = {"doorbell_video": {"supported": False}}
        supported = _FakeEntry()
        supported.runtime_data.capabilities = {"doorbell_video": {"supported": True}}
        unsupported_entities: list[Any] = []
        supported_entities: list[Any] = []

        await async_setup_entry(
            SimpleNamespace(),  # type: ignore[arg-type]
            unsupported,  # type: ignore[arg-type]
            unsupported_entities.extend,
        )
        await async_setup_entry(
            SimpleNamespace(),  # type: ignore[arg-type]
            supported,  # type: ignore[arg-type]
            supported_entities.extend,
        )

        assert unsupported_entities == []
        assert len(supported_entities) == 1
        assert isinstance(supported_entities[0], C300XDoorbellCamera)

    asyncio.run(_run())


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
            return SimpleNamespace(A=1, AAAA=28, PTR=12, SRV=33, TXT=16)
        return object()

    _preload_dns_mdns_modules(_fake_import)

    assert imported == [
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
        "dns.rdata",
        "dns.rdataclass",
        "dns.rdatatype",
    ]
    assert generic_rdata_classes == [
        (32769, 1),
        (32769, 28),
        (32769, 12),
        (32769, 33),
        (32769, 16),
        (32769, 47),
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
    session = _NativeWebRTCSession(peer)
    camera._webrtc_sessions["session-1"] = session
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


def test_doorbell_camera_exposes_only_user_facing_media_attributes() -> None:
    entry = _FakeEntry()
    entry.runtime_data.device_user_status = {
        "homeassistant_user_present": True,
        "account_label": "Home Assistant Test",
    }
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera._video_window_available = True
    camera._video_owner = "ring"
    camera._external_media_active = True
    camera._external_owner = "external_client"
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
        "media_state": "unknown",
        "media_primary_action": "refresh",
        "video_window_available": True,
        "video_owner": "ring",
        "external_media_active": True,
        "external_owner": "external_client",
        "last_video_block_reason": "external_session_active",
            "talkback_supported": True,
            "media_user": {
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


def test_doorbell_camera_refresh_failure_marks_entity_unavailable() -> None:
    class _FailingApi(_FakeApi):
        async def async_doorbell_video_status(self) -> dict[str, Any]:
            raise RuntimeError("offline")

    entry = _FakeEntry(runtime_data=_FakeRuntimeData(api=_FailingApi()))
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    asyncio.run(camera.async_update())

    assert camera._bridge_available is False
    assert camera.available is False


def test_doorbell_camera_webrtc_offer_reports_missing_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = C300XDoorbellCamera(_FakeEntry())  # type: ignore[arg-type]
    camera.hass = SimpleNamespace()
    sent_messages: list[Any] = []
    _install_fake_webrtc_provider(monkeypatch, None)

    asyncio.run(
        camera.async_handle_async_webrtc_offer(
            "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n",
            "session-1",
            sent_messages.append,
        )
    )

    assert sent_messages == [
        {
            "type": "error",
            "code": "bticino_webrtc_unavailable",
            "message": (
                "No Home Assistant WebRTC provider is available for the C300X RTSP stream"
            ),
        }
    ]


def test_doorbell_camera_initial_refresh_sets_idle_stream_action() -> None:
    class _IdleApi(_FakeApi):
        async def async_doorbell_video_status(self) -> dict[str, Any]:
            return {
                "available": True,
                "window_available": False,
                "media_owner": "idle",
                "stream_path": "/doorbell-video",
                "audio_stream_path": "/doorbell",
                "recorder_stream_path": "/doorbell-recorder",
                "bridge": {
                    "clients": 0,
                    "media_owner": "idle",
                    "running": True,
                    "audio_codec": "PCMU/8000",
                    "talkback_supported": True,
                    "talkback_running": True,
                    "talkback_payload_type": 97,
                    "talkback_codec": "speex/8000",
                },
            }

    class _FakeBus:
        def async_listen(self, *_args: Any):
            return lambda: None

    class _FakeHass:
        bus = _FakeBus()

    entry = _FakeEntry()
    entry.runtime_data.api = _IdleApi()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera.hass = _FakeHass()  # type: ignore[assignment]
    camera.async_on_remove = lambda _remove: None  # type: ignore[method-assign]
    camera.async_write_ha_state = lambda: None  # type: ignore[method-assign]

    asyncio.run(camera.async_added_to_hass())

    assert camera._last_media_state is MediaState.IDLE
    assert camera._last_media_decision.primary_action == "start_stream"
    assert camera.extra_state_attributes["media_primary_action"] == "start_stream"


def test_doorbell_camera_closed_event_clears_stale_ring_facts() -> None:
    camera = C300XDoorbellCamera(_FakeEntry())  # type: ignore[arg-type]
    camera._video_owner = "ring"
    camera._video_window_available = True
    camera._attr_is_streaming = True
    camera._bridge_status = {
        "media_owner": "ring",
        "media_active": True,
        "ring_call_active": True,
        "ring_media_active": True,
        "ring_audio_active": True,
        "ring_answer_requested": True,
        "ring_answered": True,
        "ring_hangup_requested": True,
        "unanswered_ring_call": True,
        "call_active": True,
        "clients": 1,
    }

    camera._clear_video_window()

    assert camera._last_media_state is MediaState.IDLE
    assert camera._last_media_decision.primary_action == "start_stream"
    assert camera._bridge_status["ring_audio_active"] is False
    assert camera._bridge_status["ring_answered"] is False
    assert camera._bridge_status["unanswered_ring_call"] is False
    assert camera._bridge_status["clients"] == 0


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


def test_doorbell_camera_registers_explicit_stop_hook() -> None:
    class _Bus:
        def async_listen(self, *_args: Any, **_kwargs: Any) -> Any:
            return lambda: None

    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera.hass = SimpleNamespace(bus=_Bus())
    camera.async_on_remove = lambda _remove: None  # type: ignore[method-assign]
    camera.async_write_ha_state = lambda: None  # type: ignore[method-assign]

    asyncio.run(camera.async_added_to_hass())

    assert entry.runtime_data.prepare_doorbell_video_stop is not None


def test_doorbell_video_stop_closes_local_webrtc_before_agent_stop() -> None:
    order: list[str] = []

    class _Peer:
        async def close(self) -> None:
            order.append("peer_close")

    class _Player:
        def stop(self) -> None:
            order.append("player_stop")

    class _Api(_FakeApi):
        async def async_stop_doorbell_video(self) -> dict[str, Any]:
            order.append("agent_stop")
            return await super().async_stop_doorbell_video()

    entry = _FakeEntry(
        data={CONF_VIDEO_ENABLED: True},
        runtime_data=_FakeRuntimeData(api=_Api()),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera.hass = SimpleNamespace()
    session = _NativeWebRTCSession(_Peer(), owner="doorbell")
    session.player = _Player()
    camera._webrtc_sessions["session-1"] = session
    entry.runtime_data.prepare_doorbell_video_stop = camera.async_prepare_doorbell_video_stop

    asyncio.run(DoorbellVideoUseCase(entry).stop())

    assert "session-1" not in camera._webrtc_sessions
    assert entry.runtime_data.api.stop_calls == 1
    assert entry.runtime_data.api.activate_calls == []
    assert order == ["player_stop", "peer_close", "agent_stop"]


def test_ring_call_hangup_closes_local_webrtc_before_agent_hangup() -> None:
    order: list[str] = []

    class _Peer:
        async def close(self) -> None:
            order.append("peer_close")

    class _Player:
        def stop(self) -> None:
            order.append("player_stop")

    class _Api(_FakeApi):
        async def async_hangup_doorbell_call(self) -> dict[str, Any]:
            order.append("agent_hangup")
            return await super().async_hangup_doorbell_call()

    entry = _FakeEntry(
        data={CONF_VIDEO_ENABLED: True},
        runtime_data=_FakeRuntimeData(
            api=_Api(),
            capabilities={"doorbell_call": {"supported": True}},
        ),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera.hass = SimpleNamespace()
    session = _NativeWebRTCSession(_Peer(), owner="doorbell")
    session.ring_call = True
    session.player = _Player()
    camera._webrtc_sessions["ring-session"] = session
    entry.runtime_data.prepare_doorbell_video_stop = camera.async_prepare_doorbell_video_stop

    asyncio.run(RingCallUseCase(entry).hangup())

    assert "ring-session" not in camera._webrtc_sessions
    assert entry.runtime_data.api.hangup_calls == 1
    assert entry.runtime_data.api.activate_calls == []
    assert entry.runtime_data.api.stop_calls == 0
    assert order == ["player_stop", "peer_close", "agent_hangup"]


def test_ring_call_hangup_closes_multiple_local_webrtc_sessions_in_parallel() -> None:
    order: list[str] = []

    class _Peer:
        def __init__(self, name: str) -> None:
            self.name = name

        async def close(self) -> None:
            order.append(f"{self.name}:peer_start")
            await asyncio.sleep(0)
            order.append(f"{self.name}:peer_end")

    class _Player:
        def __init__(self, name: str) -> None:
            self.name = name

        def stop(self) -> None:
            order.append(f"{self.name}:player_stop")

    class _Api(_FakeApi):
        async def async_hangup_doorbell_call(self) -> dict[str, Any]:
            order.append("agent_hangup")
            return await super().async_hangup_doorbell_call()

    entry = _FakeEntry(
        data={CONF_VIDEO_ENABLED: True},
        runtime_data=_FakeRuntimeData(
            api=_Api(),
            capabilities={"doorbell_call": {"supported": True}},
        ),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera.hass = SimpleNamespace()
    for name in ("first", "second"):
        session = _NativeWebRTCSession(
            _Peer(name),
            owner="doorbell",
            send_message=lambda message, session_name=name: order.append(
                f"{session_name}:notify:{message['reason']}"
            ),
        )
        session.ring_call = True
        session.player = _Player(name)
        camera._webrtc_sessions[name] = session
    entry.runtime_data.prepare_doorbell_video_stop = camera.async_prepare_doorbell_video_stop

    asyncio.run(RingCallUseCase(entry).hangup())

    assert camera._webrtc_sessions == {}
    assert entry.runtime_data.api.hangup_calls == 1
    assert order.index("second:notify:doorbell_video_stopped") < order.index(
        "first:peer_end"
    )
    assert order.index("agent_hangup") > order.index("second:peer_end")


def test_home_call_stop_closes_local_webrtc_before_agent_stop() -> None:
    order: list[str] = []

    class _Peer:
        async def close(self) -> None:
            order.append("peer_close")

    class _Player:
        def stop(self) -> None:
            order.append("player_stop")

    class _Api(_FakeApi):
        async def async_stop_home_call(self) -> dict[str, Any]:
            order.append("agent_home_stop")
            return await super().async_stop_home_call()

    entry = _FakeEntry(
        data={CONF_VIDEO_ENABLED: True},
        runtime_data=_FakeRuntimeData(
            api=_Api(),
            capabilities={"home_call": {"supported": True}},
        ),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera.hass = SimpleNamespace()
    session = _NativeWebRTCSession(_Peer(), owner="home_call")
    session.player = _Player()
    camera._webrtc_sessions["home-session"] = session
    entry.runtime_data.prepare_home_call_stop = camera.async_prepare_home_call_stop

    asyncio.run(HomeCallUseCase(entry).stop())

    assert "home-session" not in camera._webrtc_sessions
    assert entry.runtime_data.api.home_call_stop_calls == 1
    assert entry.runtime_data.api.activate_calls == []
    assert entry.runtime_data.api.stop_calls == 0
    assert order == ["player_stop", "peer_close", "agent_home_stop"]


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


def test_doorbell_camera_counts_shared_ring_rtsp_as_one_local_session() -> None:
    camera = C300XDoorbellCamera(_FakeEntry())  # type: ignore[arg-type]
    first = _NativeWebRTCSession(SimpleNamespace())
    first.player = SimpleNamespace(resource_id="ring:entry-1")
    second = _NativeWebRTCSession(SimpleNamespace())
    second.player = SimpleNamespace(resource_id="ring:entry-1")
    standalone = _NativeWebRTCSession(SimpleNamespace())
    standalone.player = object()
    camera._webrtc_sessions["first-ring-viewer"] = first
    camera._webrtc_sessions["second-ring-viewer"] = second
    camera._webrtc_sessions["on-demand-viewer"] = standalone

    assert camera._active_local_media_sessions() == 2


def test_doorbell_camera_renews_shared_ring_resource_once() -> None:
    class _RingApi(_FakeApi):
        def __init__(self) -> None:
            super().__init__()
            self.status_calls = 0

        async def async_doorbell_video_status(self) -> dict[str, Any]:
            self.status_calls += 1
            status = await super().async_doorbell_video_status()
            status["media_owner"] = "ring"
            status["bridge"] = {
                **status["bridge"],
                "media_owner": "ring",
                "ring_call_active": True,
                "ring_media_active": True,
            }
            return status

    peer = SimpleNamespace(
        connectionState="connected",
        iceConnectionState="completed",
        signalingState="stable",
    )
    api = _RingApi()
    camera = C300XDoorbellCamera(  # type: ignore[arg-type]
        _FakeEntry(runtime_data=_FakeRuntimeData(api=api))
    )
    first = _NativeWebRTCSession(peer)
    first.player = SimpleNamespace(resource_id="ring:entry-1")
    first.ring_call = True
    second = _NativeWebRTCSession(peer)
    second.player = SimpleNamespace(resource_id="ring:entry-1")
    second.ring_call = True
    camera._webrtc_sessions["first-ring-viewer"] = first
    camera._webrtc_sessions["second-ring-viewer"] = second

    asyncio.run(camera._async_renew_webrtc_resource_once("ring:entry-1"))

    assert api.status_calls == 1
    assert set(camera._webrtc_sessions) == {"first-ring-viewer", "second-ring-viewer"}


def test_doorbell_camera_schedules_one_renewal_task_per_shared_resource(
    monkeypatch,
) -> None:  # noqa: ANN001
    monkeypatch.setattr(camera_module, "WEBRTC_RENEW_SECONDS", 60)

    class _Hass:
        def __init__(self) -> None:
            self.tasks: list[asyncio.Task[Any]] = []

        def async_create_task(self, coro: Any) -> asyncio.Task[Any]:
            task = asyncio.create_task(coro)
            self.tasks.append(task)
            return task

    async def _run() -> None:
        camera = C300XDoorbellCamera(_FakeEntry())  # type: ignore[arg-type]
        camera.hass = _Hass()  # type: ignore[assignment]
        first = _NativeWebRTCSession(SimpleNamespace())
        first.player = SimpleNamespace(resource_id="ring:entry-1")
        second = _NativeWebRTCSession(SimpleNamespace())
        second.player = SimpleNamespace(resource_id="ring:entry-1")
        camera._webrtc_sessions["first-ring-viewer"] = first
        camera._webrtc_sessions["second-ring-viewer"] = second

        camera._schedule_webrtc_renewal("first-ring-viewer")
        camera._schedule_webrtc_renewal("second-ring-viewer")

        assert len(camera.hass.tasks) == 1
        assert set(camera._webrtc_resource_renew_tasks) == {"ring:entry-1"}
        camera.hass.tasks[0].cancel()
        await asyncio.gather(*camera.hass.tasks, return_exceptions=True)

    asyncio.run(_run())


def test_doorbell_camera_closing_unanswered_ring_preview_keeps_ring_media() -> None:
    class _RingPreviewApi(_FakeApi):
        async def async_doorbell_video_status(self) -> dict[str, Any]:
            status = await super().async_doorbell_video_status()
            status["media_owner"] = "ring"
            status["window_available"] = True
            status["bridge"] = {
                **status["bridge"],
                "media_owner": "ring",
                "ring_call_active": True,
                "ring_media_active": True,
                "unanswered_ring_call": True,
            }
            return status

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

    api = _RingPreviewApi()
    entry = _FakeEntry(runtime_data=_FakeRuntimeData(api=api))
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    peer = _Peer()
    player = _Player()
    session = _NativeWebRTCSession(peer, owner="ring")
    session.ring_preview = True
    session.player = player
    camera._webrtc_sessions["ring-preview"] = session

    asyncio.run(camera._async_close_webrtc_session("ring-preview"))

    assert peer.closed is True
    assert player.stopped is True
    assert api.stop_calls == 0
    assert api.hangup_calls == 0


def test_doorbell_camera_cpu_watchdog_closes_local_webrtc_sessions() -> None:
    class _Peer:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    class _Hass:
        def __init__(self) -> None:
            self.tasks: list[asyncio.Task] = []

        def async_create_task(self, coro: Any) -> asyncio.Task:
            task = asyncio.create_task(coro)
            self.tasks.append(task)
            return task

    async def _run() -> tuple[_FakeApi, C300XDoorbellCamera, _Peer]:
        api = _FakeApi()
        entry = _FakeEntry(runtime_data=_FakeRuntimeData(api=api))
        camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
        camera.hass = _Hass()  # type: ignore[assignment]
        peer = _Peer()
        camera._webrtc_sessions["session-1"] = _NativeWebRTCSession(peer)
        entry.runtime_data.agent_cpu_watchdog.tripped = True
        entry.runtime_data.agent_cpu_watchdog.last_percent = 96.0
        entry.runtime_data.agent_cpu_watchdog.last_reason = "agent_cpu_high"

        camera._handle_system_metrics_changed(entry.entry_id)
        await asyncio.gather(*camera.hass.tasks)
        return api, camera, peer

    api, camera, peer = asyncio.run(_run())

    assert api.stop_calls == 0
    assert api.reload_gui_calls == 1
    assert camera._webrtc_sessions == {}
    assert peer.closed is True
    assert camera._agent_cpu_watchdog.tripped is True
    assert camera._agent_cpu_watchdog.last_percent == 96.0


def test_doorbell_camera_webrtc_stream_url_does_not_pre_warm_video_call_path() -> None:
    entry = _FakeEntry(data={"agent_host": "127.0.0.1", "video_port": 6554})
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    source = camera._build_stream_url(audio=False)

    assert source == "rtsp://127.0.0.1:6554/doorbell-video"
    assert entry.runtime_data.api.activate_calls == []


def test_doorbell_camera_stream_source_warms_video_once() -> None:
    entry = _FakeEntry(data={"agent_host": "127.0.0.1", "video_port": 6554})
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    _stub_rtsp_ready(camera)

    async def _run() -> str:
        return await camera.stream_source()

    source = asyncio.run(_run())

    assert source == "rtsp://127.0.0.1:6554/doorbell-video"
    assert entry.runtime_data.api.activate_calls == [False]


def test_doorbell_camera_audio_stream_source_uses_audio_video_path() -> None:
    entry = _FakeEntry(data={"agent_host": "127.0.0.1", "video_port": 6554})
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    _stub_rtsp_ready(camera)

    async def _run() -> str:
        return await camera._async_prepare_rtsp_stream(audio=True)

    source = asyncio.run(_run())

    assert source == "rtsp://127.0.0.1:6554/doorbell"
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
    _stub_rtsp_ready(camera)

    async def _run() -> str:
        return await camera._async_prepare_rtsp_stream(audio=True)

    source = asyncio.run(_run())

    assert source == "rtsp://127.0.0.1:6554/doorbell"
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
    _stub_rtsp_ready(camera)

    async def _run() -> str:
        return await camera._async_prepare_rtsp_stream(audio=True)

    source = asyncio.run(_run())

    assert source == "rtsp://127.0.0.1:6554/doorbell"
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
    _stub_rtsp_ready(camera)

    async def _run() -> None:
        await camera._async_restart_video_reader(audio=True)

    asyncio.run(_run())

    assert api.activate_calls == []


def test_doorbell_camera_webrtc_offer_uses_provider_without_aiortc_fallback() -> None:
    source = Path("custom_components/bticino_c300x/camera.py").read_text(
        encoding="utf-8"
    )
    offer_block = source[
        source.index("async def _async_handle_webrtc_offer(")
        : source.index("async def _async_handle_provider_webrtc_offer(")
    ]

    assert "_async_handle_provider_webrtc_offer(" in offer_block
    assert "_async_load_aiortc_modules" not in offer_block
    assert "aiortc is not installed" not in offer_block


def test_doorbell_camera_rtsp_policy_blocks_second_on_demand_browser() -> None:
    class _BusyOnDemandApi(_FakeApi):
        async def async_doorbell_video_status(self) -> dict[str, Any]:
            status = await super().async_doorbell_video_status()
            status["media_owner"] = "agent"
            status["window_available"] = True
            status["bridge"] = {
                **status["bridge"],
                "media_owner": "agent",
                "clients": 1,
            }
            return status

    api = _BusyOnDemandApi()
    entry = _FakeEntry(
        data={"agent_host": "127.0.0.1", "video_port": 6554},
        runtime_data=_FakeRuntimeData(api=api),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera._webrtc_sessions["first"] = SimpleNamespace(player=object())  # type: ignore[assignment]
    _stub_rtsp_ready(camera)

    async def _run() -> None:
        await camera._async_prepare_rtsp_stream(audio=True)

    with pytest.raises(Exception, match="rtsp_consumer_active"):
        asyncio.run(_run())

    assert api.activate_calls == []
    assert camera._last_video_block_reason == "rtsp_consumer_active"


def test_doorbell_camera_on_demand_closes_stale_webrtc_before_admission() -> None:
    class _IdleApi(_FakeApi):
        async def async_doorbell_video_status(self) -> dict[str, Any]:
            status = await super().async_doorbell_video_status()
            status["media_owner"] = "idle"
            status["window_available"] = False
            status["bridge"] = {
                **status["bridge"],
                "media_owner": "idle",
                "clients": 0,
            }
            return status

    class _ClosedPeer:
        connectionState = "closed"
        iceConnectionState = "closed"
        signalingState = "closed"

        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    class _Player:
        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    api = _IdleApi()
    entry = _FakeEntry(
        data={"agent_host": "127.0.0.1", "video_port": 6554},
        runtime_data=_FakeRuntimeData(api=api),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    peer = _ClosedPeer()
    player = _Player()
    session = _NativeWebRTCSession(peer)
    session.player = player
    camera._webrtc_sessions["stale"] = session
    _stub_rtsp_ready(camera)

    stream_url = asyncio.run(camera._async_prepare_rtsp_stream(audio=False))

    assert stream_url == "rtsp://127.0.0.1:6554/doorbell-video"
    assert camera._webrtc_sessions == {}
    assert peer.closed is True
    assert player.stopped is True
    assert api.stop_calls == 1
    assert api.activate_calls == [False]


def test_doorbell_camera_on_demand_closes_finished_home_call_before_admission() -> None:
    class _IdleAfterHomeCallApi(_FakeApi):
        async def async_doorbell_video_status(self) -> dict[str, Any]:
            status = await super().async_doorbell_video_status()
            active = bool(self.activate_calls)
            status["media_owner"] = "agent" if active else "idle"
            status["window_available"] = active
            status["bridge"] = {
                **status["bridge"],
                "media_owner": "agent" if active else "idle",
                "home_call_running": False,
                "home_call_active": False,
                "home_call_answered": False,
                "clients": 0,
            }
            return status

        async def async_home_call_status(self) -> dict[str, Any]:
            self.home_call_status_calls += 1
            return {
                "available": True,
                "running": False,
                "active": False,
                "answered": False,
                "rtp_proxy": False,
                "target_audio_port": 0,
                "rtp_packets": 7,
                "rtcp_packets": 1,
            }

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

    api = _IdleAfterHomeCallApi()
    entry = _FakeEntry(
        data={"agent_host": "127.0.0.1", "video_port": 6554},
        runtime_data=_FakeRuntimeData(api=api),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera._video_owner = "home_call"
    camera._bridge_status = {
        "media_owner": "home_call",
        "home_call_running": True,
        "home_call_active": True,
        "home_call_answered": True,
    }
    sent_messages: list[Any] = []
    peer = _Peer()
    player = _Player()
    session = _NativeWebRTCSession(
        peer,
        owner="home_call",
        send_message=sent_messages.append,
    )
    session.player = player
    camera._webrtc_sessions["home-call"] = session
    _stub_rtsp_ready(camera)

    stream_url = asyncio.run(camera._async_prepare_rtsp_stream(audio=False))

    assert stream_url == "rtsp://127.0.0.1:6554/doorbell-video"
    assert camera._webrtc_sessions == {}
    assert peer.closed is True
    assert player.stopped is True
    assert sent_messages == [{"type": "closed", "reason": "home_call_ended"}]
    assert api.home_call_status_calls == 1
    assert api.home_call_stop_calls == 0
    assert api.stop_calls == 0
    assert api.activate_calls == [False]
    assert camera.extra_state_attributes["video_owner"] == "agent"


def test_doorbell_camera_on_demand_clears_finished_home_call_without_local_session() -> None:
    class _IdleAfterHomeCallApi(_FakeApi):
        async def async_doorbell_video_status(self) -> dict[str, Any]:
            status = await super().async_doorbell_video_status()
            active = bool(self.activate_calls)
            status["media_owner"] = "agent" if active else "idle"
            status["window_available"] = active
            status["bridge"] = {
                **status["bridge"],
                "media_owner": "agent" if active else "idle",
                "home_call_running": False,
                "home_call_active": False,
                "home_call_answered": False,
                "clients": 0,
            }
            return status

        async def async_home_call_status(self) -> dict[str, Any]:
            self.home_call_status_calls += 1
            return {
                "available": True,
                "running": False,
                "active": False,
                "answered": False,
                "rtp_proxy": False,
                "target_audio_port": 0,
                "rtp_packets": 9,
                "rtcp_packets": 2,
            }

    api = _IdleAfterHomeCallApi()
    entry = _FakeEntry(
        data={"agent_host": "127.0.0.1", "video_port": 6554},
        runtime_data=_FakeRuntimeData(api=api),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera._video_owner = "home_call"
    camera._bridge_status = {
        "media_owner": "home_call",
        "home_call_running": True,
        "home_call_active": True,
        "home_call_answered": True,
    }
    _stub_rtsp_ready(camera)

    stream_url = asyncio.run(camera._async_prepare_rtsp_stream(audio=False))

    assert stream_url == "rtsp://127.0.0.1:6554/doorbell-video"
    assert api.home_call_status_calls == 1
    assert api.activate_calls == [False]
    assert camera.extra_state_attributes["video_owner"] == "agent"
    assert camera._bridge_status["home_call_active"] is False


def test_doorbell_camera_on_demand_blocks_active_home_call_without_local_session() -> None:
    class _ActiveHomeCallApi(_FakeApi):
        async def async_doorbell_video_status(self) -> dict[str, Any]:
            status = await super().async_doorbell_video_status()
            status["media_owner"] = "home_call"
            status["bridge"] = {
                **status["bridge"],
                "media_owner": "home_call",
                "home_call_running": True,
                "home_call_active": True,
                "home_call_answered": True,
                "clients": 0,
            }
            return status

    api = _ActiveHomeCallApi()
    entry = _FakeEntry(
        data={"agent_host": "127.0.0.1", "video_port": 6554},
        runtime_data=_FakeRuntimeData(api=api),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera._video_owner = "home_call"
    camera._bridge_status = {
        "media_owner": "home_call",
        "home_call_running": True,
        "home_call_active": True,
        "home_call_answered": True,
    }
    _stub_rtsp_ready(camera)

    with pytest.raises(HomeAssistantError, match="home_call_active"):
        asyncio.run(camera._async_prepare_rtsp_stream(audio=False))

    assert api.home_call_status_calls == 1
    assert api.activate_calls == []
    assert camera.extra_state_attributes["last_video_block_reason"] == "home_call_active"


def test_doorbell_camera_keeps_active_home_call_session_during_preflight() -> None:
    class _Peer:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    peer = _Peer()
    camera._webrtc_sessions["home-call"] = _NativeWebRTCSession(
        peer,
        owner="home_call",
    )

    asyncio.run(camera._async_close_finished_home_call_sessions())

    assert "home-call" in camera._webrtc_sessions
    assert peer.closed is False
    assert entry.runtime_data.api.home_call_status_calls == 1
    assert camera._bridge_status["home_call_active"] is True
    assert camera.extra_state_attributes["video_owner"] == "home_call"


def test_doorbell_camera_keeps_home_call_session_when_status_refresh_fails() -> None:
    class _FailingHomeCallApi(_FakeApi):
        async def async_home_call_status(self) -> dict[str, Any]:
            self.home_call_status_calls += 1
            raise RuntimeError("status failed")

    class _Peer:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    api = _FailingHomeCallApi()
    entry = _FakeEntry(runtime_data=_FakeRuntimeData(api=api))
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    peer = _Peer()
    camera._webrtc_sessions["home-call"] = _NativeWebRTCSession(
        peer,
        owner="home_call",
    )

    asyncio.run(camera._async_close_finished_home_call_sessions())

    assert "home-call" in camera._webrtc_sessions
    assert peer.closed is False
    assert api.home_call_status_calls == 1


def test_doorbell_camera_refresh_video_status_or_none_suppresses_errors() -> None:
    class _FailingApi(_FakeApi):
        async def async_doorbell_video_status(self) -> dict[str, Any]:
            raise RuntimeError("offline")

    entry = _FakeEntry(runtime_data=_FakeRuntimeData(api=_FailingApi()))
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    status = asyncio.run(camera._async_refresh_video_status_or_none())

    assert status is None


def test_doorbell_camera_audio_gain_is_clamped_and_uses_default_on_invalid() -> None:
    low_entry = _FakeEntry(data={"doorstation_audio_gain_db": -99})
    high_entry = _FakeEntry(data={"doorstation_audio_gain_db": 99})
    invalid_entry = _FakeEntry(data={"doorstation_audio_gain_db": "bad"})

    assert C300XDoorbellCamera(low_entry)._doorstation_audio_gain_db() == -12.0  # type: ignore[arg-type]
    assert C300XDoorbellCamera(high_entry)._doorstation_audio_gain_db() == 12.0  # type: ignore[arg-type]
    assert C300XDoorbellCamera(invalid_entry)._doorstation_audio_gain_db() == 9.5  # type: ignore[arg-type]


def test_doorbell_camera_rtsp_policy_allows_second_ring_preview_when_agent_shares() -> None:
    class _SharedRingPreviewApi(_FakeApi):
        async def async_doorbell_video_status(self) -> dict[str, Any]:
            status = await super().async_doorbell_video_status()
            status["media_owner"] = "ring"
            status["window_available"] = True
            status["bridge"] = {
                **status["bridge"],
                "media_owner": "ring",
                "ring_call_active": True,
                "ring_media_active": True,
                "unanswered_ring_call": True,
                "clients": 1,
                "max_clients": 2,
                "ring_preview_sharing": True,
            }
            return status

    api = _SharedRingPreviewApi()
    entry = _FakeEntry(
        data={"agent_host": "127.0.0.1", "video_port": 6554},
        runtime_data=_FakeRuntimeData(api=api),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera._webrtc_sessions["first"] = SimpleNamespace(player=object())  # type: ignore[assignment]
    _stub_rtsp_ready(camera)

    async def _run() -> str:
        return await camera._async_prepare_rtsp_stream(audio=True)

    source = asyncio.run(_run())

    assert source == "rtsp://127.0.0.1:6554/doorbell"
    assert api.activate_calls == []


def test_doorbell_camera_ring_webrtc_offers_share_one_rtsp_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_messages: list[Any] = []
    ready_urls: list[str] = []
    peers: list[Any] = []

    class _SharedRingApi(_FakeApi):
        def __init__(self) -> None:
            super().__init__()
            self.answered = False

        async def async_doorbell_video_status(self) -> dict[str, Any]:
            status = await super().async_doorbell_video_status()
            status["media_owner"] = "ring"
            status["window_available"] = True
            status["bridge"] = {
                **status["bridge"],
                "media_owner": "ring",
                "ring_call_active": True,
                "ring_media_active": True,
                "ring_audio_active": self.answered,
                "ring_answer_requested": self.answered,
                "ring_answered": self.answered,
                "unanswered_ring_call": not self.answered,
                "clients": 1 if self.answered else 0,
                "max_clients": 4,
                "ring_preview_sharing": True,
            }
            return status

    class _FakeHass:
        def async_create_task(self, coro: Any) -> asyncio.Task:
            return asyncio.create_task(coro)

    class _RelayTrack:
        def __init__(self, track: Any) -> None:
            self.kind = track.kind
            self._track = track
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    class _MediaRelay:
        def subscribe(self, track: Any) -> _RelayTrack:
            return _RelayTrack(track)

    class _VideoTrack:
        kind = "video"

        async def next_timestamp(self) -> tuple[int, str]:
            return 1, "1/90000"

        def stop(self) -> None:
            return None

    class _AudioTrack:
        kind = "audio"

        def stop(self) -> None:
            return None

    class _Peer:
        connectionState = "new"
        iceGatheringState = "complete"

        def __init__(self, configuration: Any) -> None:
            self.configuration = configuration
            self.remoteDescription = None
            self.localDescription = SimpleNamespace(sdp="v=0\r\n", type="answer")
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

    async def _load_aiortc_modules() -> SimpleNamespace:
        return SimpleNamespace(
            av=SimpleNamespace(),
            AudioStreamTrack=_AudioTrack,
            MediaPlayer=object,
            MediaRelay=_MediaRelay,
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
            VideoStreamTrack=_VideoTrack,
        )

    api = _SharedRingApi()
    entry = _FakeEntry(
        data={"agent_host": "127.0.0.1", "video_port": 6554},
        runtime_data=_FakeRuntimeData(api=api),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera.hass = _FakeHass()
    provider = _FakeWebRTCProvider()
    _install_fake_webrtc_provider(monkeypatch, provider)
    _stub_rtsp_ready(camera, ready_urls)

    preview_offer = "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\na=recvonly\r\n"
    answered_offer = (
        "v=0\r\n"
        "m=video 9 UDP/TLS/RTP/SAVPF 96\r\n"
        "a=recvonly\r\n"
        "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
        "a=sendrecv\r\n"
    )

    async def _run() -> None:
        for browser_index in range(4):
            await camera.async_handle_async_webrtc_offer(
                preview_offer,
                f"ring-preview-browser-{browser_index}",
                sent_messages.append,
            )
        api.answered = True
        await camera.async_handle_async_webrtc_offer(
            answered_offer,
            "ring-answer-browser",
            sent_messages.append,
        )

    asyncio.run(_run())

    preview_sessions = [
        camera._provider_webrtc_sessions[f"ring-preview-browser-{browser_index}"]
        for browser_index in range(4)
    ]
    answer_session = camera._provider_webrtc_sessions["ring-answer-browser"]
    assert all(session.resource_id == "ring:entry-1" for session in preview_sessions)
    assert answer_session.resource_id == "ring:entry-1"
    assert answer_session.wants_audio is True
    assert all(session.ready for session in preview_sessions)
    assert answer_session.ready is True
    assert camera._active_local_media_sessions() == 1
    assert provider.offer_sources[-1] == "rtsp://127.0.0.1:6554/doorbell#backchannel=1"
    assert provider.support_sources[-1] == "rtsp://127.0.0.1:6554/doorbell#backchannel=1"
    assert len(provider.offers) == 5
    assert api.activate_calls == []
    assert ready_urls == [
        *(["rtsp://127.0.0.1:6554/doorbell-video"] * 8),
        "rtsp://127.0.0.1:6554/doorbell",
        "rtsp://127.0.0.1:6554/doorbell",
    ]
    assert not any(
        _webrtc_message_value(message, "type") == "error"
        for message in sent_messages
    )


def test_doorbell_camera_blocks_doorbell_rtsp_while_home_call_is_active() -> None:
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
    _stub_rtsp_ready(camera)

    async def _run() -> str:
        return await camera._async_prepare_rtsp_stream(audio=True)

    with pytest.raises(HomeAssistantError, match="home_call_active"):
        asyncio.run(_run())

    assert api.activate_calls == []
    assert camera.extra_state_attributes["last_video_block_reason"] == "home_call_active"


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
    _stub_rtsp_ready(camera)

    async def _run() -> None:
        await camera._async_restart_video_reader(audio=True)

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
    _stub_rtsp_ready(camera)

    async def _run() -> None:
        await asyncio.gather(
            camera._async_prepare_rtsp_stream(audio=True),
            camera._async_prepare_rtsp_stream(audio=True),
        )

    asyncio.run(_run())

    assert api.activate_calls == [True, True]
    assert api.max_active_activate_calls == 1


def test_doorbell_camera_home_call_webrtc_offer_starts_audio_only_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    provider = _FakeWebRTCProvider()
    _install_fake_webrtc_provider(monkeypatch, provider)
    _stub_rtsp_ready(camera, ready_urls)

    offer = "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=sendrecv\r\n"

    async def _run() -> None:
        await camera.async_handle_home_call_webrtc_offer(
            offer,
            "session-home",
            sent_messages.append,
            duration_seconds=30,
        )

        session = camera._provider_webrtc_sessions["session-home"]
        assert session.owner == "home_call"
        assert session.wants_audio is True
        assert session.ready is True
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

        listen_session = camera._provider_webrtc_sessions["session-home-listen"]
        assert listen_session.owner == "home_call"
        assert listen_session.wants_audio is True
        assert listen_session.ready is True

        await camera._async_close_webrtc_session("session-home-listen")

    asyncio.run(_run())

    assert api.home_call_start_calls == [30, 30]
    assert api.home_call_status_calls == 4
    assert api.home_call_stop_calls == 2
    assert api.activate_calls == []
    assert api.stop_calls == 0
    assert ready_urls == [
        "rtsp://127.0.0.1:6554/doorbell",
        "rtsp://127.0.0.1:6554/doorbell",
        "rtsp://127.0.0.1:6554/doorbell",
        "rtsp://127.0.0.1:6554/doorbell",
    ]
    assert provider.offer_sources == [
        "rtsp://127.0.0.1:6554/doorbell#backchannel=1",
        "rtsp://127.0.0.1:6554/doorbell#backchannel=1",
    ]
    assert provider.closed == ["session-home", "session-home-listen"]
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


def test_doorbell_camera_home_call_renew_closes_when_agent_reports_idle(
    monkeypatch,
) -> None:  # noqa: ANN001
    monkeypatch.setattr(camera_module, "WEBRTC_RENEW_SECONDS", 0.01)

    class _EndedHomeCallApi(_FakeApi):
        async def async_home_call_status(self) -> dict[str, Any]:
            self.home_call_status_calls += 1
            return {
                "available": True,
                "running": False,
                "active": False,
                "answered": False,
                "rtp_proxy": False,
                "target_audio_port": 0,
                "rtp_packets": 7,
                "rtcp_packets": 2,
            }

    class _Peer:
        connectionState = "connected"
        iceConnectionState = "completed"
        signalingState = "stable"

        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    api = _EndedHomeCallApi()
    entry = _FakeEntry(runtime_data=_FakeRuntimeData(api=api))
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera._video_owner = "home_call"
    camera._bridge_status = {
        "media_owner": "home_call",
        "home_call_running": True,
        "home_call_active": True,
        "home_call_answered": True,
    }
    sent_messages: list[Any] = []
    peer = _Peer()
    camera._webrtc_sessions["session-home"] = _NativeWebRTCSession(
        peer,
        owner="home_call",
        send_message=sent_messages.append,
    )

    async def _run() -> None:
        await asyncio.wait_for(
            camera._async_renew_webrtc_until_closed("session-home"),
            1,
        )

    asyncio.run(_run())

    assert "session-home" not in camera._webrtc_sessions
    assert peer.closed is True
    assert sent_messages == [{"type": "closed", "reason": "home_call_ended"}]
    assert api.home_call_status_calls == 1
    assert api.home_call_stop_calls == 0
    assert camera._bridge_status["home_call_active"] is False
    assert camera._active_local_media_sessions() == 0


def test_doorbell_camera_renew_closes_terminal_webrtc_peer(
    monkeypatch,
) -> None:  # noqa: ANN001
    monkeypatch.setattr(camera_module, "WEBRTC_RENEW_SECONDS", 0.01)

    class _Peer:
        connectionState = "closed"
        iceConnectionState = "closed"
        signalingState = "closed"

        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    class _Player:
        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    api = _FakeApi()
    entry = _FakeEntry(runtime_data=_FakeRuntimeData(api=api))
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    sent_messages: list[Any] = []
    peer = _Peer()
    player = _Player()
    session = _NativeWebRTCSession(peer, send_message=sent_messages.append)
    session.player = player
    camera._webrtc_sessions["session-doorbell"] = session

    async def _run() -> None:
        await asyncio.wait_for(
            camera._async_renew_webrtc_until_closed("session-doorbell"),
            1,
        )

    asyncio.run(_run())

    assert "session-doorbell" not in camera._webrtc_sessions
    assert peer.closed is True
    assert player.stopped is True
    assert sent_messages == [{"type": "closed", "reason": "webrtc_closed"}]
    assert api.stop_calls == 1


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

    class _FakeSocket:
        def __init__(self, family: int, socktype: int, proto: int) -> None:
            self.family = family
            self.socktype = socktype
            self.proto = proto
            self.blocking: bool | None = None
            self.closed = False

        def setblocking(self, value: bool) -> None:
            self.blocking = value

        def close(self) -> None:
            self.closed = True

    async def _run() -> tuple[bytes, _NativeWebRTCSession, dict[str, Any]]:
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
        sent_packets: list[tuple[bytes, tuple[Any, ...]]] = []
        fake_sockets: list[_FakeSocket] = []
        socket_family = socket.AF_INET
        socket_type = socket.SOCK_DGRAM
        talkback_port = talkback_module.TALKBACK_RTP_PORT

        async def _getaddrinfo(
            host: str,
            port: int,
            *,
            type: int,
        ) -> list[tuple[Any, ...]]:
            assert host == "127.0.0.1"
            assert port == talkback_port
            assert type == socket_type
            return [
                (
                    socket_family,
                    socket_type,
                    0,
                    "",
                    ("192.0.2.60", port),
                )
            ]

        def _socket(family: int, socktype: int, proto: int) -> _FakeSocket:
            sock = _FakeSocket(family, socktype, proto)
            fake_sockets.append(sock)
            return sock

        async def _sock_sendto(
            sock: _FakeSocket,
            data: bytes,
            target: tuple[Any, ...],
        ) -> None:
            assert sock is fake_sockets[0]
            sent_packets.append((data, target))

        monkeypatch.setattr(loop, "getaddrinfo", _getaddrinfo)
        monkeypatch.setattr(loop, "sock_sendto", _sock_sendto)
        monkeypatch.setattr(talkback_module.socket, "socket", _socket)

        task = asyncio.create_task(
            camera._async_forward_talkback_audio(
                _FakeTrack(),
                aiortc_modules,
                "session-1",
            )
        )
        await asyncio.wait_for(task, 1)
        assert camera._talkback_last_error is None
        assert len(fake_sockets) == 1
        assert fake_sockets[0].blocking is False
        assert fake_sockets[0].closed is True
        assert len(sent_packets) == 1
        packet, target = sent_packets[0]
        assert target == ("192.0.2.60", talkback_port)
        return packet, session, camera.extra_state_attributes

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


def test_doorbell_camera_detects_home_call_media_for_audio_only() -> None:
    camera = C300XDoorbellCamera(_FakeEntry())  # type: ignore[arg-type]

    assert camera._derive_media_decision(
        {"media_owner": "home_call", "bridge": {}}
    ).state is MediaState.HOME_CALL_STARTING
    assert camera._derive_media_decision(
        {"bridge": {"media_owner": "home_call"}}
    ).state is MediaState.HOME_CALL_STARTING
    assert camera._derive_media_decision(
        {"bridge": {"home_call_active": True}}
    ).state is MediaState.HOME_CALL_RINGING
    assert camera._derive_media_decision(
        {"bridge": {"home_call_answered": True}}
    ).state is MediaState.HOME_CALL_ACTIVE
    assert camera._derive_media_decision(
        {"media_owner": "ring", "bridge": {"ring_call_active": True}}
    ).state is MediaState.RING_PENDING
    assert camera._derive_media_decision(
        {
            "media_owner": "ring",
            "bridge": {
                "ring_call_active": True,
                "ring_media_active": True,
                "ring_audio_active": True,
            },
        }
    ).state is MediaState.RING_ACTIVE


def test_doorbell_camera_ignores_home_call_rtsp_cooldown_for_doorbell_state() -> None:
    camera = C300XDoorbellCamera(_FakeEntry())  # type: ignore[arg-type]
    camera._last_rtsp_error = "ConnectionRefusedError"
    camera._rtsp_unavailable_until = 999999999.0
    camera._rtsp_cooldown_scope = "home_call"

    decision = camera._derive_media_decision({"media_owner": "idle", "bridge": {}})

    assert decision.state is MediaState.IDLE
    assert decision.primary_action.value == "start_stream"


def test_doorbell_camera_stream_url_brackets_ipv6_host() -> None:
    entry = _FakeEntry(data={"agent_host": "fe80::1%wlan0", "video_port": 6554})
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    assert camera._build_stream_url(audio=False) == (
        "rtsp://[fe80::1%25wlan0]:6554/doorbell-video"
    )
    assert camera._agent_host_for_socket() == "fe80::1%wlan0"


def test_doorbell_camera_rtsp_cooldown_marker_does_not_block_retry() -> None:
    entry = _FakeEntry(data={"agent_host": "127.0.0.1", "video_port": 9})
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera._rtsp_unavailable_until = 999999999.0
    camera._last_rtsp_error = "ConnectionRefusedError"
    _stub_rtsp_ready(camera)

    async def _run() -> str:
        return await camera.stream_source()

    source = asyncio.run(_run())

    assert source == "rtsp://127.0.0.1:9/doorbell-video"
    assert entry.runtime_data.api.activate_calls == [False]
    assert camera._rtsp_unavailable_until == 0.0
    assert camera._rtsp_cooldown_scope is None


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


def test_doorbell_camera_updates_derived_media_state_from_video_status() -> None:
    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    camera._apply_status(
        {
            "available": True,
            "window_available": True,
            "media_owner": "agent",
            "bridge": {"media_owner": "agent"},
        }
    )
    assert camera._last_media_state is MediaState.ON_DEMAND_ACTIVE

    camera._apply_status(
        {
            "available": True,
            "window_available": False,
            "media_owner": "external_media",
            "external_media_active": True,
            "external_owner": "smartphone",
            "bridge": {
                "media_owner": "external_media",
                "external_media_active": True,
            },
        }
    )
    assert camera._last_media_state is MediaState.EXTERNAL_MEDIA_ACTIVE


def test_doorbell_camera_updates_derived_media_state_from_agent_clients() -> None:
    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    camera._apply_status(
        {
            "available": True,
            "window_available": False,
            "media_owner": "idle",
            "bridge": {"media_owner": "idle", "clients": 1},
        }
    )

    assert camera._last_media_state is MediaState.RTSP_BUSY
    assert camera._last_media_decision.capture_blocked is True


def test_doorbell_camera_keeps_capabilities_permissive_until_agent_reports_them() -> None:
    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    camera._apply_status(
        {
            "available": True,
            "window_available": True,
            "media_owner": "agent",
            "bridge": {"media_owner": "agent"},
        }
    )

    assert camera._last_media_state is MediaState.ON_DEMAND_ACTIVE


def test_doorbell_camera_uses_known_capability_facts_in_state_machine() -> None:
    entry = _FakeEntry()
    entry.runtime_data.capabilities = {"doorbell_video": {"supported": False}}
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    camera._apply_status(
        {
            "available": True,
            "window_available": True,
            "media_owner": "agent",
            "bridge": {"media_owner": "agent"},
        }
    )

    assert camera._last_media_state is MediaState.UNKNOWN
    assert camera._last_media_decision.webrtc_keepalive_allowed is False


def test_doorbell_camera_updates_derived_media_state_from_home_call_status() -> None:
    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    camera._apply_home_call_status(
        {
            "available": True,
            "running": True,
            "active": True,
            "answered": True,
            "rtp_proxy": True,
        }
    )

    assert camera._last_media_state is MediaState.HOME_CALL_ACTIVE


def test_doorbell_camera_updates_derived_media_state_from_ring_event() -> None:
    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    event = SimpleNamespace(
        data={
            "entry_id": entry.entry_id,
            "event_key": "doorbell_view_requested",
            "video_window_available": True,
            "video_available": True,
            "stream_path": "/doorbell-video",
            "media_owner": "ring",
            "bridge": {
                "media_owner": "ring",
                "ring_call_active": True,
                "ring_media_active": True,
            },
        }
    )

    camera._handle_agent_event(event)

    assert camera._last_media_state is MediaState.RING_PREVIEW_ACTIVE
    assert camera._last_media_decision.primary_action == "answer_ring"


def test_doorbell_camera_ring_event_sequence_reaches_preview_then_idle() -> None:
    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    camera._handle_agent_event(
        SimpleNamespace(
            data={
                "entry_id": entry.entry_id,
                "event_key": "doorbell_pressed",
                "media_owner": "ring",
                "bridge": {
                    "media_owner": "ring",
                    "ring_call_active": True,
                    "ring_media_active": False,
                    "unanswered_ring_call": True,
                },
            }
        )
    )

    assert camera._last_media_state is MediaState.RING_PENDING
    assert camera._last_media_decision.rtsp_start_allowed is False

    camera._handle_agent_event(
        SimpleNamespace(
            data={
                "entry_id": entry.entry_id,
                "event_key": "doorbell_view_requested",
                "media_owner": "ring",
                "video_window_available": True,
                "video_available": True,
                "stream_path": "/doorbell-video",
                "bridge": {
                    "media_owner": "ring",
                    "ring_call_active": True,
                    "ring_media_active": True,
                    "unanswered_ring_call": True,
                },
            }
        )
    )

    assert camera._last_media_state is MediaState.RING_PREVIEW_ACTIVE
    assert camera._last_media_decision.primary_action == "answer_ring"
    assert camera.extra_state_attributes["video_window_available"] is True

    camera._handle_agent_event(
        SimpleNamespace(
            data={
                "entry_id": entry.entry_id,
                "event_key": "doorbell_media_closed",
            }
        )
    )

    assert camera._last_media_state is MediaState.IDLE
    assert camera.extra_state_attributes["video_window_available"] is False


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
    assert camera._last_media_state is MediaState.IDLE


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


def test_doorbell_camera_home_call_answered_then_ended_event_sequence() -> None:
    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    camera._handle_agent_event(
        SimpleNamespace(
            data={
                "entry_id": entry.entry_id,
                "event_key": "home_call_answered",
                "home_call": {
                    "running": True,
                    "active": True,
                    "answered": True,
                    "rtp_proxy": True,
                    "target_audio_port": 62012,
                },
            }
        )
    )

    assert camera._last_media_state is MediaState.HOME_CALL_ACTIVE
    assert camera.extra_state_attributes["video_owner"] == "home_call"

    camera._handle_agent_event(
        SimpleNamespace(
            data={
                "entry_id": entry.entry_id,
                "event_key": "home_call_ended",
                "home_call": {"rtp_packets": 12, "rtcp_packets": 3},
            }
        )
    )

    assert camera._last_media_state is MediaState.IDLE
    assert camera.extra_state_attributes["video_owner"] == "idle"
    assert camera._bridge_status["home_call_running"] is False
    assert camera._bridge_status["home_call_active"] is False
    assert camera._bridge_status["home_call_answered"] is False
    assert camera._bridge_status["home_call_rtp_packets"] == 12
    assert camera._bridge_status["home_call_rtcp_packets"] == 3
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
