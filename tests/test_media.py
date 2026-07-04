from __future__ import annotations

import asyncio
import builtins
import sys
import types
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp import web

if "homeassistant.components.http" not in sys.modules:
    homeassistant = sys.modules.setdefault(
        "homeassistant",
        types.ModuleType("homeassistant"),
    )
    components = sys.modules.setdefault(
        "homeassistant.components",
        types.ModuleType("homeassistant.components"),
    )
    http = types.ModuleType("homeassistant.components.http")
    config_entries = sys.modules.setdefault(
        "homeassistant.config_entries",
        types.ModuleType("homeassistant.config_entries"),
    )
    core = sys.modules.setdefault(
        "homeassistant.core",
        types.ModuleType("homeassistant.core"),
    )
    helpers = sys.modules.setdefault(
        "homeassistant.helpers",
        types.ModuleType("homeassistant.helpers"),
    )
    helpers.__path__ = []
    config_validation = sys.modules.setdefault(
        "homeassistant.helpers.config_validation",
        types.ModuleType("homeassistant.helpers.config_validation"),
    )

    class ConfigEntry:  # pragma: no cover - import-time stub only
        pass

    class HomeAssistant:  # pragma: no cover - import-time stub only
        pass

    class HomeAssistantView:  # pragma: no cover - import-time stub only
        extra_urls: list[str] = []

    config_entries.ConfigEntry = ConfigEntry
    core.HomeAssistant = HomeAssistant
    http.HomeAssistantView = HomeAssistantView
    config_validation.config_entry_only_config_schema = lambda _domain: dict
    components.http = http
    helpers.config_validation = config_validation
    homeassistant.components = components
    homeassistant.helpers = helpers
    sys.modules["homeassistant.components.http"] = http

from custom_components.bticino_c300x import media as media_module
from custom_components.bticino_c300x.api import (
    C300XAgentApiError,
    C300XAgentApiUnsupportedError,
)
from custom_components.bticino_c300x.const import DOMAIN
from custom_components.bticino_c300x.media import (
    C300XVideoMessageMediaView,
    C300XVoiceMemoMediaView,
    _should_transcode_video_message,
    _validated_message_id,
    _validated_voice_memo_id,
    async_setup_media_view,
    runtime_entry,
)


def test_video_message_view_exposes_playable_mp4_route() -> None:
    assert C300XVideoMessageMediaView.url == (
        f"/api/{DOMAIN}/video-messages/{{entry_id}}/{{message_id}}/video"
    )
    assert C300XVideoMessageMediaView.extra_urls == [
        f"/api/{DOMAIN}/video-messages/{{entry_id}}/{{message_id}}/video.mp4"
    ]


def test_video_message_transcode_decision_targets_non_browser_containers() -> None:
    assert _should_transcode_video_message("video/x-msvideo")
    assert _should_transcode_video_message("video/x-matroska; charset=binary")
    assert not _should_transcode_video_message("video/mp4")


def test_media_view_registration_is_idempotent() -> None:
    registered: list[object] = []
    hass = SimpleNamespace(
        data={},
        http=SimpleNamespace(register_view=lambda view: registered.append(view)),
    )

    async_setup_media_view(hass)  # type: ignore[arg-type]
    async_setup_media_view(hass)  # type: ignore[arg-type]

    assert [type(view) for view in registered] == [
        C300XVideoMessageMediaView,
        C300XVoiceMemoMediaView,
    ]
    assert hass.data[DOMAIN]["video_message_view_registered"] is True


def test_media_proxy_id_validation_rejects_path_traversal() -> None:
    assert _validated_message_id("message_1") == "message_1"
    assert _validated_voice_memo_id("memo_1") == "voice/memo_1"
    assert _validated_message_id("../message_1") is None
    assert _validated_voice_memo_id("../memo_1") is None


def test_runtime_entry_requires_loaded_c300x_entry() -> None:
    loaded = SimpleNamespace(domain=DOMAIN, runtime_data=object())
    no_runtime = SimpleNamespace(domain=DOMAIN)
    other_domain = SimpleNamespace(domain="other", runtime_data=object())
    entries = {
        "loaded": loaded,
        "no-runtime": no_runtime,
        "other": other_domain,
    }
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_get_entry=lambda entry_id: entries.get(entry_id)
        )
    )

    assert runtime_entry(hass, "loaded") is loaded  # type: ignore[arg-type]
    assert runtime_entry(hass, "no-runtime") is None  # type: ignore[arg-type]
    assert runtime_entry(hass, "other") is None  # type: ignore[arg-type]
    assert runtime_entry(hass, "missing") is None  # type: ignore[arg-type]


def test_video_message_view_serves_agent_video_bytes() -> None:
    api = _FakeMediaApi(video=(b"video-bytes", "video/mp4"))
    hass = _fake_hass({"entry1": _fake_entry(api)})
    request = SimpleNamespace(
        app={"hass": hass},
        path=f"/api/{DOMAIN}/video-messages/entry1/message_1/video",
    )

    response = asyncio.run(
        C300XVideoMessageMediaView().get(  # type: ignore[arg-type]
            request,
            "entry1",
            "message_1",
        )
    )

    assert response.body == b"video-bytes"
    assert response.content_type == "video/mp4"
    assert response.headers["Cache-Control"] == "no-store"
    assert api.video_message_ids == ["message_1"]


def test_video_message_view_transcodes_original_container() -> None:
    api = _FakeMediaApi(video=(b"avi-bytes", "video/x-msvideo"))

    async def async_add_executor_job(func, content):  # noqa: ANN001
        assert content == b"avi-bytes"
        assert func.__name__ == "_convert_video_message_to_mp4"
        return b"mp4-bytes"

    hass = _fake_hass({"entry1": _fake_entry(api)})
    hass.async_add_executor_job = async_add_executor_job
    request = SimpleNamespace(
        app={"hass": hass},
        path=f"/api/{DOMAIN}/video-messages/entry1/message_1/video.mp4",
    )

    response = asyncio.run(
        C300XVideoMessageMediaView().get(  # type: ignore[arg-type]
            request,
            "entry1",
            "message_1",
        )
    )

    assert response.body == b"mp4-bytes"
    assert response.content_type == "video/mp4"


@pytest.mark.parametrize(
    ("entry_id", "message_id", "error"),
    [
        ("missing", "message_1", web.HTTPNotFound),
        ("entry1", "../bad", web.HTTPNotFound),
    ],
)
def test_video_message_view_rejects_unknown_or_invalid_request(
    entry_id: str,
    message_id: str,
    error: type[Exception],
) -> None:
    hass = _fake_hass({"entry1": _fake_entry(_FakeMediaApi())})
    request = SimpleNamespace(
        app={"hass": hass},
        path=f"/api/{DOMAIN}/video-messages/{entry_id}/{message_id}/video",
    )

    with pytest.raises(error):
        asyncio.run(
            C300XVideoMessageMediaView().get(  # type: ignore[arg-type]
                request,
                entry_id,
                message_id,
            )
        )


def test_video_message_view_maps_agent_errors_to_http_responses() -> None:
    request = SimpleNamespace(
        app={"hass": _fake_hass({"entry1": _fake_entry(_FakeMediaApi(error="unsupported"))})},
        path=f"/api/{DOMAIN}/video-messages/entry1/message_1/video",
    )

    with pytest.raises(web.HTTPNotFound):
        asyncio.run(
            C300XVideoMessageMediaView().get(  # type: ignore[arg-type]
                request,
                "entry1",
                "message_1",
            )
        )

    request.app["hass"] = _fake_hass({"entry1": _fake_entry(_FakeMediaApi(error="api"))})
    with pytest.raises(web.HTTPBadGateway):
        asyncio.run(
            C300XVideoMessageMediaView().get(  # type: ignore[arg-type]
                request,
                "entry1",
                "message_1",
            )
        )


def test_voice_memo_view_serves_agent_audio_bytes() -> None:
    api = _FakeMediaApi(audio=(b"audio-bytes", "audio/wav"))
    hass = _fake_hass({"entry1": _fake_entry(api)})
    request = SimpleNamespace(
        app={"hass": hass},
        path=f"/api/{DOMAIN}/voice-memos/entry1/memo_1/audio",
    )

    response = asyncio.run(
        C300XVoiceMemoMediaView().get(  # type: ignore[arg-type]
            request,
            "entry1",
            "memo_1",
        )
    )

    assert response.body == b"audio-bytes"
    assert response.content_type == "audio/wav"
    assert response.headers["Cache-Control"] == "no-store"
    assert api.memo_ids == ["voice/memo_1"]


def test_voice_memo_view_maps_invalid_and_agent_errors() -> None:
    request = SimpleNamespace(
        app={"hass": _fake_hass({"entry1": _fake_entry(_FakeMediaApi())})},
        path=f"/api/{DOMAIN}/voice-memos/entry1/memo_1/audio",
    )

    with pytest.raises(web.HTTPNotFound):
        asyncio.run(
            C300XVoiceMemoMediaView().get(  # type: ignore[arg-type]
                request,
                "entry1",
                "../memo_1",
            )
        )

    request.app["hass"] = _fake_hass({"entry1": _fake_entry(_FakeMediaApi(error="api"))})
    with pytest.raises(web.HTTPBadGateway):
        asyncio.run(
            C300XVoiceMemoMediaView().get(  # type: ignore[arg-type]
                request,
                "entry1",
                "memo_1",
            )
        )

    request.app["hass"] = _fake_hass(
        {"entry1": _fake_entry(_FakeMediaApi(error="unsupported"))}
    )
    with pytest.raises(web.HTTPNotFound):
        asyncio.run(
            C300XVoiceMemoMediaView().get(  # type: ignore[arg-type]
                request,
                "entry1",
                "memo_1",
            )
        )


def test_convert_video_message_to_mp4_muxes_video_and_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    av_module, resampler_module, output = _install_fake_av(monkeypatch)
    av_module.open = lambda target, **kwargs: (
        _FakeInputContainer()
        if kwargs["mode"] == "r"
        else _FakeOutputContainer(target, output)
    )

    converted = media_module._convert_video_message_to_mp4(b"avi")

    assert converted == b"mp4" * 5
    assert output.added == [("h264", 2), ("aac", 44100)]
    assert output.video.width == 640
    assert output.video.height == 480
    assert output.video.pix_fmt == "yuv420p"
    assert output.audio.layout == "mono"
    assert resampler_module.created == [("fltp", "mono", 44100)]
    assert output.muxed == [b"video", b"audio", b"video-flush", b"audio", b"audio-flush"]


def test_convert_video_message_to_mp4_rejects_missing_video_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    av_module, _resampler_module, _output = _install_fake_av(monkeypatch)
    av_module.open = lambda target, **kwargs: (
        _FakeInputContainer(video=False)
        if kwargs["mode"] == "r"
        else _FakeOutputContainer(target, _FakeOutputState())
    )

    with pytest.raises(ValueError, match="does not contain a video stream"):
        media_module._convert_video_message_to_mp4(b"audio-only")


def test_convert_video_message_to_mp4_maps_missing_pyav(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for module_name in ("av", "av.audio", "av.audio.resampler"):
        monkeypatch.delitem(sys.modules, module_name, raising=False)

    original_import = builtins.__import__

    def fake_import(
        name: str,
        globals_: dict[str, object] | None = None,
        locals_: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == "av" or name.startswith("av."):
            raise ImportError("missing PyAV")
        return original_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(
        media_module.C300XMediaDependencyError,
        match="PyAV is not installed",
    ):
        media_module._convert_video_message_to_mp4(b"avi")


class _FakeMediaApi:
    def __init__(
        self,
        *,
        video: tuple[bytes, str] = (b"", "video/mp4"),
        audio: tuple[bytes, str] = (b"", "audio/wav"),
        error: str | None = None,
    ) -> None:
        self._video = video
        self._audio = audio
        self._error = error
        self.video_message_ids: list[str] = []
        self.memo_ids: list[str] = []

    async def async_answering_machine_message_video(
        self,
        message_id: str,
    ) -> tuple[bytes, str]:
        self.video_message_ids.append(message_id)
        self._raise_if_needed()
        return self._video

    async def async_memo_audio(self, memo_id: str) -> tuple[bytes, str]:
        self.memo_ids.append(memo_id)
        self._raise_if_needed()
        return self._audio

    def _raise_if_needed(self) -> None:
        if self._error == "unsupported":
            raise C300XAgentApiUnsupportedError("unsupported")
        if self._error == "api":
            raise C300XAgentApiError("offline")


def _fake_entry(api: _FakeMediaApi) -> SimpleNamespace:
    return SimpleNamespace(domain=DOMAIN, runtime_data=SimpleNamespace(api=api))


def _fake_hass(entries: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        data={},
        config_entries=SimpleNamespace(
            async_get_entry=lambda entry_id: entries.get(entry_id)
        ),
    )


def _install_fake_av(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any, Any]:
    av_module = types.ModuleType("av")
    audio_module = types.ModuleType("av.audio")
    resampler_module = types.ModuleType("av.audio.resampler")
    output = _FakeOutputState()

    class AudioResampler:
        def __init__(self, *, format: str, layout: str, rate: int) -> None:
            resampler_module.created.append((format, layout, rate))

        def resample(self, frame: object | None) -> list[_FakeFrame]:
            return [_FakeFrame("audio-flush" if frame is None else "audio")]

    resampler_module.AudioResampler = AudioResampler
    resampler_module.created = []
    audio_module.resampler = resampler_module
    av_module.audio = audio_module
    monkeypatch.setitem(sys.modules, "av", av_module)
    monkeypatch.setitem(sys.modules, "av.audio", audio_module)
    monkeypatch.setitem(sys.modules, "av.audio.resampler", resampler_module)
    return av_module, resampler_module, output


class _FakeCodecContext:
    width = 640
    height = 480


class _FakeStream:
    def __init__(self, stream_type: str) -> None:
        self.type = stream_type
        self.average_rate = 2
        self.codec_context = _FakeCodecContext()


class _FakeFrame:
    def __init__(self, payload: str) -> None:
        self.payload = payload


class _FakePacket:
    def __init__(self, stream: _FakeStream, payload: str) -> None:
        self.stream = stream
        self._payload = payload

    def decode(self) -> list[_FakeFrame]:
        return [_FakeFrame(self._payload)]


class _FakeInputContainer:
    def __init__(self, *, video: bool = True, audio: bool = True) -> None:
        self.video = _FakeStream("video") if video else None
        self.audio = _FakeStream("audio") if audio else None
        self.streams = [
            stream for stream in (self.video, self.audio) if stream is not None
        ]

    def __enter__(self) -> _FakeInputContainer:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def demux(self, streams: list[_FakeStream]) -> list[_FakePacket]:
        return [_FakePacket(stream, stream.type) for stream in streams]


class _FakeOutputState:
    def __init__(self) -> None:
        self.added: list[tuple[str, int]] = []
        self.muxed: list[bytes] = []
        self.video: _FakeOutputStream | None = None
        self.audio: _FakeOutputStream | None = None


class _FakeOutputStream:
    def __init__(self, codec: str, rate: int) -> None:
        self.codec = codec
        self.rate = rate
        self.width: int | None = None
        self.height: int | None = None
        self.pix_fmt: str | None = None
        self.layout: str | None = None

    def encode(self, frame: _FakeFrame | None = None) -> list[bytes]:
        if self.codec == "h264":
            return [b"video-flush" if frame is None else b"video"]
        return [b"audio-flush" if frame is None else b"audio"]


class _FakeOutputContainer:
    def __init__(self, target: object, output: _FakeOutputState) -> None:
        self._target = target
        self._output = output

    def __enter__(self) -> _FakeOutputContainer:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def add_stream(self, codec: str, *, rate: int) -> _FakeOutputStream:
        self._output.added.append((codec, rate))
        stream = _FakeOutputStream(codec, rate)
        if codec == "h264":
            self._output.video = stream
        else:
            self._output.audio = stream
        return stream

    def mux(self, packet: bytes) -> None:
        self._output.muxed.append(packet)
        self._target.write(b"mp4")
