"""HA-side C300X ring-call capture helpers."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
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
from .ring_talkback import (
    _create_speex_encoder,
    async_play_announcement_when_ready as _async_play_announcement_when_ready,
)

_RTSP_READY_TIMEOUT_SECONDS = 5.0
_CAPTURE_WORK_DIR = Path("/config/c300x/ring/capture")


async def async_capture_doorbell_ring_call(
    hass: Any,
    entry: Any,
    *,
    output_path: str | None = None,
    wav_output_dir: str | None = None,
    duration_seconds: int = 5,
    include_audio: bool = True,
    announcement_path: str | None = None,
) -> Path:
    """Record a short C300X doorbell RTSP clip on Home Assistant."""

    duration = _validate_duration(duration_seconds)
    target = _capture_output_path(hass, output_path)
    work_dir = _capture_work_dir(hass, wav_output_dir)
    announcement = await _async_announcement_input_path(hass, announcement_path)
    status = await entry.runtime_data.api.async_doorbell_video_status()
    rtsp_url = _rtsp_url_from_status(entry, status, include_audio=include_audio)

    await _async_wait_rtsp_ready(rtsp_url)
    await _async_mkdir(hass, target.parent)
    await _async_mkdir(hass, work_dir)
    capture_task = asyncio.create_task(
        _async_run_ffmpeg(
            rtsp_url,
            target,
            work_dir=work_dir,
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


def _capture_work_dir(hass: Any, wav_output_dir: str | None = None) -> Path:
    if wav_output_dir:
        resolved = _safe_c300x_path(
            hass,
            Path(wav_output_dir).expanduser(),
            "capture WAV output directory",
        )
        if resolved.suffix:
            raise HomeAssistantError(
                "C300X capture WAV output must be a directory, not a file"
            )
        return resolved
    config = getattr(hass, "config", None)
    target = (
        Path(config.path("c300x"))
        if config is not None and hasattr(config, "path")
        else _CAPTURE_WORK_DIR.parent.parent
    )
    return _safe_c300x_path(hass, target, "capture work directory")


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


async def _async_announcement_input_path(
    hass: Any,
    announcement_path: str | None,
) -> Path | None:
    if hasattr(hass, "async_add_executor_job"):
        return await hass.async_add_executor_job(
            _announcement_input_path,
            hass,
            announcement_path,
        )
    return await asyncio.to_thread(_announcement_input_path, hass, announcement_path)


def _safe_c300x_path(hass: Any, target: Path, path_kind: str) -> Path:
    target = _normalize_ha_www_alias(hass, target)
    if not target.is_absolute():
        raise HomeAssistantError(f"C300X {path_kind} path must be absolute")
    try:
        resolved = target.resolve(strict=False)
    except OSError as err:
        raise HomeAssistantError(f"Invalid C300X {path_kind} path") from err

    allowed_roots = [Path("/media/c300x"), Path("/config/c300x")]
    config = getattr(hass, "config", None)
    if config is not None and hasattr(config, "path"):
        allowed_roots.append(Path(config.path("c300x")))
        allowed_roots.append(Path(config.path("media", "c300x")))
        allowed_roots.append(Path(config.path("www", "c300x")))
    else:
        allowed_roots.append(Path("/config/www/c300x"))
    allowed = [_resolve_root(root) for root in allowed_roots]
    if not any(resolved == root or root in resolved.parents for root in allowed):
        raise HomeAssistantError(
            "C300X paths must be below /media/c300x, /config/c300x, or /config/www/c300x"
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
    work_dir: Path | None = None,
    duration_seconds: int,
    include_audio: bool,
) -> None:
    audio_dir = work_dir or target.parent
    raw_audio_target = audio_dir / target.with_suffix(".raw.wav").name
    processed_audio_target = audio_dir / target.with_suffix(".processed.wav").name
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
        "-fflags",
        "nobuffer",
        "-flags",
        "low_delay",
        "-probesize",
        "32768",
        "-analyzeduration",
        "0",
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
                    "volume=6dB,"
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
    if include_audio:
        command.extend(
            [
                "-map",
                "0:a:0?",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(raw_audio_target),
            ]
        )
    await _async_run_ffmpeg_command(
        command,
        timeout=duration_seconds + 10,
        error_prefix="C300X capture failed",
    )
    if include_audio:
        await _async_extract_processed_audio_wav(target, processed_audio_target)


async def _async_extract_processed_audio_wav(source: Path, target: Path) -> None:
    await _async_run_ffmpeg_command(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-map",
            "0:a:0?",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(target),
        ],
        timeout=10,
        error_prefix="C300X processed audio extraction failed",
    )


async def _async_run_ffmpeg_command(
    command: list[str],
    *,
    timeout: int,
    error_prefix: str,
) -> None:
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as err:
        raise HomeAssistantError("ffmpeg is not installed on Home Assistant") from err
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError as err:
        process.kill()
        await process.communicate()
        raise HomeAssistantError(f"{error_prefix}: timed out") from err
    if process.returncode != 0:
        message = stderr.decode("utf-8", "replace").strip()
        raise HomeAssistantError(f"{error_prefix}{': ' + message if message else ''}")
