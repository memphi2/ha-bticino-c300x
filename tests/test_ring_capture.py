from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.bticino_c300x.const import (
    CONF_AGENT_HOST,
    CONF_VIDEO_PORT,
    CONF_VIDEO_STREAM_PATH,
)
from custom_components.bticino_c300x.ring_capture import (
    _announcement_input_path,
    _async_run_ffmpeg,
    _capture_output_path,
    _capture_stream_path,
    _create_speex_encoder,
    _rtsp_url_from_status,
    async_capture_doorbell_ring_call,
)


@dataclass
class _FakeConfig:
    root: Path

    def path(self, *parts: str) -> str:
        return str(self.root.joinpath(*parts))


@dataclass
class _FakeHass:
    root: Path
    config: _FakeConfig = field(init=False)

    def __post_init__(self) -> None:
        self.config = _FakeConfig(self.root)

    async def async_add_executor_job(self, func: Any, *args: Any) -> Any:
        return func(*args)


@dataclass
class _FakeApi:
    status: dict[str, Any]

    async def async_doorbell_video_status(self) -> dict[str, Any]:
        return self.status


@dataclass
class _FakeRuntimeData:
    api: _FakeApi


@dataclass
class _FakeEntry:
    runtime_data: _FakeRuntimeData
    data: dict[str, Any]
    options: dict[str, Any] = field(default_factory=dict)


def test_capture_stream_path_prefers_audio_path_when_audio_is_requested() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(_FakeApi({})),
        data={CONF_VIDEO_STREAM_PATH: "/configured"},
    )

    assert _capture_stream_path(
        entry,
        {
            "stream_path": "/video",
            "audio_stream_path": "/audio",
            "recorder_stream_path": "/recorder",
        },
        include_audio=True,
    ) == "/audio"
    assert _capture_stream_path(
        entry,
        {
            "stream_path": "/video",
            "audio_stream_path": "/audio",
            "recorder_stream_path": "/recorder",
        },
        include_audio=False,
    ) == "/recorder"
    assert _capture_stream_path(
        entry,
        {"stream_path": "/video", "audio_stream_path": "/audio"},
        include_audio=True,
    ) == "/audio"
    assert _capture_stream_path(entry, {"stream_path": "/video"}) == "/video"
    assert _capture_stream_path(entry, {}) == "/configured"


def test_rtsp_url_uses_entry_host_port_and_status_path() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(_FakeApi({})),
        data={
            CONF_AGENT_HOST: "192.0.2.10",
            CONF_VIDEO_PORT: 6554,
            CONF_VIDEO_STREAM_PATH: "/configured",
        },
    )

    assert (
        _rtsp_url_from_status(
            entry,
            {"recorder_stream_path": "doorbell-recorder"},
            include_audio=False,
        )
        == "rtsp://192.0.2.10:6554/doorbell-recorder"
    )


def test_capture_output_path_rejects_paths_outside_allowed_roots(tmp_path: Path) -> None:
    hass = _FakeHass(tmp_path / "config")

    assert _capture_output_path(
        hass,
        str(tmp_path / "config" / "www" / "c300x" / "clip.mp4"),
    ).name == "clip.mp4"
    with pytest.raises(HomeAssistantError):
        _capture_output_path(hass, str(tmp_path / "config" / "www" / "bad.mp4"))
    with pytest.raises(HomeAssistantError):
        _capture_output_path(hass, "/media/c300x/clip.mkv")


def test_announcement_path_allows_only_c300x_media_roots(tmp_path: Path) -> None:
    hass = _FakeHass(tmp_path / "config")
    announcement = tmp_path / "config" / "www" / "c300x" / "announce.wav"
    announcement.parent.mkdir(parents=True)
    announcement.write_bytes(b"fake")

    assert _announcement_input_path(hass, str(announcement)) == announcement
    with pytest.raises(HomeAssistantError):
        _announcement_input_path(hass, str(tmp_path / "announce.wav"))
    with pytest.raises(HomeAssistantError):
        _announcement_input_path(
            hass,
            str(tmp_path / "config" / "www" / "c300x" / "missing.wav"),
        )


def test_announcement_path_accepts_ha_www_alias(tmp_path: Path) -> None:
    hass = _FakeHass(tmp_path / "config")
    announcement = tmp_path / "config" / "www" / "c300x" / "announce.wav"
    announcement.parent.mkdir(parents=True)
    announcement.write_bytes(b"fake")

    assert _announcement_input_path(hass, "/www/c300x/announce.wav") == announcement


def test_capture_runs_ffmpeg_after_rtsp_ready(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, Any]] = []
    target = tmp_path / "config" / "www" / "c300x" / "clip.mp4"
    hass = _FakeHass(tmp_path / "config")
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            _FakeApi({"recorder_stream_path": "/doorbell-recorder"})
        ),
        data={CONF_AGENT_HOST: "192.0.2.10", CONF_VIDEO_PORT: 6554},
    )

    async def _ready(rtsp_url: str) -> None:
        calls.append(("ready", rtsp_url))

    async def _ffmpeg(
        rtsp_url: str,
        output: Path,
        *,
        duration_seconds: int,
        include_audio: bool,
    ) -> None:
        calls.append(("ffmpeg", (rtsp_url, output, duration_seconds, include_audio)))

    async def _unexpected_announcement(_host: str, _source: Path) -> None:
        calls.append(("unexpected_announcement", None))

    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_wait_rtsp_ready",
        _ready,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_run_ffmpeg",
        _ffmpeg,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_play_announcement_when_ready",
        _unexpected_announcement,
    )

    result = asyncio.run(
        async_capture_doorbell_ring_call(
            hass,
            entry,
            output_path=str(target),
            duration_seconds=4,
            include_audio=True,
        )
    )

    assert result == target
    assert calls == [
        ("ready", "rtsp://192.0.2.10:6554/doorbell-recorder"),
        ("ffmpeg", ("rtsp://192.0.2.10:6554/doorbell-recorder", target, 4, True)),
    ]


def test_capture_ffmpeg_audio_uses_mp4_safe_normalized_aac(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    commands: list[list[str]] = []

    class _Process:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b""

    async def _create_subprocess_exec(*command: str, **_kwargs: Any) -> _Process:
        commands.append(list(command))
        return _Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _create_subprocess_exec)

    asyncio.run(
        _async_run_ffmpeg(
            "rtsp://192.0.2.10:6554/doorbell",
            tmp_path / "clip.mp4",
            duration_seconds=4,
            include_audio=True,
        )
    )

    command = commands[0]
    audio_filter = command[command.index("-af") + 1]
    assert "aresample=48000" in audio_filter
    assert "pan=stereo" in audio_filter
    assert "dynaudnorm=" not in audio_filter
    assert "alimiter=" in audio_filter
    assert "volume=6dB" in audio_filter
    assert "volume=30dB" not in audio_filter
    assert command[command.index("-ac") + 1] == "2"
    assert command[command.index("-ar") + 1] == "48000"
    assert command[command.index("-b:a") + 1] == "128k"
    assert str(tmp_path / "clip.raw.wav") in command
    assert commands[1][-1] == str(tmp_path / "clip.processed.wav")


def test_announcement_speex_encoder_accepts_runtime_codec_alias() -> None:
    calls: list[str] = []

    class _CodecContext:
        @staticmethod
        def create(codec_name: str, _mode: str) -> object:
            calls.append(codec_name)
            if codec_name == "speex":
                return object()
            raise RuntimeError("missing")

    class _AvModule:
        CodecContext = _CodecContext

    assert _create_speex_encoder(_AvModule()) is not None
    assert calls == ["speex"]


def test_capture_plays_announcement_in_parallel(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, Any]] = []
    target = tmp_path / "config" / "www" / "c300x" / "clip.mp4"
    announcement = tmp_path / "config" / "www" / "c300x" / "announce.wav"
    announcement.parent.mkdir(parents=True)
    announcement.write_bytes(b"fake")
    hass = _FakeHass(tmp_path / "config")
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(_FakeApi({"audio_stream_path": "/doorbell"})),
        data={CONF_AGENT_HOST: "192.0.2.10", CONF_VIDEO_PORT: 6554},
    )

    async def _ready(rtsp_url: str) -> None:
        calls.append(("ready", rtsp_url))

    async def _ffmpeg(
        rtsp_url: str,
        output: Path,
        *,
        duration_seconds: int,
        include_audio: bool,
    ) -> None:
        calls.append(("ffmpeg", (rtsp_url, output, duration_seconds, include_audio)))

    async def _announcement(_entry: Any, host: str, source: Path) -> None:
        calls.append(("announcement", (host, source)))

    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_wait_rtsp_ready",
        _ready,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_run_ffmpeg",
        _ffmpeg,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_play_announcement_when_ready",
        _announcement,
    )

    asyncio.run(
        async_capture_doorbell_ring_call(
            hass,
            entry,
            output_path=str(target),
            duration_seconds=4,
            include_audio=True,
            announcement_path=str(announcement),
        )
    )

    assert ("announcement", ("192.0.2.10", announcement)) in calls
