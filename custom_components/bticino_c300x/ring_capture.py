"""HA-side C300X ring-call capture helpers."""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import uuid4

from homeassistant.exceptions import HomeAssistantError

from .camera_media.rtsp_policy import (
    RtspConsumer,
    decide_rtsp_admission,
    rtsp_resource_snapshot_from_status,
)
from .camera_media.rtsp_probe import async_probe_rtsp_url
from .camera_media.rtsp_url import (
    agent_host_for_socket as _agent_host_for_socket_value,
)
from .camera_media.rtsp_url import (
    agent_host_for_url as _agent_host_for_url_value,
)
from .camera_media.rtsp_url import (
    normalize_rtsp_path as _normalize_rtsp_path_value,
)
from .camera_media.state_machine import (
    derive_media_state,
    media_state_input_from_video_status,
)
from .config_audio import AUDIO_GAIN_DB_MAX, AUDIO_GAIN_DB_MIN
from .const import (
    CONF_AGENT_HOST,
    CONF_RING_CAPTURE_AUDIO_GAIN_DB,
    CONF_VIDEO_PORT,
    CONF_VIDEO_STREAM_PATH,
    DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB,
    DEFAULT_VIDEO_PORT,
    DEFAULT_VIDEO_STREAM_PATH,
)
from .entry_config import entry_config_value
from .error_text import compact_error_text
from .json_io import async_write_json_file
from .ring_talkback import (
    async_keep_talkback_alive_when_ready as _async_keep_talkback_alive_when_ready,
)
from .value_parsing import optional_mapping

_RTSP_READY_TIMEOUT_SECONDS = 5.0
_CAPTURE_WORK_DIR = Path("/config/c300x")
_CAPTURE_FRAME_COUNT = 3
_CAPTURE_FRAME_START_SECONDS = 1.0
_CAPTURE_FRAME_END_MARGIN_SECONDS = 0.2
DEFAULT_RING_CAPTURE_METADATA_GLOB = "/config/c300x/*.capture.json"


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
    raise_if_ring_capture_blocked(status)
    rtsp_url = _rtsp_url_from_status(entry, status, include_audio=include_audio)
    audio_gain_db = _capture_audio_gain_db(entry)

    await _async_wait_rtsp_ready(rtsp_url)
    await _async_mkdir(hass, target.parent)
    await _async_mkdir(hass, work_dir)
    codec_pcmu = (
        await _async_talkback_codec_is_pcmu(entry, status)
        if include_audio or announcement is not None
        else False
    )
    capture_task = asyncio.create_task(
        _async_run_ffmpeg(
            rtsp_url,
            target,
            work_dir=work_dir,
            duration_seconds=duration,
            include_audio=include_audio,
            audio_gain_db=audio_gain_db,
        )
    )
    talkback_stop = threading.Event()
    talkback_task: asyncio.Task[None] | None = None
    if include_audio or announcement is not None:
        talkback_task = asyncio.create_task(
            _async_keep_talkback_alive_when_ready(
                entry,
                _agent_host(entry),
                announcement,
                talkback_stop,
                codec_pcmu=codec_pcmu,
            )
        )
    try:
        await capture_task
        if talkback_task is not None:
            talkback_stop.set()
            if talkback_task.done():
                await talkback_task
            else:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(talkback_task, timeout=2.0)
            if not talkback_task.done():
                talkback_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await talkback_task
        await async_write_json_file(
            hass,
            _capture_metadata_path(work_dir),
            _capture_metadata_payload(
                capture_id=uuid4().hex,
                target=target,
                work_dir=work_dir,
                rtsp_url=rtsp_url,
                status=status,
                duration_seconds=duration,
                include_audio=include_audio,
                announcement_used=announcement is not None,
            ),
        )
    finally:
        talkback_stop.set()
        if talkback_task is not None and not talkback_task.done():
            talkback_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await talkback_task
    return target


def _normalized_audio_codec(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    codec = value.strip().lower()
    if codec in {"pcmu", "speex"}:
        return codec
    if codec.startswith("pcmu/"):
        return "pcmu"
    if codec.startswith("speex/"):
        return "speex"
    return None


def _record_talkback_codec(entry: Any, codec: str) -> None:
    try:
        entry.runtime_data.event_state.audio_codec = codec
    except Exception:  # noqa: BLE001
        return


def _status_talkback_codec(status: Mapping[str, Any]) -> str | None:
    bridge = optional_mapping(status.get("bridge"))
    for value in (
        bridge.get("device_audio_codec"),
        status.get("device_audio_codec"),
        bridge.get("running_audio_codec"),
        status.get("running_audio_codec"),
        bridge.get("talkback_codec"),
        status.get("talkback_codec"),
    ):
        codec = _normalized_audio_codec(value)
        if codec is not None:
            return codec
    return None


def _cached_talkback_codec(entry: Any) -> str | None:
    try:
        return _normalized_audio_codec(entry.runtime_data.event_state.audio_codec)
    except Exception:  # noqa: BLE001
        return None


def _talkback_codec_is_pcmu(entry: Any) -> bool:
    """Return True when the device's last-known running codec is PCMU.

    The audio_codec select publishes the resolved device codec into shared
    This legacy helper is intentionally cache-only; capture paths use
    _async_talkback_codec_is_pcmu so an unresolved cache is refreshed before
    talkback starts.
    """

    return _cached_talkback_codec(entry) == "pcmu"


async def _async_talkback_codec_is_pcmu(
    entry: Any,
    status: Mapping[str, Any],
) -> bool:
    codec = _status_talkback_codec(status) or _cached_talkback_codec(entry)
    if codec is None:
        api = getattr(getattr(entry, "runtime_data", None), "api", None)
        status_fn = getattr(api, "async_audio_codec_status", None)
        if not callable(status_fn):
            raise HomeAssistantError("C300X talkback codec is unknown")
        try:
            refreshed = await status_fn()
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(
                f"C300X talkback codec is unknown: {compact_error_text(err)}"
            ) from err
        if isinstance(refreshed, Mapping):
            codec = _normalized_audio_codec(
                refreshed.get("running_state", refreshed.get("state"))
            )
    if codec is None:
        raise HomeAssistantError("C300X talkback codec is unknown")
    _record_talkback_codec(entry, codec)
    return codec == "pcmu"


def _capture_metadata_path(work_dir: Path) -> Path:
    """Return the local metadata path for one C300X ring capture."""

    return work_dir / "latest.capture.json"


def _capture_raw_audio_path(work_dir: Path) -> Path:
    return work_dir / "latest.raw.wav"


def _capture_processed_audio_path(work_dir: Path) -> Path:
    return work_dir / "latest.processed.wav"


def _capture_frame_path(work_dir: Path, index: int) -> Path:
    return work_dir / f"frame_{index:02d}.jpg"


def _capture_metadata_payload(
    *,
    capture_id: str,
    target: Path,
    work_dir: Path,
    rtsp_url: str,
    status: Mapping[str, Any],
    duration_seconds: int,
    include_audio: bool,
    announcement_used: bool,
) -> dict[str, Any]:
    bridge_status = optional_mapping(status.get("bridge"))
    payload: dict[str, Any] = {
        "capture_id": capture_id,
        "created_at": datetime.now(UTC).isoformat(),
        "kind": "doorbell_ring_capture",
        "output_path": str(target),
        "metadata_path": str(_capture_metadata_path(work_dir)),
        "duration_seconds": duration_seconds,
        "include_audio": include_audio,
        "announcement_used": announcement_used,
        "rtsp_path": urlsplit(rtsp_url).path,
        "video_owner": status.get("video_owner") or bridge_status.get("media_owner"),
        "media_state": status.get("media_state"),
        "ring_call_active": bool(
            status.get("ring_call_active") or bridge_status.get("ring_call_active")
        ),
        "ring_media_active": bool(
            status.get("ring_media_active") or bridge_status.get("ring_media_active")
        ),
        "frames": [
            str(_capture_frame_path(work_dir, index))
            for index in range(1, _CAPTURE_FRAME_COUNT + 1)
        ],
    }
    if include_audio:
        payload["raw_wav_path"] = str(_capture_raw_audio_path(work_dir))
        payload["processed_wav_path"] = str(
            _capture_processed_audio_path(work_dir)
        )
    return payload


def raise_if_ring_capture_blocked(status: Mapping[str, Any]) -> None:
    """Reject capture when factual media state or RTSP policy blocks it."""

    media_decision = derive_media_state(media_state_input_from_video_status(status))
    decision = decide_rtsp_admission(
        RtspConsumer.CAPTURE,
        rtsp_resource_snapshot_from_status(status),
    )
    if decision.allowed and not media_decision.capture_blocked:
        return
    reason = (
        f"media_state_{media_decision.state.value}"
        if media_decision.capture_blocked
        else decision.reason
    )
    raise HomeAssistantError(f"C300X ring capture busy: {reason}")


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
        else _CAPTURE_WORK_DIR
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
        return cast(
            Path | None,
            await hass.async_add_executor_job(
                _announcement_input_path,
                hass,
                announcement_path,
            ),
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
    status: Mapping[str, Any],
    *,
    include_audio: bool = False,
) -> str:
    host = _agent_host_for_url(_agent_host(entry))
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


def _capture_audio_gain_db(entry: Any) -> float:
    """Return configured ring capture audio gain in dB."""

    try:
        gain = float(
            entry_config_value(
                entry,
                CONF_RING_CAPTURE_AUDIO_GAIN_DB,
                DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB,
            )
        )
    except (TypeError, ValueError):
        return DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB
    return min(AUDIO_GAIN_DB_MAX, max(AUDIO_GAIN_DB_MIN, gain))


def _agent_host_for_socket(host: str) -> str:
    return _agent_host_for_socket_value(host)


def _agent_host_for_url(host: str) -> str:
    return _agent_host_for_url_value(host)


def _capture_stream_path(
    entry: Any,
    status: Mapping[str, Any],
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
    return _normalize_rtsp_path_value(value, default_path=DEFAULT_VIDEO_STREAM_PATH)


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
    await async_probe_rtsp_url(
        rtsp_url,
        method="OPTIONS",
        timeout_seconds=1.0,
        read_size=128,
        user_agent="HomeAssistant-C300X",
        reject_status_from=500,
    )


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
    audio_gain_db: float = DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB,
) -> None:
    audio_dir = work_dir or target.parent
    raw_audio_target = _capture_raw_audio_path(audio_dir)
    processed_audio_target = _capture_processed_audio_path(audio_dir)
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
                    f"volume={audio_gain_db:g}dB,"
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
        command_timeout=duration_seconds + 10,
        error_prefix="C300X capture failed",
    )
    if include_audio:
        await _async_extract_processed_audio_wav(target, processed_audio_target)
    await _async_extract_capture_frames(
        target,
        audio_dir,
        duration_seconds=duration_seconds,
    )


def _capture_frame_offsets(duration_seconds: int) -> tuple[float, float, float]:
    """Return stable still-frame offsets for the captured MP4."""

    duration = max(0.1, float(duration_seconds))
    first = (
        _CAPTURE_FRAME_START_SECONDS
        if duration > _CAPTURE_FRAME_START_SECONDS
        else max(0.1, duration / 2)
    )
    last = max(first, duration - _CAPTURE_FRAME_END_MARGIN_SECONDS)
    middle = first + ((last - first) / 2)
    return (first, middle, last)


async def _async_extract_capture_frames(
    source: Path,
    output_dir: Path,
    *,
    duration_seconds: int,
) -> None:
    """Extract analysis still frames from a captured MP4."""

    for index, offset in enumerate(_capture_frame_offsets(duration_seconds), start=1):
        target = _capture_frame_path(output_dir, index)
        await _async_run_ffmpeg_command(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-ss",
                f"{offset:.3f}",
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(target),
            ],
            command_timeout=10,
            error_prefix="C300X frame extraction failed",
        )


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
        command_timeout=10,
        error_prefix="C300X processed audio extraction failed",
    )


async def _async_run_ffmpeg_command(
    command: list[str],
    *,
    command_timeout: int,
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
        _, stderr = await asyncio.wait_for(
            process.communicate(), timeout=command_timeout
        )
    except TimeoutError as err:
        process.kill()
        await process.communicate()
        raise HomeAssistantError(f"{error_prefix}: timed out") from err
    if process.returncode != 0:
        message = stderr.decode("utf-8", "replace").strip()
        raise HomeAssistantError(f"{error_prefix}{': ' + message if message else ''}")
