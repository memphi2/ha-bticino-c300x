"""HA-side C300X ring-call capture helpers."""

from __future__ import annotations

import asyncio
import contextlib
import random
import socket
import struct
import time
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_AGENT_HOST,
    CONF_VIDEO_PORT,
    CONF_VIDEO_STREAM_PATH,
    DEFAULT_VIDEO_PORT,
    DEFAULT_VIDEO_STREAM_PATH,
)
from .entry_config import entry_config_value

_RTSP_READY_TIMEOUT_SECONDS = 5.0
_TALKBACK_RTP_PORT = 40004
_TALKBACK_READY_TIMEOUT_SECONDS = 5.0
_TALKBACK_SAMPLE_RATE = 8000
_TALKBACK_FRAME_SAMPLES = 160
_ANNOUNCEMENT_PREROLL_SECONDS = 1.0


async def async_capture_doorbell_ring_call(
    hass: Any,
    entry: Any,
    *,
    output_path: str | None = None,
    duration_seconds: int = 5,
    include_audio: bool = True,
    announcement_path: str | None = None,
) -> Path:
    """Record a short C300X doorbell RTSP clip on Home Assistant."""

    duration = _validate_duration(duration_seconds)
    target = _capture_output_path(hass, output_path)
    announcement = _announcement_input_path(hass, announcement_path)
    status = await entry.runtime_data.api.async_doorbell_video_status()
    rtsp_url = _rtsp_url_from_status(entry, status, include_audio=include_audio)

    await _async_wait_rtsp_ready(rtsp_url)
    await _async_mkdir(hass, target.parent)
    capture_task = asyncio.create_task(
        _async_run_ffmpeg(
            rtsp_url,
            target,
            duration_seconds=duration,
            include_audio=include_audio,
        )
    )
    announcement_task = (
        asyncio.create_task(
            _async_play_announcement_when_ready(
                entry,
                _agent_host(entry),
                announcement,
            )
        )
        if announcement is not None
        else None
    )
    try:
        await capture_task
        if announcement_task is not None:
            await announcement_task
    finally:
        if announcement_task is not None and not announcement_task.done():
            announcement_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await announcement_task
    return target


def _validate_duration(value: Any) -> int:
    try:
        duration = int(value)
    except (TypeError, ValueError) as err:
        raise HomeAssistantError("Invalid C300X capture duration") from err
    if duration < 1 or duration > 15:
        raise HomeAssistantError("C300X capture duration must be between 1 and 15 seconds")
    return duration


def _capture_output_path(hass: Any, output_path: str | None) -> Path:
    target = (
        Path(output_path).expanduser()
        if output_path
        else Path("/media/c300x")
        / f"doorbell_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.mp4"
    )
    resolved = _safe_c300x_path(hass, target, "capture output")
    if resolved.suffix.lower() != ".mp4":
        raise HomeAssistantError("C300X capture output must be an MP4 file")
    return resolved


def _announcement_input_path(hass: Any, announcement_path: str | None) -> Path | None:
    if not announcement_path:
        return None
    source = _safe_c300x_path(
        hass,
        Path(announcement_path).expanduser(),
        "announcement input",
    )
    if not source.is_file():
        raise HomeAssistantError("C300X announcement file does not exist")
    return source


def _safe_c300x_path(hass: Any, target: Path, path_kind: str) -> Path:
    target = _normalize_ha_www_alias(hass, target)
    if not target.is_absolute():
        raise HomeAssistantError(f"C300X {path_kind} path must be absolute")
    try:
        resolved = target.resolve(strict=False)
    except OSError as err:
        raise HomeAssistantError(f"Invalid C300X {path_kind} path") from err

    allowed_roots = [Path("/media/c300x")]
    config = getattr(hass, "config", None)
    if config is not None and hasattr(config, "path"):
        allowed_roots.append(Path(config.path("www", "c300x")))
    else:
        allowed_roots.append(Path("/config/www/c300x"))
    allowed = [_resolve_root(root) for root in allowed_roots]
    if not any(resolved == root or root in resolved.parents for root in allowed):
        raise HomeAssistantError(
            "C300X paths must be below /media/c300x or /config/www/c300x"
        )
    return resolved


def _normalize_ha_www_alias(hass: Any, target: Path) -> Path:
    if target.parts[:3] != ("/", "www", "c300x"):
        return target
    config = getattr(hass, "config", None)
    if config is None or not hasattr(config, "path"):
        return target
    return Path(config.path("www", "c300x")).joinpath(*target.parts[3:])


def _resolve_root(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except OSError:
        return path


def _rtsp_url_from_status(
    entry: Any,
    status: dict[str, Any],
    *,
    include_audio: bool = False,
) -> str:
    host = _agent_host(entry)
    try:
        port = int(entry_config_value(entry, CONF_VIDEO_PORT, DEFAULT_VIDEO_PORT))
    except (TypeError, ValueError) as err:
        raise HomeAssistantError("C300X RTSP port is invalid") from err
    path = _capture_stream_path(entry, status, include_audio=include_audio)
    return f"rtsp://{host}:{port}{path}"


def _agent_host(entry: Any) -> str:
    host = str(entry_config_value(entry, CONF_AGENT_HOST, "") or "").strip()
    if not host:
        raise HomeAssistantError("C300X agent host is not configured")
    return host


def _capture_stream_path(
    entry: Any,
    status: dict[str, Any],
    *,
    include_audio: bool = False,
) -> str:
    keys = (
        ("audio_stream_path", "recorder_stream_path", "stream_path")
        if include_audio
        else ("recorder_stream_path", "stream_path", "audio_stream_path")
    )
    for key in keys:
        value = status.get(key)
        if isinstance(value, str) and value.strip():
            return _normalize_rtsp_path(value)
    return _normalize_rtsp_path(
        entry_config_value(entry, CONF_VIDEO_STREAM_PATH, DEFAULT_VIDEO_STREAM_PATH)
    )


def _normalize_rtsp_path(value: Any) -> str:
    path = str(value or "").strip() or DEFAULT_VIDEO_STREAM_PATH
    return path if path.startswith("/") else f"/{path}"


async def _async_wait_rtsp_ready(rtsp_url: str) -> None:
    deadline = asyncio.get_running_loop().time() + _RTSP_READY_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while asyncio.get_running_loop().time() < deadline:
        try:
            await _async_rtsp_options(rtsp_url)
            return
        except Exception as err:  # noqa: BLE001
            last_error = err
            await asyncio.sleep(0.2)
    raise HomeAssistantError("C300X RTSP stream was not ready for capture") from last_error


async def _async_rtsp_options(rtsp_url: str) -> None:
    parsed = urlsplit(rtsp_url)
    if parsed.scheme != "rtsp" or not parsed.hostname or not parsed.port:
        raise HomeAssistantError("Invalid C300X RTSP URL")
    reader: asyncio.StreamReader | None = None
    writer: asyncio.StreamWriter | None = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(parsed.hostname, parsed.port),
            timeout=1.0,
        )
        request = (
            f"OPTIONS {rtsp_url} RTSP/1.0\r\n"
            "CSeq: 1\r\n"
            "User-Agent: HomeAssistant-C300X\r\n"
            "\r\n"
        )
        writer.write(request.encode("ascii"))
        await writer.drain()
        response = await asyncio.wait_for(reader.read(128), timeout=1.0)
        first_line = response.splitlines()[0].decode("ascii", "replace") if response else ""
        if not first_line.startswith("RTSP/"):
            raise HomeAssistantError("C300X RTSP bridge returned a non-RTSP response")
        parts = first_line.split()
        if len(parts) < 2 or int(parts[1]) >= 500:
            raise HomeAssistantError(f"C300X RTSP bridge returned {first_line}")
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()


async def _async_mkdir(hass: Any, path: Path) -> None:
    if hasattr(hass, "async_add_executor_job"):
        await hass.async_add_executor_job(lambda: path.mkdir(parents=True, exist_ok=True))
        return
    await asyncio.to_thread(path.mkdir, parents=True, exist_ok=True)


async def _async_run_ffmpeg(
    rtsp_url: str,
    target: Path,
    *,
    duration_seconds: int,
    include_audio: bool,
) -> None:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-fflags",
        "+genpts",
        "-rtsp_transport",
        "tcp",
        "-timeout",
        "5000000",
        "-t",
        str(duration_seconds),
        "-i",
        rtsp_url,
        "-map",
        "0:v:0",
        "-c:v",
        "copy",
    ]
    if include_audio:
        command.extend(
            [
                "-map",
                "0:a:0?",
                "-af",
                (
                    "aresample=48000:async=1:first_pts=0,"
                    "pan=stereo|c0=c0|c1=c0,"
                    "dynaudnorm=f=75:g=31:p=0.95:m=10,"
                    "volume=9dB,"
                    "alimiter=limit=0.95"
                ),
                "-ac",
                "2",
                "-ar",
                "48000",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
            ]
        )
    else:
        command.append("-an")
    command.extend(["-movflags", "+faststart", str(target)])
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as err:
        raise HomeAssistantError("ffmpeg is not installed on Home Assistant") from err
    try:
        _, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=duration_seconds + 10,
        )
    except TimeoutError as err:
        process.kill()
        await process.communicate()
        raise HomeAssistantError("C300X capture timed out") from err
    if process.returncode != 0:
        message = stderr.decode("utf-8", "replace").strip()
        raise HomeAssistantError(
            f"C300X capture failed{': ' + message if message else ''}"
        )


async def _async_play_announcement_when_ready(entry: Any, host: str, source: Path) -> None:
    await _async_wait_talkback_ready(entry)
    await _async_play_announcement(host, source)


async def _async_wait_talkback_ready(entry: Any) -> None:
    deadline = asyncio.get_running_loop().time() + _TALKBACK_READY_TIMEOUT_SECONDS
    last_status: dict[str, Any] | None = None
    while asyncio.get_running_loop().time() < deadline:
        status = await entry.runtime_data.api.async_doorbell_call_status()
        last_status = status if isinstance(status, dict) else None
        if (
            last_status is not None
            and last_status.get("answered") is True
            and last_status.get("audio_active") is True
        ):
            return
        await asyncio.sleep(0.2)
    raise HomeAssistantError(
        "C300X talkback was not ready for announcement playback"
    )


async def _async_play_announcement(host: str, source: Path) -> None:
    """Play one HA-local announcement file into the C300X talkback RTP port."""

    try:
        await asyncio.to_thread(_play_announcement_sync, host, source)
    except HomeAssistantError:
        raise
    except Exception as err:
        raise HomeAssistantError("C300X announcement playback failed") from err


def _play_announcement_sync(host: str, source: Path) -> None:
    try:
        import av
        from av.audio.fifo import AudioFifo
        from av.audio.resampler import AudioResampler
    except ImportError as err:
        raise HomeAssistantError("PyAV is not installed on Home Assistant") from err

    sequence = random.randrange(0, 65536)
    timestamp = random.randrange(0, 2**32)
    ssrc = random.randrange(1, 2**32)
    marker = True
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    target = (host, _TALKBACK_RTP_PORT)
    encoder = _create_speex_encoder(av)
    encoder.sample_rate = _TALKBACK_SAMPLE_RATE
    encoder.layout = "mono"
    encoder.format = "s16"
    encoder.time_base = Fraction(1, _TALKBACK_SAMPLE_RATE)
    encoder.options = {"vbr": "on"}
    encoder.open()
    fifo = AudioFifo()
    resampler = AudioResampler(
        format="s16",
        layout="mono",
        rate=_TALKBACK_SAMPLE_RATE,
    )
    try:
        sequence, timestamp, marker = _send_talkback_silence_preroll(
            av,
            encoder,
            sock,
            target,
            sequence,
            timestamp,
            ssrc,
            marker,
        )
        with av.open(str(source)) as container:
            audio_stream = next(
                (stream for stream in container.streams if stream.type == "audio"),
                None,
            )
            if audio_stream is None:
                raise HomeAssistantError("C300X announcement file has no audio stream")
            for frame in container.decode(audio_stream):
                for resampled in resampler.resample(frame):
                    fifo.write(resampled)
                    sequence, timestamp, marker = _send_ready_talkback_frames(
                        encoder,
                        fifo,
                        sock,
                        target,
                        sequence,
                        timestamp,
                        ssrc,
                        marker,
                    )
            while fifo.samples:
                frame = fifo.read(min(_TALKBACK_FRAME_SAMPLES, fifo.samples))
                if frame is None:
                    break
                sequence, timestamp, marker = _send_encoded_talkback_frame(
                    encoder,
                    frame,
                    sock,
                    target,
                    sequence,
                    timestamp,
                    ssrc,
                    marker,
                )
        for packet in encoder.encode(None):
            payload = bytes(packet)
            if not payload:
                continue
            rtp = _build_talkback_rtp_packet(payload, sequence, timestamp, ssrc, marker)
            sock.sendto(rtp, target)
            sequence = (sequence + 1) & 0xFFFF
            timestamp = (
                timestamp + max(1, int(getattr(packet, "duration", None) or _TALKBACK_FRAME_SAMPLES))
            ) & 0xFFFFFFFF
            marker = False
    finally:
        sock.close()


def _send_talkback_silence_preroll(
    av_module: Any,
    encoder: Any,
    sock: socket.socket,
    target: tuple[str, int],
    sequence: int,
    timestamp: int,
    ssrc: int,
    marker: bool,
) -> tuple[int, int, bool]:
    frames = int(_ANNOUNCEMENT_PREROLL_SECONDS * _TALKBACK_SAMPLE_RATE / _TALKBACK_FRAME_SAMPLES)
    for _ in range(frames):
        frame = av_module.AudioFrame(
            format="s16",
            layout="mono",
            samples=_TALKBACK_FRAME_SAMPLES,
        )
        frame.sample_rate = _TALKBACK_SAMPLE_RATE
        frame.planes[0].update(bytes(frame.planes[0].buffer_size))
        sequence, timestamp, marker = _send_encoded_talkback_frame(
            encoder,
            frame,
            sock,
            target,
            sequence,
            timestamp,
            ssrc,
            marker,
        )
    return sequence, timestamp, marker


def _send_ready_talkback_frames(
    encoder: Any,
    fifo: Any,
    sock: socket.socket,
    target: tuple[str, int],
    sequence: int,
    timestamp: int,
    ssrc: int,
    marker: bool,
) -> tuple[int, int, bool]:
    while fifo.samples >= _TALKBACK_FRAME_SAMPLES:
        frame = fifo.read(_TALKBACK_FRAME_SAMPLES)
        if frame is None:
            break
        sequence, timestamp, marker = _send_encoded_talkback_frame(
            encoder,
            frame,
            sock,
            target,
            sequence,
            timestamp,
            ssrc,
            marker,
        )
    return sequence, timestamp, marker


def _send_encoded_talkback_frame(
    encoder: Any,
    frame: Any,
    sock: socket.socket,
    target: tuple[str, int],
    sequence: int,
    timestamp: int,
    ssrc: int,
    marker: bool,
) -> tuple[int, int, bool]:
    samples = max(1, int(getattr(frame, "samples", _TALKBACK_FRAME_SAMPLES) or _TALKBACK_FRAME_SAMPLES))
    for packet in encoder.encode(frame):
        payload = bytes(packet)
        if not payload:
            continue
        rtp = _build_talkback_rtp_packet(payload, sequence, timestamp, ssrc, marker)
        sock.sendto(rtp, target)
        sequence = (sequence + 1) & 0xFFFF
        timestamp = (
            timestamp + max(1, int(getattr(packet, "duration", None) or samples))
        ) & 0xFFFFFFFF
        marker = False
        time.sleep(samples / _TALKBACK_SAMPLE_RATE)
    return sequence, timestamp, marker


def _create_speex_encoder(av_module: Any) -> Any:
    """Return a Speex encoder using the codec name available in this runtime."""

    last_error: Exception | None = None
    for codec_name in ("speex", "libspeex"):
        try:
            return av_module.CodecContext.create(codec_name, "w")
        except Exception as err:  # noqa: BLE001
            last_error = err
    raise HomeAssistantError("Speex encoding is not available on Home Assistant") from last_error


def _build_talkback_rtp_packet(
    payload: bytes,
    sequence: int,
    timestamp: int,
    ssrc: int,
    marker: bool,
) -> bytes:
    marker_payload = 97 | (0x80 if marker else 0)
    header = struct.pack("!BBHII", 0x80, marker_payload, sequence, timestamp, ssrc)
    return header + payload
