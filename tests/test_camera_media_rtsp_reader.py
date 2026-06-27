from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.bticino_c300x.camera_media import rtsp_reader
from custom_components.bticino_c300x.camera_media.rtsp_reader import (
    DOORSTATION_AUDIO_GAIN,
    RTSP_MAX_SESSION_RESTARTS,
    SharedRTSPMediaSource,
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


def test_shared_rtsp_media_source_reuses_reader_until_last_subscriber_stops() -> None:
    opened_urls: list[str] = []
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
            return 9, "1/90000"

        def stop(self) -> None:
            stopped.append("video-wrapper")

    class _AudioTrack:
        kind = "audio"

        def stop(self) -> None:
            stopped.append("audio-wrapper")

    class _MediaPlayer:
        def __init__(self, url: str, options: dict[str, str]) -> None:
            opened_urls.append(url)
            self.video = _SourceTrack("video")
            self.audio = _SourceTrack("audio")

    class _RelayTrack:
        def __init__(self, track: Any) -> None:
            self.kind = track.kind
            self._track = track
            self.stopped = False

        async def recv(self) -> Any:
            return await self._track.recv()

        def stop(self) -> None:
            self.stopped = True

    class _MediaRelay:
        def subscribe(self, track: Any) -> _RelayTrack:
            return _RelayTrack(track)

    class _Hass:
        async def async_add_executor_job(self, func: Any) -> Any:
            return func()

    async def _run() -> tuple[Any, Any, Any, Any, Any]:
        source = SharedRTSPMediaSource(
            resource_id="ring:test-entry",
            av_module=SimpleNamespace(),
            media_relay_cls=_MediaRelay,
            video_stream_track_cls=_VideoTrack,
            audio_stream_track_cls=_AudioTrack,
            media_stream_error_cls=Exception,
            media_player_cls=_MediaPlayer,
            hass=_Hass(),
            stream_url="rtsp://agent.local:6554/doorbell",
            restart_callback=lambda: None,
        )
        first_handle, first_video, first_audio = source.acquire(include_audio=False)
        second_handle, second_video, second_audio = source.acquire(include_audio=True)
        first_frame = await first_video.recv()
        second_frame = await second_video.recv()
        first_handle.stop()
        closed_after_first = source.closed
        second_handle.stop()
        return first_audio, second_audio, first_frame, second_frame, closed_after_first

    first_audio, second_audio, first_frame, second_frame, closed_after_first = asyncio.run(
        _run()
    )

    assert first_audio is None
    assert second_audio is not None
    assert first_frame.pts == 9
    assert second_frame.pts == 9
    assert opened_urls == ["rtsp://agent.local:6554/doorbell"]
    assert closed_after_first is False
    assert stopped == ["video", "audio"]


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


def test_restarting_rtsp_video_track_restarts_after_first_frame_failure(
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
                raise RuntimeError("first frame missing")
            return _Frame()

        def stop(self) -> None:
            return None

    class _VideoTrack:
        kind = "video"

        async def next_timestamp(self) -> tuple[int, str]:
            return 11, "1/90000"

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
            "rtsp://agent.local:6554/doorbell-video",
            restart_callback,
        )
        try:
            return await track.recv()
        finally:
            track.stop()

    frame = asyncio.run(_run())

    assert frame.pts == 11
    assert opened == [0, 1]
    assert restarts == ["restart"]


def test_restarting_shared_rtsp_tracks_restart_after_first_frame_failure(
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
        def __init__(self, fail: bool = False) -> None:
            self._fail = fail

        async def recv(self) -> _Frame:
            if self._fail:
                raise RuntimeError("first shared frame missing")
            return _Frame()

        def stop(self) -> None:
            return None

    class _VideoTrack:
        kind = "video"

        async def next_timestamp(self) -> tuple[int, str]:
            return 17, "1/90000"

        def stop(self) -> None:
            return None

    class _AudioTrack:
        kind = "audio"

        def stop(self) -> None:
            return None

    class _MediaPlayer:
        def __init__(self, _url: str, options: dict[str, str]) -> None:
            assert options["rtsp_transport"] == "tcp"
            opened.append(len(opened))
            self.video = _SourceTrack(fail=len(opened) == 1)
            self.audio = _SourceTrack()

    class _Hass:
        async def async_add_executor_job(self, func: Any) -> Any:
            return func()

    async def restart_callback() -> None:
        restarts.append("restart")

    async def _run() -> _Frame:
        media, video_track, _audio_track = _new_restarting_rtsp_tracks(
            SimpleNamespace(),
            _VideoTrack,
            _AudioTrack,
            Exception,
            _MediaPlayer,
            _Hass(),
            "rtsp://agent.local:6554/doorbell",
            restart_callback,
        )
        try:
            return await video_track.recv()
        finally:
            media.stop()

    frame = asyncio.run(_run())

    assert frame.pts == 17
    assert opened == [0, 1]
    assert restarts == ["restart"]


def test_restarting_rtsp_tracks_logs_once_when_video_stalls_after_audio(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[int] = []

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(rtsp_reader.asyncio, "sleep", no_sleep)

    class _MediaError(Exception):
        pass

    class _Frame:
        pts: int | None = None
        time_base: object | None = None

    class _SourceTrack:
        def __init__(self, kind: str) -> None:
            self.kind = kind

        async def recv(self) -> _Frame:
            if self.kind == "video":
                raise TimeoutError("video frame timeout")
            return _Frame()

        def stop(self) -> None:
            return None

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

    class _MediaPlayer:
        def __init__(self, _url: str, options: dict[str, str]) -> None:
            assert options["rtsp_transport"] == "tcp"
            opened.append(len(opened))
            self.video = _SourceTrack("video")
            self.audio = _SourceTrack("audio")

    class _Hass:
        async def async_add_executor_job(self, func: Any) -> Any:
            return func()

    async def restart_callback() -> bool:
        return False

    async def _run() -> None:
        media, video_track, audio_track = _new_restarting_rtsp_tracks(
            SimpleNamespace(),
            _VideoTrack,
            _AudioTrack,
            _MediaError,
            _MediaPlayer,
            _Hass(),
            "rtsp://agent.local:6554/doorbell",
            restart_callback,
            diagnostic_label="session=test owner=doorbell mode=audio_video audio=True",
        )
        try:
            await audio_track.recv()
            with pytest.raises(_MediaError):
                await video_track.recv()
        finally:
            media.stop()

    with caplog.at_level(
        logging.DEBUG,
        logger="custom_components.bticino_c300x.camera_media.rtsp_reader",
    ):
        asyncio.run(_run())

    stall_logs = [
        record
        for record in caplog.records
        if "C300X WebRTC RTSP video frame stalled" in record.message
    ]
    assert len(stall_logs) == 1
    assert "path=/doorbell" in stall_logs[0].message
    assert "audio_frames=1" in stall_logs[0].message
    assert "video_frames=0" in stall_logs[0].message
    assert "reason=TimeoutError" in stall_logs[0].message
    assert opened == [0]


def test_restarting_rtsp_audio_track_restarts_after_first_frame_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[int] = []
    restarts: list[str] = []

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(rtsp_reader.asyncio, "sleep", no_sleep)

    class _Frame:
        pass

    class _SourceTrack:
        def __init__(self, fail: bool) -> None:
            self._fail = fail

        async def recv(self) -> _Frame:
            if self._fail:
                raise RuntimeError("first audio frame missing")
            return _Frame()

        def stop(self) -> None:
            return None

    class _AudioTrack:
        kind = "audio"

        def stop(self) -> None:
            return None

    class _MediaPlayer:
        def __init__(self, _url: str, options: dict[str, str]) -> None:
            assert options["rtsp_transport"] == "tcp"
            opened.append(len(opened))
            self.video = None
            self.audio = _SourceTrack(fail=len(opened) == 1)

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
            "rtsp://agent.local:6554/home-call",
            restart_callback,
        )
        try:
            return await track.recv()
        finally:
            track.stop()

    frame = asyncio.run(_run())

    assert isinstance(frame, _Frame)
    assert opened == [0, 1]
    assert restarts == ["restart"]


def test_restarting_rtsp_video_track_stops_when_restart_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[int] = []
    restarts: list[str] = []

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(rtsp_reader.asyncio, "sleep", no_sleep)

    class _MediaError(Exception):
        pass

    class _SourceTrack:
        async def recv(self) -> object:
            raise RuntimeError("closed")

        def stop(self) -> None:
            return None

    class _VideoTrack:
        kind = "video"

        async def next_timestamp(self) -> tuple[int, str]:
            return 1, "1/90000"

        def stop(self) -> None:
            return None

    class _MediaPlayer:
        def __init__(self, _url: str, options: dict[str, str]) -> None:
            opened.append(len(opened))
            self.video = _SourceTrack()
            self.audio = None

    class _Hass:
        async def async_add_executor_job(self, func: Any) -> Any:
            return func()

    async def restart_callback() -> bool:
        restarts.append("restart")
        return False

    async def _run() -> None:
        track = _new_restarting_rtsp_video_track(
            _VideoTrack,
            _MediaError,
            _MediaPlayer,
            _Hass(),
            "rtsp://agent.local:6554/doorbell-video",
            restart_callback,
        )
        await track._ensure_reader()
        track._restart_pending = True
        with pytest.raises(_MediaError):
            await track._async_open_reader()
        track.stop()

    asyncio.run(_run())

    assert opened == [0]
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
