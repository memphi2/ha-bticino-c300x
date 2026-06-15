from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.bticino_c300x.camera_media import rtsp_reader
from custom_components.bticino_c300x.camera_media.rtsp_reader import (
    DOORSTATION_AUDIO_GAIN,
    RTSP_MAX_SESSION_RESTARTS,
    _apply_audio_gain,
    _audio_gain_multiplier,
    _new_restarting_rtsp_audio_track,
    _new_restarting_rtsp_tracks,
    _new_restarting_rtsp_video_track,
)


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
            _Hass(),
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
            _Hass(),
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


def test_restarting_rtsp_video_track_stops_unused_audio_reader() -> None:
    stopped: list[str] = []

    class _Frame:
        pts: int | None = None
        time_base: object | None = None

    class _SourceTrack:
        def __init__(self, kind: str) -> None:
            self.kind = kind

        async def recv(self) -> _Frame:
            return _Frame()

        def stop(self) -> None:
            stopped.append(self.kind)

    class _VideoTrack:
        kind = "video"

        async def next_timestamp(self) -> tuple[int, str]:
            return 7, "1/90000"

        def stop(self) -> None:
            stopped.append("wrapper")

    class _MediaPlayer:
        def __init__(self, _url: str, options: dict[str, str]) -> None:
            assert options["rtsp_transport"] == "tcp"
            self.video = _SourceTrack("video")
            self.audio = _SourceTrack("audio")

    class _Hass:
        async def async_add_executor_job(self, func: Any) -> Any:
            return func()

    async def _run() -> _Frame:
        track = _new_restarting_rtsp_video_track(
            _VideoTrack,
            Exception,
            _MediaPlayer,
            _Hass(),
            "rtsp://agent.local:6554/doorbell",
            lambda: None,
        )
        try:
            return await track.recv()
        finally:
            track.stop()

    frame = asyncio.run(_run())

    assert frame.pts == 7
    assert frame.time_base == "1/90000"
    assert stopped == ["video", "audio", "wrapper"]


def test_restarting_rtsp_video_track_restarts_after_reader_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[int] = []
    restarts: list[str] = []

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(rtsp_reader.asyncio, "sleep", no_sleep)

    class _Frame:
        pts: int | None = None
        time_base: object | None = None

    class _SourceTrack:
        def __init__(self, fail: bool) -> None:
            self._fail = fail

        async def recv(self) -> _Frame:
            if self._fail:
                raise RuntimeError("lost")
            return _Frame()

        def stop(self) -> None:
            return None

    class _VideoTrack:
        kind = "video"

        async def next_timestamp(self) -> tuple[int, str]:
            return 3, "1/90000"

        def stop(self) -> None:
            return None

    class _MediaPlayer:
        def __init__(self, _url: str, options: dict[str, str]) -> None:
            assert options["rtsp_transport"] == "tcp"
            opened.append(len(opened))
            self.video = _SourceTrack(fail=len(opened) == 1)
            self.audio = None

    class _Hass:
        async def async_add_executor_job(self, func: Any) -> Any:
            return func()

    async def restart_callback() -> None:
        restarts.append("restart")

    async def _run() -> _Frame:
        track = _new_restarting_rtsp_video_track(
            _VideoTrack,
            Exception,
            _MediaPlayer,
            _Hass(),
            "rtsp://agent.local:6554/doorbell",
            restart_callback,
        )
        try:
            await track._ensure_reader()
            return await track.recv()
        finally:
            track.stop()

    frame = asyncio.run(_run())

    assert frame.pts == 3
    assert opened == [0, 1]
    assert restarts == ["restart"]


def test_restarting_rtsp_tracks_reject_missing_media_and_max_restarts() -> None:
    class _MediaError(Exception):
        pass

    class _SourceTrack:
        def stop(self) -> None:
            return None

    class _VideoTrack:
        kind = "video"

        def stop(self) -> None:
            return None

    class _AudioTrack:
        kind = "audio"

        def stop(self) -> None:
            return None

    class _MediaPlayer:
        def __init__(self, _url: str, options: dict[str, str]) -> None:
            assert options["rtsp_transport"] == "tcp"
            self.video = _SourceTrack()
            self.audio = None

    class _Hass:
        async def async_add_executor_job(self, func: Any) -> Any:
            return func()

    async def _run() -> None:
        media, _video, _audio = _new_restarting_rtsp_tracks(
            SimpleNamespace(),
            _VideoTrack,
            _AudioTrack,
            _MediaError,
            _MediaPlayer,
            _Hass(),
            "rtsp://agent.local:6554/doorbell",
            lambda: None,
        )
        with pytest.raises(_MediaError):
            await media._async_open_reader()
        media._restart_pending = True
        media._restart_attempts = RTSP_MAX_SESSION_RESTARTS
        with pytest.raises(_MediaError):
            await media._async_open_reader()

    asyncio.run(_run())


def test_restarting_shared_rtsp_media_ensure_reader_is_idempotent() -> None:
    opened = 0

    class _SourceTrack:
        def stop(self) -> None:
            return None

    class _VideoTrack:
        kind = "video"

        def stop(self) -> None:
            return None

    class _AudioTrack:
        kind = "audio"

        def stop(self) -> None:
            return None

    class _MediaPlayer:
        def __init__(self, _url: str, options: dict[str, str]) -> None:
            nonlocal opened
            opened += 1
            self.video = _SourceTrack()
            self.audio = _SourceTrack()

    class _MediaStreamError(Exception):
        pass

    class _Hass:
        async def async_add_executor_job(self, func: Any) -> Any:
            return func()

    async def _run() -> None:
        media, _video, _audio = _new_restarting_rtsp_tracks(
            SimpleNamespace(),
            _VideoTrack,
            _AudioTrack,
            _MediaStreamError,
            _MediaPlayer,
            _Hass(),
            "rtsp://agent.local:6554/doorbell",
            lambda: None,
        )
        await media._ensure_reader()
        await media._ensure_reader()
        media.stop()
        with pytest.raises(_MediaStreamError):
            await media.recv("video")

    asyncio.run(_run())

    assert opened == 1


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
    assert boosted.to_ndarray().tolist() == [[2985, -2985, 32767]]
    assert boosted.sample_rate == frame.sample_rate
    assert boosted.pts == frame.pts
    assert boosted.time_base == frame.time_base


def test_doorbell_audio_gain_keeps_original_frame_when_disabled_or_failing() -> None:
    class _BadFrame:
        def to_ndarray(self) -> Any:
            raise RuntimeError("bad")

    frame = _BadFrame()

    assert _apply_audio_gain(SimpleNamespace(), frame, 1.0) is frame
    assert _apply_audio_gain(SimpleNamespace(), frame, DOORSTATION_AUDIO_GAIN) is frame


def test_doorbell_audio_gain_can_attenuate_decoded_frames() -> None:
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

    frame = _FakeAudioFrame(np.array([[1000, -1000]], dtype=np.int16))

    attenuated = _apply_audio_gain(
        SimpleNamespace(AudioFrame=_FakeAudioFrameFactory),
        frame,
        _audio_gain_multiplier(-6.0),
    )

    assert attenuated.to_ndarray().tolist() == [[501, -501]]


def test_doorbell_audio_gain_clips_float_frames() -> None:
    import numpy as np

    class _FakeFormat:
        name = "fltp"

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
            assert format == "fltp"
            assert layout == "mono"
            return _FakeAudioFrame(samples)

    frame = _FakeAudioFrame(np.array([[0.75, -0.75]], dtype=np.float32))

    boosted = _apply_audio_gain(
        SimpleNamespace(AudioFrame=_FakeAudioFrameFactory),
        frame,
        2.0,
    )

    assert boosted.to_ndarray().tolist() == [[1.0, -1.0]]


def test_audio_gain_multiplier_converts_db_to_linear_factor() -> None:
    assert _audio_gain_multiplier(6.0) == pytest.approx(1.995262)
    assert _audio_gain_multiplier(-12.0) == pytest.approx(0.25118864)


def test_video_track_rejects_missing_video_and_stops_audio() -> None:
    stopped: list[str] = []

    class _MediaError(Exception):
        pass

    class _AudioSource:
        def stop(self) -> None:
            stopped.append("audio")

    class _VideoTrack:
        kind = "video"

        def stop(self) -> None:
            stopped.append("wrapper")

    class _MediaPlayer:
        def __init__(self, _url: str, options: dict[str, str]) -> None:
            self.video = None
            self.audio = _AudioSource()

    class _Hass:
        async def async_add_executor_job(self, func: Any) -> Any:
            return func()

    async def _run() -> None:
        track = _new_restarting_rtsp_video_track(
            _VideoTrack,
            _MediaError,
            _MediaPlayer,
            _Hass(),
            "rtsp://agent.local:6554/doorbell",
            lambda: None,
        )
        with pytest.raises(_MediaError):
            await track._async_open_reader()
        track._restart_pending = True
        track._restart_attempts = RTSP_MAX_SESSION_RESTARTS
        with pytest.raises(_MediaError):
            await track._async_open_reader()
        track.stop()

    asyncio.run(_run())

    assert stopped == ["audio", "wrapper"]


def test_audio_track_stops_unused_video_and_restarts_after_reader_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stopped: list[str] = []
    opened: list[int] = []
    restarts: list[str] = []

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(rtsp_reader.asyncio, "sleep", no_sleep)

    class _Frame:
        pass

    class _SourceTrack:
        def __init__(self, kind: str, *, fail: bool = False) -> None:
            self.kind = kind
            self.fail = fail

        async def recv(self) -> _Frame:
            if self.fail:
                raise RuntimeError("lost")
            return _Frame()

        def stop(self) -> None:
            stopped.append(self.kind)

    class _AudioTrack:
        kind = "audio"

        def stop(self) -> None:
            stopped.append("wrapper")

    class _MediaPlayer:
        def __init__(self, _url: str, options: dict[str, str]) -> None:
            opened.append(len(opened))
            self.video = _SourceTrack(f"video-{len(opened)}")
            self.audio = _SourceTrack(f"audio-{len(opened)}", fail=len(opened) == 1)

    class _Hass:
        async def async_add_executor_job(self, func: Any) -> Any:
            return func()

    async def restart_callback() -> None:
        restarts.append("restart")

    async def _run() -> _Frame:
        track = _new_restarting_rtsp_audio_track(
            _AudioTrack,
            Exception,
            _MediaPlayer,
            _Hass(),
            "rtsp://agent.local:6554/doorbell",
            restart_callback,
        )
        try:
            await track._ensure_reader()
            return await track.recv()
        finally:
            track.stop()

    frame = asyncio.run(_run())

    assert isinstance(frame, _Frame)
    assert opened == [0, 1]
    assert restarts == ["restart"]
    assert "video-1" in stopped
    assert "audio-1" in stopped
    assert "video-2" in stopped
    assert "audio-2" in stopped
    assert "wrapper" in stopped


def test_audio_track_rejects_missing_audio_and_stops_video() -> None:
    stopped: list[str] = []

    class _MediaError(Exception):
        pass

    class _VideoSource:
        def stop(self) -> None:
            stopped.append("video")

    class _AudioTrack:
        kind = "audio"

        def stop(self) -> None:
            stopped.append("wrapper")

    class _MediaPlayer:
        def __init__(self, _url: str, options: dict[str, str]) -> None:
            self.video = _VideoSource()
            self.audio = None

    class _Hass:
        async def async_add_executor_job(self, func: Any) -> Any:
            return func()

    async def _run() -> None:
        track = _new_restarting_rtsp_audio_track(
            _AudioTrack,
            _MediaError,
            _MediaPlayer,
            _Hass(),
            "rtsp://agent.local:6554/doorbell",
            lambda: None,
        )
        with pytest.raises(_MediaError):
            await track._async_open_reader()
        track._restart_pending = True
        track._restart_attempts = RTSP_MAX_SESSION_RESTARTS
        with pytest.raises(_MediaError):
            await track._async_open_reader()
        track.stop()

    asyncio.run(_run())

    assert stopped == ["video", "wrapper"]
