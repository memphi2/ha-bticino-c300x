from __future__ import annotations

import asyncio
import sys
import types
from contextlib import suppress
from dataclasses import dataclass, field
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
    core.CALLBACK_TYPE = object
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
    _ProviderWebRTCSession,
    async_setup_entry,
)
from custom_components.bticino_c300x.camera_media.state_machine import MediaState
from custom_components.bticino_c300x.media_timeline import C300XMediaTimeline
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
        self.doorstation_audio_gain_calls: list[float] = []
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

    async def async_set_doorstation_audio_gain_db(
        self,
        gain_db: float,
    ) -> dict[str, Any]:
        self.doorstation_audio_gain_calls.append(gain_db)
        return {"ok": True, "doorstation_audio_gain_db": gain_db}

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
    media_timeline: Any = field(default_factory=C300XMediaTimeline)


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


def test_doorbell_camera_provider_offer_error_closes_local_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ErrorWebRTCProvider(_FakeWebRTCProvider):
        async def async_handle_async_webrtc_offer(
            self,
            camera: C300XDoorbellCamera,
            offer_sdp: str,
            session_id: str,
            send_message: Any,
        ) -> None:
            self.offer_sources.append(await camera.stream_source())
            self.offers.append((session_id, offer_sdp))
            send_message(camera_module.WebRTCError("go2rtc_offer_failed", "boom"))

    api = _FakeApi()
    entry = _FakeEntry(
        data={"agent_host": "127.0.0.1", "video_port": 6554},
        runtime_data=_FakeRuntimeData(api=api),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera.hass = SimpleNamespace()
    provider = _ErrorWebRTCProvider()
    sent_messages: list[Any] = []
    _install_fake_webrtc_provider(monkeypatch, provider)
    _stub_rtsp_ready(camera)

    asyncio.run(
        camera.async_handle_async_webrtc_offer(
            "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n",
            "session-error",
            sent_messages.append,
        )
    )

    assert camera._webrtc_session_ids() == []
    assert camera._presession_webrtc_candidates == {}
    assert provider.closed == ["session-error"]
    assert api.stop_calls == 1
    assert [_webrtc_message_value(message, "code") for message in sent_messages] == [
        "go2rtc_offer_failed"
    ]


def test_doorbell_camera_provider_exception_before_stream_source_keeps_media(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _EarlyErrorWebRTCProvider(_FakeWebRTCProvider):
        async def async_handle_async_webrtc_offer(
            self,
            camera: C300XDoorbellCamera,
            offer_sdp: str,
            session_id: str,
            send_message: Any,
        ) -> None:
            self.offers.append((session_id, offer_sdp))
            raise HomeAssistantError("provider failed before source setup")

    api = _FakeApi()
    entry = _FakeEntry(
        data={"agent_host": "127.0.0.1", "video_port": 6554},
        runtime_data=_FakeRuntimeData(api=api),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera.hass = SimpleNamespace()
    provider = _EarlyErrorWebRTCProvider()
    sent_messages: list[Any] = []

    async def _provider_without_source(
        _hass: Any,
        _camera: C300XDoorbellCamera,
    ) -> Any:
        return provider

    monkeypatch.setattr(
        camera_module,
        "_async_get_supported_webrtc_provider",
        _provider_without_source,
    )
    _stub_rtsp_ready(camera)

    asyncio.run(
        camera.async_handle_async_webrtc_offer(
            "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n",
            "session-early-error",
            sent_messages.append,
        )
    )

    assert camera._webrtc_session_ids() == []
    assert provider.closed == ["session-early-error"]
    assert provider.offer_sources == []
    assert api.stop_calls == 0
    assert [_webrtc_message_value(message, "code") for message in sent_messages] == [
        "bticino_webrtc_unavailable"
    ]


def test_doorbell_camera_provider_exception_after_stream_source_stops_on_demand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _LateErrorWebRTCProvider(_FakeWebRTCProvider):
        async def async_handle_async_webrtc_offer(
            self,
            camera: C300XDoorbellCamera,
            offer_sdp: str,
            session_id: str,
            send_message: Any,
        ) -> None:
            self.offer_sources.append(await camera.stream_source())
            self.offers.append((session_id, offer_sdp))
            raise HomeAssistantError("provider failed after source setup")

    api = _FakeApi()
    entry = _FakeEntry(
        data={"agent_host": "127.0.0.1", "video_port": 6554},
        runtime_data=_FakeRuntimeData(api=api),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera.hass = SimpleNamespace()
    provider = _LateErrorWebRTCProvider()
    sent_messages: list[Any] = []
    _install_fake_webrtc_provider(monkeypatch, provider)
    _stub_rtsp_ready(camera)

    asyncio.run(
        camera.async_handle_async_webrtc_offer(
            "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n",
            "session-late-error",
            sent_messages.append,
        )
    )

    assert camera._webrtc_session_ids() == []
    assert provider.closed == ["session-late-error"]
    assert provider.offer_sources == ["rtsp://127.0.0.1:6554/doorbell"]
    assert api.stop_calls == 1
    assert [_webrtc_message_value(message, "code") for message in sent_messages] == [
        "bticino_webrtc_unavailable"
    ]


def test_doorbell_camera_home_call_provider_offer_error_stops_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ErrorWebRTCProvider(_FakeWebRTCProvider):
        async def async_handle_async_webrtc_offer(
            self,
            camera: C300XDoorbellCamera,
            offer_sdp: str,
            session_id: str,
            send_message: Any,
        ) -> None:
            self.offer_sources.append(await camera.stream_source())
            self.offers.append((session_id, offer_sdp))
            send_message(camera_module.WebRTCError("go2rtc_offer_failed", "boom"))

    api = _FakeApi()
    entry = _FakeEntry(
        data={"agent_host": "127.0.0.1", "video_port": 6554},
        runtime_data=_FakeRuntimeData(api=api),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera.hass = SimpleNamespace()
    provider = _ErrorWebRTCProvider()
    sent_messages: list[Any] = []
    _install_fake_webrtc_provider(monkeypatch, provider)
    _stub_rtsp_ready(camera)

    asyncio.run(
        camera.async_handle_home_call_webrtc_offer(
            "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=sendrecv\r\n",
            "session-home-error",
            sent_messages.append,
            duration_seconds=30,
        )
    )

    assert camera._webrtc_session_ids() == []
    assert provider.closed == ["session-home-error"]
    assert api.home_call_start_calls == [30]
    assert api.home_call_stop_calls == 1
    assert [_webrtc_message_value(message, "code") for message in sent_messages] == [
        "go2rtc_offer_failed"
    ]


def test_doorbell_camera_buffers_provider_ice_candidate_before_offer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _FakeEntry(data={"agent_host": "127.0.0.1", "video_port": 6554})
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera.hass = SimpleNamespace()
    provider = _FakeWebRTCProvider()
    _install_fake_webrtc_provider(monkeypatch, provider)
    _stub_rtsp_ready(camera)

    candidate = SimpleNamespace(candidate="candidate:1 1 udp 1 192.0.2.10 9 typ host")

    async def _run() -> None:
        await camera.async_on_webrtc_candidate("session-1", candidate)
        assert provider.candidates == []
        await camera.async_handle_async_webrtc_offer(
            "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n",
            "session-1",
            lambda _message: None,
        )

    asyncio.run(_run())

    assert provider.candidates == [("session-1", candidate)]
    assert camera._presession_webrtc_candidates == {}


def test_doorbell_camera_closing_provider_sessions_controls_media_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _FakeApi()
    entry = _FakeEntry(
        data={"agent_host": "127.0.0.1", "video_port": 6554},
        runtime_data=_FakeRuntimeData(api=api),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera.hass = SimpleNamespace()
    provider = _FakeWebRTCProvider()
    _install_fake_webrtc_provider(monkeypatch, provider)
    _stub_rtsp_ready(camera)

    async def _run() -> None:
        offer = "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n"
        await camera.async_handle_async_webrtc_offer(offer, "session-1", lambda _: None)
        await camera.async_handle_async_webrtc_offer(offer, "session-2", lambda _: None)
        assert camera._webrtc_session_ids() == ["session-1", "session-2"]
        await camera._async_close_webrtc_session("session-1")
        assert api.stop_calls == 0
        await camera._async_close_webrtc_session("session-2")

    asyncio.run(_run())

    assert provider.closed == ["session-1", "session-2"]
    assert api.stop_calls == 1


def test_doorbell_camera_prepare_stop_waits_for_provider_rtsp_clients_to_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class _DrainingApi(_FakeApi):
        def __init__(self) -> None:
            super().__init__()
            self.clients = [2, 1, 0]

        async def async_doorbell_video_status(self) -> dict[str, Any]:
            status = await super().async_doorbell_video_status()
            clients = self.clients.pop(0)
            events.append(f"status:{clients}")
            status["bridge"] = {**status["bridge"], "clients": clients}
            return status

    class _RecordingProvider(_FakeWebRTCProvider):
        def async_close_session(self, session_id: str) -> None:
            events.append(f"close:{session_id}")
            super().async_close_session(session_id)

    monkeypatch.setattr(
        camera_module,
        "WEBRTC_PROVIDER_CLOSE_DRAIN_INTERVAL_SECONDS",
        0,
    )

    api = _DrainingApi()
    entry = _FakeEntry(runtime_data=_FakeRuntimeData(api=api))
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    provider = _RecordingProvider()
    camera._provider_webrtc_sessions["doorbell-session"] = _ProviderWebRTCSession(
        provider=provider,
        owner="doorbell",
        send_message=lambda _message: None,
        wants_audio=True,
        wants_backchannel=False,
        resource_id="doorbell:entry-1:audio",
        ready=True,
    )

    asyncio.run(camera.async_prepare_doorbell_video_stop())

    assert events == [
        "close:doorbell-session",
        "status:2",
        "status:1",
        "status:0",
    ]
    assert provider.closed == ["doorbell-session"]
    assert api.stop_calls == 0


def test_doorbell_camera_closing_last_webrtc_session_drains_provider_before_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class _DrainingApi(_FakeApi):
        def __init__(self) -> None:
            super().__init__()
            self.clients = [2, 1, 0]

        async def async_doorbell_video_status(self) -> dict[str, Any]:
            status = await super().async_doorbell_video_status()
            clients = self.clients.pop(0)
            events.append(f"status:{clients}")
            status["bridge"] = {**status["bridge"], "clients": clients}
            return status

        async def async_stop_doorbell_video(self) -> dict[str, Any]:
            events.append("stop")
            return await super().async_stop_doorbell_video()

    class _RecordingProvider(_FakeWebRTCProvider):
        def async_close_session(self, session_id: str) -> None:
            events.append(f"close:{session_id}")
            super().async_close_session(session_id)

    monkeypatch.setattr(
        camera_module,
        "WEBRTC_PROVIDER_CLOSE_DRAIN_INTERVAL_SECONDS",
        0,
    )

    api = _DrainingApi()
    entry = _FakeEntry(runtime_data=_FakeRuntimeData(api=api))
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    provider = _RecordingProvider()
    camera._provider_webrtc_sessions["doorbell-session"] = _ProviderWebRTCSession(
        provider=provider,
        owner="doorbell",
        send_message=lambda _message: None,
        wants_audio=True,
        wants_backchannel=False,
        resource_id="doorbell:entry-1:audio",
        ready=True,
    )

    asyncio.run(camera._async_close_webrtc_session("doorbell-session"))

    assert events == [
        "close:doorbell-session",
        "status:2",
        "status:1",
        "status:0",
        "stop",
    ]
    assert provider.closed == ["doorbell-session"]
    assert api.stop_calls == 1


def test_doorbell_camera_closing_last_resource_session_ignores_unrelated_stale_session() -> None:
    api = _FakeApi()
    entry = _FakeEntry(runtime_data=_FakeRuntimeData(api=api))
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    provider = _FakeWebRTCProvider()
    camera._provider_webrtc_sessions["doorbell-session"] = _ProviderWebRTCSession(
        provider=provider,
        owner="doorbell",
        send_message=lambda _message: None,
        wants_audio=True,
        wants_backchannel=False,
        resource_id="doorbell:entry-1:audio",
        ready=True,
    )
    camera._provider_webrtc_sessions["stale-home-call-session"] = _ProviderWebRTCSession(
        provider=provider,
        owner="home_call",
        send_message=lambda _message: None,
        wants_audio=True,
        wants_backchannel=False,
        resource_id="home_call:entry-1",
        ready=False,
    )

    asyncio.run(camera._async_close_webrtc_session("doorbell-session"))

    assert provider.closed == ["doorbell-session"]
    assert api.stop_calls == 1
    assert api.home_call_stop_calls == 0
    assert camera._webrtc_session_ids() == ["stale-home-call-session"]


def test_doorbell_camera_provider_offer_uses_backchannel_for_talkback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _FakeEntry(data={"agent_host": "127.0.0.1", "video_port": 6554})
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera.hass = SimpleNamespace()
    provider = _FakeWebRTCProvider()
    _install_fake_webrtc_provider(monkeypatch, provider)
    _stub_rtsp_ready(camera)

    offer = (
        "v=0\r\n"
        "m=video 9 UDP/TLS/RTP/SAVPF 96\r\n"
        "a=recvonly\r\n"
        "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
        "a=sendrecv\r\n"
    )

    asyncio.run(
        camera.async_handle_async_webrtc_offer(
            offer,
            "session-talkback",
            lambda _message: None,
        )
    )

    assert camera._provider_webrtc_sessions["session-talkback"].wants_audio is True
    assert camera._provider_webrtc_sessions["session-talkback"].wants_backchannel is True
    assert provider.offer_sources == [
        "rtsp://127.0.0.1:6554/doorbell#backchannel=1"
    ]
    assert provider.support_sources == [
        "rtsp://127.0.0.1:6554/doorbell#backchannel=1"
    ]


def test_doorbell_camera_provider_offer_omits_backchannel_without_microphone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _FakeEntry(data={"agent_host": "127.0.0.1", "video_port": 6554})
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera.hass = SimpleNamespace()
    provider = _FakeWebRTCProvider()
    _install_fake_webrtc_provider(monkeypatch, provider)
    _stub_rtsp_ready(camera)

    offer = (
        "v=0\r\n"
        "m=video 9 UDP/TLS/RTP/SAVPF 96\r\n"
        "a=recvonly\r\n"
        "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
        "a=recvonly\r\n"
    )

    asyncio.run(
        camera.async_handle_async_webrtc_offer(
            offer,
            "session-listen",
            lambda _message: None,
        )
    )

    session = camera._provider_webrtc_sessions["session-listen"]
    assert session.wants_audio is True
    assert session.wants_backchannel is False
    assert provider.offer_sources == ["rtsp://127.0.0.1:6554/doorbell"]
    assert provider.support_sources == ["rtsp://127.0.0.1:6554/doorbell"]


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

    assert source == "rtsp://127.0.0.1:6554/doorbell"
    assert entry.runtime_data.api.activate_calls == [True]


def test_doorbell_camera_audio_stream_source_uses_audio_video_path() -> None:
    entry = _FakeEntry(data={"agent_host": "127.0.0.1", "video_port": 6554})
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    _stub_rtsp_ready(camera)

    async def _run() -> str:
        return await camera._async_prepare_rtsp_stream(audio=True)

    source = asyncio.run(_run())

    assert source == "rtsp://127.0.0.1:6554/doorbell"
    assert entry.runtime_data.api.activate_calls == [True]


def test_doorbell_camera_provider_video_only_offer_uses_on_demand_audio_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _IdleApi(_FakeApi):
        async def async_doorbell_video_status(self) -> dict[str, Any]:
            status = await super().async_doorbell_video_status()
            status["media_owner"] = "idle"
            status["window_available"] = False
            status["bridge"] = {
                **status["bridge"],
                "media_owner": "idle",
                "clients": 0,
                "max_clients": 1,
            }
            return status

    entry = _FakeEntry(
        data={"agent_host": "127.0.0.1", "video_port": 6554},
        runtime_data=_FakeRuntimeData(api=_IdleApi()),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera.hass = SimpleNamespace()
    provider = _FakeWebRTCProvider()
    _install_fake_webrtc_provider(monkeypatch, provider)
    _stub_rtsp_ready(camera)

    offer = "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\na=recvonly\r\n"

    asyncio.run(
        camera.async_handle_async_webrtc_offer(
            offer,
            "entity-video-only",
            lambda _message: None,
        )
    )

    session = camera._provider_webrtc_sessions["entity-video-only"]
    assert session.wants_audio is False
    assert session.wants_backchannel is False
    assert provider.offer_sources == ["rtsp://127.0.0.1:6554/doorbell"]
    assert provider.support_sources == ["rtsp://127.0.0.1:6554/doorbell"]
    assert entry.runtime_data.api.activate_calls == [True, True]


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


def test_doorbell_camera_refresh_video_status_or_none_suppresses_errors() -> None:
    class _FailingApi(_FakeApi):
        async def async_doorbell_video_status(self) -> dict[str, Any]:
            raise RuntimeError("offline")

    entry = _FakeEntry(runtime_data=_FakeRuntimeData(api=_FailingApi()))
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    status = asyncio.run(camera._async_refresh_video_status_or_none())

    assert status is None


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

    preview_session_ids = [
        f"ring-preview-browser-{browser_index}" for browser_index in range(4)
    ]
    answer_session = camera._provider_webrtc_sessions["ring-answer-browser"]
    assert list(camera._provider_webrtc_sessions) == [
        *preview_session_ids,
        "ring-answer-browser",
    ]
    assert answer_session.resource_id == "ring:entry-1"
    assert answer_session.wants_audio is True
    assert answer_session.ready is True
    assert camera._active_local_media_sessions() == 1
    assert provider.closed == []
    assert provider.offer_sources[-1] == "rtsp://127.0.0.1:6554/doorbell#backchannel=1"
    assert provider.support_sources[-1] == "rtsp://127.0.0.1:6554/doorbell#backchannel=1"
    assert len(provider.offers) == 5
    assert [session_id for session_id, _offer in provider.offers[:4]] == preview_session_ids
    closed_messages = [
        message
        for message in sent_messages
        if _webrtc_message_value(message, "type") == "closed"
    ]
    assert closed_messages == []
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


def test_ring_answer_audio_keeps_passive_preview_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class _RingApi(_FakeApi):
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
                "clients": 0,
                "max_clients": 2,
                "ring_preview_sharing": True,
            }
            return status

    class _RecordingProvider(_FakeWebRTCProvider):
        async def async_handle_async_webrtc_offer(
            self,
            camera: C300XDoorbellCamera,
            offer_sdp: str,
            session_id: str,
            send_message: Any,
        ) -> None:
            events.append(f"offer-start:{session_id}")
            await super().async_handle_async_webrtc_offer(
                camera,
                offer_sdp,
                session_id,
                send_message,
            )

        def async_close_session(self, session_id: str) -> None:
            events.append(f"close:{session_id}")
            super().async_close_session(session_id)

    api = _RingApi()
    entry = _FakeEntry(
        data={"agent_host": "127.0.0.1", "video_port": 6554},
        runtime_data=_FakeRuntimeData(api=api),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera.hass = SimpleNamespace()
    provider = _RecordingProvider()
    messages: list[Any] = []
    _install_fake_webrtc_provider(monkeypatch, provider)
    _stub_rtsp_ready(camera)

    preview_offer = "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\na=recvonly\r\n"
    answered_offer = (
        "v=0\r\n"
        "m=video 9 UDP/TLS/RTP/SAVPF 96\r\n"
        "a=recvonly\r\n"
        "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
        "a=sendrecv\r\n"
    )

    async def _run() -> None:
        await camera.async_handle_async_webrtc_offer(
            preview_offer,
            "ring-preview-browser",
            messages.append,
        )
        api.answered = True
        await camera.async_handle_async_webrtc_offer(
            answered_offer,
            "ring-answer-browser",
            messages.append,
        )

    asyncio.run(_run())

    assert events == [
        "offer-start:ring-preview-browser",
        "offer-start:ring-answer-browser",
    ]
    assert list(camera._provider_webrtc_sessions) == [
        "ring-preview-browser",
        "ring-answer-browser",
    ]
    assert provider.closed == []
    assert provider.offer_sources[-1] == "rtsp://127.0.0.1:6554/doorbell#backchannel=1"
    assert api.hangup_calls == 0
    assert api.stop_calls == 0
    closed_messages = [
        message
        for message in messages
        if _webrtc_message_value(message, "type") == "closed"
    ]
    assert closed_messages == []


def test_ring_preview_provider_exception_after_stream_source_keeps_ring_media(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RingApi(_FakeApi):
        async def async_doorbell_video_status(self) -> dict[str, Any]:
            status = await super().async_doorbell_video_status()
            status["media_owner"] = "ring"
            status["window_available"] = True
            status["bridge"] = {
                **status["bridge"],
                "media_owner": "ring",
                "ring_call_active": True,
                "ring_media_active": True,
                "ring_audio_active": False,
                "ring_answer_requested": False,
                "ring_answered": False,
                "unanswered_ring_call": True,
                "clients": 0,
                "max_clients": 4,
                "ring_preview_sharing": True,
            }
            return status

    class _LateErrorWebRTCProvider(_FakeWebRTCProvider):
        async def async_handle_async_webrtc_offer(
            self,
            camera: C300XDoorbellCamera,
            offer_sdp: str,
            session_id: str,
            send_message: Any,
        ) -> None:
            self.offer_sources.append(await camera.stream_source())
            self.offers.append((session_id, offer_sdp))
            raise HomeAssistantError("provider failed after source setup")

    api = _RingApi()
    entry = _FakeEntry(
        data={"agent_host": "127.0.0.1", "video_port": 6554},
        runtime_data=_FakeRuntimeData(api=api),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera.hass = SimpleNamespace()
    provider = _LateErrorWebRTCProvider()
    sent_messages: list[Any] = []
    _install_fake_webrtc_provider(monkeypatch, provider)
    _stub_rtsp_ready(camera)

    asyncio.run(
        camera.async_handle_async_webrtc_offer(
            "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\na=recvonly\r\n",
            "ring-preview-error",
            sent_messages.append,
        )
    )

    assert camera._webrtc_session_ids() == []
    assert provider.closed == ["ring-preview-error"]
    assert provider.offer_sources == ["rtsp://127.0.0.1:6554/doorbell-video"]
    assert api.stop_calls == 0
    assert api.hangup_calls == 0
    assert [_webrtc_message_value(message, "code") for message in sent_messages] == [
        "bticino_webrtc_unavailable"
    ]


def test_ring_call_answer_without_microphone_omits_rtsp_backchannel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _AnsweredRingApi(_FakeApi):
        async def async_doorbell_video_status(self) -> dict[str, Any]:
            status = await super().async_doorbell_video_status()
            status["media_owner"] = "ring"
            status["window_available"] = True
            status["bridge"] = {
                **status["bridge"],
                "media_owner": "ring",
                "ring_call_active": True,
                "ring_media_active": True,
                "ring_audio_active": True,
                "ring_answered": True,
                "clients": 0,
                "max_clients": 4,
            }
            return status

    entry = _FakeEntry(
        data={"agent_host": "127.0.0.1", "video_port": 6554},
        runtime_data=_FakeRuntimeData(api=_AnsweredRingApi()),
    )
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera.hass = SimpleNamespace()
    provider = _FakeWebRTCProvider()
    _install_fake_webrtc_provider(monkeypatch, provider)
    _stub_rtsp_ready(camera)

    offer = (
        "v=0\r\n"
        "m=video 9 UDP/TLS/RTP/SAVPF 96\r\n"
        "a=recvonly\r\n"
        "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
        "a=recvonly\r\n"
    )

    asyncio.run(
        camera.async_handle_async_webrtc_offer(
            offer,
            "ring-listen-browser",
            lambda _message: None,
        )
    )

    session = camera._provider_webrtc_sessions["ring-listen-browser"]
    assert session.resource_id == "ring:entry-1"
    assert session.ring_call is True
    assert session.wants_audio is True
    assert session.wants_backchannel is False
    assert provider.offer_sources == ["rtsp://127.0.0.1:6554/doorbell"]
    assert provider.support_sources == ["rtsp://127.0.0.1:6554/doorbell"]


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
        assert session.wants_backchannel is True
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
        assert listen_session.wants_backchannel is False
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
        "rtsp://127.0.0.1:6554/doorbell",
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

    assert source == "rtsp://127.0.0.1:9/doorbell"
    assert entry.runtime_data.api.activate_calls == [True]
    assert camera._rtsp_unavailable_until == 0.0
    assert camera._rtsp_cooldown_scope is None


def test_doorbell_camera_wakes_rtsp_waiters_on_media_event() -> None:
    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]

    async def _run() -> int:
        revision = camera._rtsp_event_revision()
        wait_task = asyncio.create_task(
            camera._async_wait_for_rtsp_event(revision=revision, wait_seconds=1.0)
        )
        await asyncio.sleep(0)
        camera._handle_agent_event(
            SimpleNamespace(
                data={
                    "entry_id": entry.entry_id,
                    "event_key": "doorbell_view_requested",
                    "video_window_available": True,
                    "video_available": True,
                    "stream_path": "/doorbell-video",
                    "audio_stream_path": "/doorbell",
                    "bridge": {"media_owner": "agent", "media_active": True},
                }
            )
        )
        await asyncio.wait_for(wait_task, timeout=0.1)
        return revision

    initial_revision = asyncio.run(_run())

    assert camera._rtsp_event_revision() == initial_revision + 1


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


def test_doorbell_media_closed_closes_local_doorbell_webrtc_without_agent_stop() -> None:
    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    provider = _FakeWebRTCProvider()
    messages: list[Any] = []
    tasks: list[asyncio.Task[Any]] = []

    class _FakeHass:
        def async_create_task(self, coro: Any) -> asyncio.Task[Any]:
            task = asyncio.create_task(coro)
            tasks.append(task)
            return task

    camera.hass = _FakeHass()  # type: ignore[assignment]
    camera._provider_webrtc_sessions["ring-preview-browser"] = _ProviderWebRTCSession(
        provider=provider,
        owner="doorbell",
        send_message=messages.append,
        wants_audio=False,
        wants_backchannel=False,
        resource_id="ring:entry-1",
        ring_preview=True,
        ready=True,
    )
    camera._provider_webrtc_sessions["ring-answer-browser"] = _ProviderWebRTCSession(
        provider=provider,
        owner="doorbell",
        send_message=messages.append,
        wants_audio=True,
        wants_backchannel=True,
        resource_id="ring:entry-1",
        ring_call=True,
        ready=True,
    )

    async def _run() -> None:
        camera._handle_agent_event(
            SimpleNamespace(
                data={
                    "entry_id": entry.entry_id,
                    "event_key": "doorbell_media_closed",
                }
            )
        )
        if tasks:
            await asyncio.gather(*tasks)

    asyncio.run(_run())

    assert camera._provider_webrtc_sessions == {}
    assert provider.closed == ["ring-preview-browser", "ring-answer-browser"]
    assert messages == [
        {"type": "closed", "reason": "doorbell_media_closed"},
        {"type": "closed", "reason": "doorbell_media_closed"},
    ]
    assert entry.runtime_data.api.stop_calls == 0


def test_ring_answer_event_keeps_passive_preview_webrtc_sessions() -> None:
    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    provider = _FakeWebRTCProvider()
    messages: list[Any] = []
    tasks: list[asyncio.Task[Any]] = []

    class _FakeHass:
        def async_create_task(self, coro: Any) -> asyncio.Task[Any]:
            task = asyncio.create_task(coro)
            tasks.append(task)
            return task

    camera.hass = _FakeHass()  # type: ignore[assignment]
    camera._provider_webrtc_sessions["ring-preview-browser"] = _ProviderWebRTCSession(
        provider=provider,
        owner="doorbell",
        send_message=messages.append,
        wants_audio=False,
        wants_backchannel=False,
        resource_id="ring:entry-1",
        ring_preview=True,
        ready=True,
    )
    camera._provider_webrtc_sessions["ring-answer-browser"] = _ProviderWebRTCSession(
        provider=provider,
        owner="doorbell",
        send_message=messages.append,
        wants_audio=True,
        wants_backchannel=True,
        resource_id="ring:entry-1",
        ring_call=True,
        ready=True,
    )

    async def _run() -> None:
        camera._handle_agent_event(
            SimpleNamespace(
                data={
                    "entry_id": entry.entry_id,
                    "event_key": "doorbell_view_requested",
                    "media_owner": "ring",
                    "video_window_available": True,
                    "video_available": True,
                    "stream_path": "/doorbell-video",
                    "audio_stream_path": "/doorbell",
                    "bridge": {
                        "media_owner": "ring",
                        "ring_call_active": True,
                        "ring_media_active": True,
                        "ring_audio_active": True,
                        "ring_answer_requested": False,
                        "ring_answered": True,
                        "unanswered_ring_call": False,
                    },
                }
            )
        )
        if tasks:
            await asyncio.gather(*tasks)

    asyncio.run(_run())

    assert list(camera._provider_webrtc_sessions) == [
        "ring-preview-browser",
        "ring-answer-browser",
    ]
    assert provider.closed == []
    assert messages == []
    assert entry.runtime_data.api.stop_calls == 0


def test_ring_answer_event_keeps_preview_until_answer_session_exists() -> None:
    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    provider = _FakeWebRTCProvider()
    messages: list[Any] = []
    tasks: list[asyncio.Task[Any]] = []

    class _FakeHass:
        def async_create_task(self, coro: Any) -> asyncio.Task[Any]:
            task = asyncio.create_task(coro)
            tasks.append(task)
            return task

    camera.hass = _FakeHass()  # type: ignore[assignment]
    camera._provider_webrtc_sessions["ring-preview-browser"] = _ProviderWebRTCSession(
        provider=provider,
        owner="doorbell",
        send_message=messages.append,
        wants_audio=False,
        wants_backchannel=False,
        resource_id="ring:entry-1",
        ring_preview=True,
        ready=True,
    )

    async def _run() -> None:
        camera._handle_agent_event(
            SimpleNamespace(
                data={
                    "entry_id": entry.entry_id,
                    "event_key": "doorbell_view_requested",
                    "media_owner": "ring",
                    "video_window_available": True,
                    "video_available": True,
                    "stream_path": "/doorbell-video",
                    "audio_stream_path": "/doorbell",
                    "bridge": {
                        "media_owner": "ring",
                        "ring_call_active": True,
                        "ring_media_active": True,
                        "ring_audio_active": True,
                        "ring_answered": True,
                        "unanswered_ring_call": False,
                    },
                }
            )
        )
        if tasks:
            await asyncio.gather(*tasks)

    asyncio.run(_run())

    assert list(camera._provider_webrtc_sessions) == ["ring-preview-browser"]
    assert provider.closed == []
    assert messages == []


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


def test_doorbell_camera_home_call_ended_clears_stale_busy_state() -> None:
    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    provider = _FakeWebRTCProvider()
    camera._video_owner = "home_call"
    camera._bridge_status = {
        "media_owner": "home_call",
        "media_active": True,
        "media_starting": False,
        "stop_in_progress": False,
        "call_active": True,
        "clients": 1,
        "home_call_running": True,
        "home_call_active": True,
        "home_call_answered": True,
    }
    camera._provider_webrtc_sessions["session-home"] = _ProviderWebRTCSession(
        provider=provider,
        owner="home_call",
        send_message=lambda _message: None,
        wants_audio=True,
        wants_backchannel=True,
        resource_id="home_call:entry-1",
        ready=True,
    )
    camera._refresh_derived_media_state()
    assert camera._last_media_state is MediaState.HOME_CALL_ACTIVE

    camera._handle_agent_event(
        SimpleNamespace(
            data={
                "entry_id": entry.entry_id,
                "event_key": "home_call_ended",
                "home_call": {"rtp_packets": 377, "rtcp_packets": 1},
            }
        )
    )

    assert camera._provider_webrtc_sessions["session-home"].ready is False
    assert camera._bridge_status["media_owner"] == "idle"
    assert camera._bridge_status["media_active"] is False
    assert camera._bridge_status["call_active"] is False
    assert camera._bridge_status["clients"] == 0
    assert camera._last_media_state is MediaState.IDLE
    assert camera.extra_state_attributes["media_state"] == "idle"
    assert camera.extra_state_attributes["media_primary_action"] == "start_stream"


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


def test_doorbell_camera_deduplicates_unchanged_agent_event_state_writes() -> None:
    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    writes: list[str] = []
    camera.async_write_ha_state = lambda: writes.append("write")  # type: ignore[method-assign]
    event_data = {
        "entry_id": entry.entry_id,
        "event_key": "doorbell_view_requested",
        "video_window_available": True,
        "video_available": True,
        "stream_path": "/doorbell-video",
        "audio_stream_path": "/doorbell",
        "recorder_stream_path": "/doorbell-recorder",
        "bridge": {
            "media_owner": "doorbell",
            "media_active": True,
            "clients": 1,
        },
    }

    camera._handle_agent_event(SimpleNamespace(data=event_data))
    camera._handle_agent_event(SimpleNamespace(data=dict(event_data)))

    assert writes == ["write"]

    camera._handle_agent_event(
        SimpleNamespace(data={**event_data, "last_block_reason": "rtsp_busy"})
    )

    assert writes == ["write", "write"]


def test_doorbell_camera_records_safe_media_timeline_from_agent_events() -> None:
    entry = _FakeEntry()
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera.async_write_ha_state = lambda: None  # type: ignore[method-assign]
    event_data = {
        "entry_id": entry.entry_id,
        "event_key": "doorbell_view_requested",
        "video_window_available": True,
        "video_available": True,
        "media_owner": "doorbell",
        "stream_path": "/doorbell-video",
        "bridge": {
            "media_owner": "doorbell",
            "media_active": True,
            "clients": 1,
            "ring_call_active": False,
        },
    }

    camera._handle_agent_event(SimpleNamespace(data=event_data))

    [entry_data] = entry.runtime_data.media_timeline.diagnostics()
    assert entry_data["kind"] == "agent_event"
    assert entry_data["event"] == "doorbell_view_requested"
    assert entry_data["owner"] == "doorbell"
    assert entry_data["session_count"] == 0
    assert entry_data["details"] == {
        "video_available": True,
        "video_window_available": True,
        "bridge_clients": 1,
        "bridge_media_active": True,
        "bridge_ring_call_active": False,
    }
    assert "stream_path" not in entry_data["details"]


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
