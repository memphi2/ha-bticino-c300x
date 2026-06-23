"""Restarting RTSP reader helpers for C300X WebRTC media tracks."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

from ..const import DEFAULT_DOORSTATION_AUDIO_GAIN_DB

RTSP_FRAME_TIMEOUT_SECONDS = 5.0
RTSP_MAX_SESSION_RESTARTS = 3
DOORSTATION_AUDIO_GAIN_DB = DEFAULT_DOORSTATION_AUDIO_GAIN_DB
DOORSTATION_AUDIO_GAIN = 10 ** (DOORSTATION_AUDIO_GAIN_DB / 20)
RestartCallback = Callable[[], Awaitable[bool | None]]

_RTSP_PLAYER_OPTIONS = {
    "rtsp_transport": "tcp",
    "timeout": "5000000",
    "fflags": "nobuffer",
    "flags": "low_delay",
    "probesize": "32768",
    "analyzeduration": "0",
}


def _new_restarting_rtsp_tracks(
    av_module: Any,
    video_stream_track_cls: Any,
    audio_stream_track_cls: Any,
    media_stream_error_cls: type[Exception],
    media_player_cls: Any,
    hass: Any,
    stream_url: str,
    restart_callback: RestartCallback,
    audio_gain_db: float = DOORSTATION_AUDIO_GAIN_DB,
    require_audio: bool = True,
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
                had_reader = False
                try:
                    await self._ensure_reader()
                    had_reader = self._player is not None
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
                if await restart_callback() is False:
                    self._stopped = True
                    raise media_stream_error_cls
            self._opened_once = True
            player = await hass.async_add_executor_job(
                lambda: media_player_cls(
                    stream_url,
                    options=_RTSP_PLAYER_OPTIONS,
                )
            )
            if player.video is None or (require_audio and player.audio is None):
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
                _audio_gain_multiplier(audio_gain_db),
            )

        def stop(self) -> None:
            media.stop()
            super().stop()

    return media, RestartingRTSPVideoTrack(), RestartingRTSPAudioTrack()


class SharedRTSPMediaHandle:
    """Reference-counted subscription to one shared RTSP source."""

    def __init__(
        self,
        source: SharedRTSPMediaSource,
        tracks: list[Any],
    ) -> None:
        self.resource_id = source.resource_id
        self._source = source
        self._tracks = tracks
        self._stopped = False

    def stop(self) -> None:
        """Stop this subscriber without stopping other subscribers."""

        if self._stopped:
            return
        self._stopped = True
        for track in self._tracks:
            with suppress(Exception):
                track.stop()
        self._source.release()


class SharedRTSPMediaSource:
    """Fan out one restarting RTSP reader to multiple WebRTC peers."""

    def __init__(
        self,
        *,
        resource_id: str,
        av_module: Any,
        media_relay_cls: Any,
        video_stream_track_cls: Any,
        audio_stream_track_cls: Any,
        media_stream_error_cls: type[Exception],
        media_player_cls: Any,
        hass: Any,
        stream_url: str,
        restart_callback: RestartCallback,
        audio_gain_db: float = DOORSTATION_AUDIO_GAIN_DB,
    ) -> None:
        self.resource_id = resource_id
        self.stream_url = stream_url
        self._relay = media_relay_cls()
        self._ref_count = 0
        self._closed = False
        self._media, self._video_source, self._audio_source = _new_restarting_rtsp_tracks(
            av_module,
            video_stream_track_cls,
            audio_stream_track_cls,
            media_stream_error_cls,
            media_player_cls,
            hass,
            stream_url,
            restart_callback,
            audio_gain_db=audio_gain_db,
            require_audio=False,
        )

    @property
    def closed(self) -> bool:
        """Return true once the shared source has been stopped."""

        return self._closed

    def acquire(self, *, include_audio: bool) -> tuple[SharedRTSPMediaHandle, Any, Any | None]:
        """Return per-peer relay tracks backed by this shared source."""

        if self._closed:
            raise RuntimeError("shared RTSP source is closed")
        self._ref_count += 1
        video_track = self._relay.subscribe(self._video_source)
        tracks = [video_track]
        audio_track = None
        if include_audio:
            audio_track = self._relay.subscribe(self._audio_source)
            tracks.append(audio_track)
        return SharedRTSPMediaHandle(self, tracks), video_track, audio_track

    def release(self) -> None:
        """Release one subscriber and stop the source after the last one."""

        if self._ref_count > 0:
            self._ref_count -= 1
        if self._ref_count == 0:
            self.stop()

    def stop(self) -> None:
        """Stop the underlying RTSP reader."""

        if self._closed:
            return
        self._closed = True
        self._media.stop()


def _apply_audio_gain(av_module: Any, frame: Any, gain: float) -> Any:
    """Boost decoded doorstation audio before HA sends it through WebRTC."""

    if gain == 1:
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


def _audio_gain_multiplier(gain_db: float) -> float:
    """Return a linear gain multiplier for a bounded dB value."""

    return math.pow(10.0, float(gain_db) / 20.0)


def _init_restarting_rtsp_track(track: Any) -> None:
    """Initialize shared RTSP restart state on a WebRTC media track."""

    track._player = None
    track._track = None
    track._opened_once = False
    track._restart_pending = False
    track._restart_attempts = 0
    track._retry_delay = 0.2
    track._stopped = False
    track._lock = asyncio.Lock()


async def _ensure_restarting_rtsp_reader(track: Any) -> None:
    """Open a shared RTSP reader once for a restart-capable media track."""

    if track._track is not None:
        return

    async with track._lock:
        if track._track is not None:
            return
        await track._async_open_reader()


def _new_restarting_rtsp_video_track(
    video_stream_track_cls: Any,
    media_stream_error_cls: type[Exception],
    media_player_cls: Any,
    hass: Any,
    stream_url: str,
    restart_callback: RestartCallback,
) -> Any:
    """Create the proven video-only RTSP track for the C300X bridge."""

    class RestartingRTSPVideoTrack(video_stream_track_cls):
        kind = "video"

        def __init__(self) -> None:
            super().__init__()
            _init_restarting_rtsp_track(self)

        async def recv(self) -> Any:
            while not self._stopped:
                had_reader = False
                try:
                    await self._ensure_reader()
                    had_reader = self._track is not None
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
            await _ensure_restarting_rtsp_reader(self)

        async def _async_open_reader(self) -> None:
            await self._async_close_reader()
            if self._restart_pending:
                self._restart_pending = False
                if self._restart_attempts >= RTSP_MAX_SESSION_RESTARTS:
                    raise media_stream_error_cls
                self._restart_attempts += 1
                if await restart_callback() is False:
                    self._stopped = True
                    raise media_stream_error_cls
            self._opened_once = True
            player = await hass.async_add_executor_job(
                lambda: media_player_cls(
                    stream_url,
                    options=_RTSP_PLAYER_OPTIONS,
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
    hass: Any,
    stream_url: str,
    restart_callback: RestartCallback,
    av_module: Any | None = None,
    audio_gain_db: float = DOORSTATION_AUDIO_GAIN_DB,
) -> Any:
    """Create an audio-only RTSP track for local Home Call media."""

    class RestartingRTSPAudioTrack(audio_stream_track_cls):
        kind = "audio"

        def __init__(self) -> None:
            super().__init__()
            _init_restarting_rtsp_track(self)

        async def recv(self) -> Any:
            while not self._stopped:
                had_reader = False
                try:
                    await self._ensure_reader()
                    had_reader = self._track is not None
                    frame = await asyncio.wait_for(
                        self._track.recv(),
                        timeout=RTSP_FRAME_TIMEOUT_SECONDS,
                    )
                    self._restart_attempts = 0
                    self._retry_delay = 0.2
                    return _apply_audio_gain(
                        av_module,
                        frame,
                        _audio_gain_multiplier(audio_gain_db),
                    )
                except Exception:
                    if had_reader and self._opened_once:
                        self._restart_pending = True
                    await self._async_close_reader()
                    await asyncio.sleep(self._retry_delay)
                    self._retry_delay = min(self._retry_delay * 2, 2.0)

            raise media_stream_error_cls

        async def _ensure_reader(self) -> None:
            await _ensure_restarting_rtsp_reader(self)

        async def _async_open_reader(self) -> None:
            await self._async_close_reader()
            if self._restart_pending:
                self._restart_pending = False
                if self._restart_attempts >= RTSP_MAX_SESSION_RESTARTS:
                    raise media_stream_error_cls
                self._restart_attempts += 1
                if await restart_callback() is False:
                    self._stopped = True
                    raise media_stream_error_cls
            self._opened_once = True
            player = await hass.async_add_executor_job(
                lambda: media_player_cls(
                    stream_url,
                    options=_RTSP_PLAYER_OPTIONS,
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
