"""Local C300X ring-call speech analysis helpers."""

from __future__ import annotations

import asyncio
import contextlib
import json
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from homeassistant.exceptions import HomeAssistantError

from .json_io import async_write_json_file
from .ring_capture import DEFAULT_RING_CAPTURE_METADATA_GLOB, _safe_c300x_path

DEFAULT_RING_WAV_GLOB = "/config/c300x/*.raw.wav"
DEFAULT_RING_AI_RESULT_PATH = "/config/c300x/analysis/result.json"
_DEFAULT_RING_WAV_PATTERN = "*.raw.wav"
_DEFAULT_RING_CAPTURE_METADATA_PATTERN = "*.capture.json"
_WYOMING_CHUNK_BYTES = 8192
_WYOMING_TIMEOUT_SECONDS = 60


async def async_run_wyoming_ring_analysis(
    hass: Any,
    *,
    wyoming_host: str,
    wyoming_port: int = 10300,
    capture_path: str | None = None,
    wav_path: str | None = None,
    result_path: str | None = None,
    language: str | None = None,
    expected_phrase: str | None = None,
) -> Path:
    """Transcribe an existing ring-call raw WAV through Wyoming Whisper."""

    host = wyoming_host.strip()
    if not host:
        raise HomeAssistantError("C300X Wyoming Whisper host is required")
    source = await _async_ring_analysis_source(
        hass,
        capture_path=capture_path,
        wav_path=wav_path,
    )
    target = _result_path(hass, result_path)
    wav = await _async_read_wav(hass, source["wav_path"])
    transcript = await _async_wyoming_transcribe(
        host,
        wyoming_port,
        wav,
        language=language,
    )
    await async_write_json_file(
        hass,
        target,
        _normalize_wyoming_result(
            transcript,
            wav_path=str(source["wav_path"]),
            capture_path=source.get("capture_path"),
            capture_payload=source.get("capture_payload"),
            expected_phrase=expected_phrase,
        ),
    )
    return target


def _ring_analysis_source(
    hass: Any,
    *,
    capture_path: str | None,
    wav_path: str | None,
) -> dict[str, Any]:
    capture_file: Path | None = None
    capture_payload: dict[str, Any] | None = None
    if capture_path:
        capture_file = _ring_capture_metadata_path(hass, capture_path)
        capture_payload = _read_capture_metadata(capture_file)
        metadata_wav = _capture_metadata_wav_path(hass, capture_payload)
        if wav_path:
            explicit_wav = _ring_wav_path(hass, wav_path)
            if explicit_wav != metadata_wav:
                raise HomeAssistantError(
                    "C300X ring analysis WAV does not match capture metadata"
                )
        return {
            "wav_path": metadata_wav,
            "capture_path": capture_file,
            "capture_payload": capture_payload,
        }
    if wav_path:
        return {"wav_path": _ring_wav_path(hass, wav_path)}
    try:
        capture_file = _latest_ring_capture_metadata_path(hass)
        capture_payload = _read_capture_metadata(capture_file)
        return {
            "wav_path": _capture_metadata_wav_path(hass, capture_payload),
            "capture_path": capture_file,
            "capture_payload": capture_payload,
        }
    except HomeAssistantError:
        return {"wav_path": _latest_ring_wav_path(hass)}


async def _async_ring_analysis_source(
    hass: Any,
    *,
    capture_path: str | None,
    wav_path: str | None,
) -> dict[str, Any]:
    if hasattr(hass, "async_add_executor_job"):
        return cast(
            dict[str, Any],
            await hass.async_add_executor_job(
                lambda: _ring_analysis_source(
                    hass,
                    capture_path=capture_path,
                    wav_path=wav_path,
                )
            ),
        )
    return await asyncio.to_thread(
        _ring_analysis_source,
        hass,
        capture_path=capture_path,
        wav_path=wav_path,
    )


def _ring_wav_path(hass: Any, wav_path: str | None) -> Path:
    if not wav_path:
        return _latest_ring_wav_path(hass)
    source = _safe_c300x_path(hass, Path(wav_path).expanduser(), "ring analysis WAV")
    return _validate_ring_wav(source)


def _latest_ring_wav_path(hass: Any) -> Path:
    candidates = sorted(_ring_wav_candidates(hass), key=_safe_mtime, reverse=True)
    if not candidates:
        raise HomeAssistantError(
            f"C300X ring analysis found no WAV files matching {DEFAULT_RING_WAV_GLOB}"
        )
    return _validate_ring_wav(candidates[0])


def _ring_wav_candidates(hass: Any) -> list[Path]:
    roots = [Path("/config/c300x")]
    config = getattr(hass, "config", None)
    if config is not None and hasattr(config, "path"):
        roots.append(Path(config.path("c300x")))

    candidates: dict[str, Path] = {}
    for root in roots:
        try:
            resolved_root = root.resolve(strict=False)
        except OSError:
            continue
        if not resolved_root.exists():
            continue
        for path in resolved_root.glob(_DEFAULT_RING_WAV_PATTERN):
            with contextlib.suppress(OSError):
                if path.is_file():
                    candidates[str(path.resolve(strict=False))] = path
    return list(candidates.values())


def _ring_capture_metadata_path(hass: Any, capture_path: str) -> Path:
    source = _safe_c300x_path(
        hass,
        Path(capture_path).expanduser(),
        "ring capture metadata",
    )
    return _validate_capture_metadata_path(source)


def _latest_ring_capture_metadata_path(hass: Any) -> Path:
    candidates = sorted(
        _ring_capture_metadata_candidates(hass),
        key=_safe_mtime,
        reverse=True,
    )
    if not candidates:
        raise HomeAssistantError(
            "C300X ring analysis found no capture metadata files matching "
            f"{DEFAULT_RING_CAPTURE_METADATA_GLOB}"
        )
    return _validate_capture_metadata_path(candidates[0])


def _ring_capture_metadata_candidates(hass: Any) -> list[Path]:
    roots = [Path("/config/c300x")]
    config = getattr(hass, "config", None)
    if config is not None and hasattr(config, "path"):
        roots.append(Path(config.path("c300x")))

    candidates: dict[str, Path] = {}
    for root in roots:
        try:
            resolved_root = root.resolve(strict=False)
        except OSError:
            continue
        if not resolved_root.exists():
            continue
        for path in resolved_root.glob(_DEFAULT_RING_CAPTURE_METADATA_PATTERN):
            with contextlib.suppress(OSError):
                if path.is_file():
                    candidates[str(path.resolve(strict=False))] = path
    return list(candidates.values())


def _validate_capture_metadata_path(path: Path) -> Path:
    if path.suffix.lower() != ".json" or not path.name.endswith(".capture.json"):
        raise HomeAssistantError("C300X ring capture metadata must be a capture JSON file")
    if not path.is_file():
        raise HomeAssistantError("C300X ring capture metadata file does not exist")
    return path


def _read_capture_metadata(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise HomeAssistantError("C300X ring capture metadata is invalid JSON") from err
    if not isinstance(data, dict):
        raise HomeAssistantError("C300X ring capture metadata must be a JSON object")
    capture_id = str(data.get("capture_id") or "").strip()
    if not capture_id:
        raise HomeAssistantError("C300X ring capture metadata has no capture_id")
    return data


def _capture_metadata_wav_path(hass: Any, payload: dict[str, Any]) -> Path:
    wav_path = str(payload.get("raw_wav_path") or "").strip()
    if not wav_path:
        raise HomeAssistantError("C300X ring capture metadata has no raw WAV path")
    return _ring_wav_path(hass, wav_path)


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _validate_ring_wav(path: Path) -> Path:
    if path.suffix.lower() != ".wav":
        raise HomeAssistantError("C300X ring analysis input must be a WAV file")
    if not path.is_file():
        raise HomeAssistantError("C300X ring analysis WAV file does not exist")
    return path


def _result_path(hass: Any, result_path: str | None) -> Path:
    target = _safe_c300x_path(
        hass,
        Path(result_path or DEFAULT_RING_AI_RESULT_PATH).expanduser(),
        "ring analysis result",
    )
    if target.suffix.lower() != ".json":
        raise HomeAssistantError("C300X ring analysis result path must be a JSON file")
    return target


async def _async_read_wav(hass: Any, path: Path) -> dict[str, Any]:
    def _read() -> dict[str, Any]:
        with wave.open(str(path), "rb") as wav:
            width = wav.getsampwidth()
            channels = wav.getnchannels()
            rate = wav.getframerate()
            audio = wav.readframes(wav.getnframes())
        if width != 2 or channels != 1:
            raise HomeAssistantError("C300X Wyoming audio must be mono 16-bit WAV")
        return {"rate": rate, "width": width, "channels": channels, "audio": audio}

    if hasattr(hass, "async_add_executor_job"):
        return cast(dict[str, Any], await hass.async_add_executor_job(_read))
    return await asyncio.to_thread(_read)


async def _async_wyoming_transcribe(
    host: str,
    port: int,
    wav: dict[str, Any],
    *,
    language: str | None,
) -> str:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=5,
        )
    except OSError as err:
        raise HomeAssistantError("C300X Wyoming Whisper connection failed") from err

    try:
        data: dict[str, Any] = {}
        if language:
            data["language"] = language
        await _async_write_wyoming_event(writer, "transcribe", data)
        await _async_write_wyoming_event(
            writer,
            "audio-start",
            {
                "rate": wav["rate"],
                "width": wav["width"],
                "channels": wav["channels"],
            },
        )
        audio = wav["audio"]
        for offset in range(0, len(audio), _WYOMING_CHUNK_BYTES):
            await _async_write_wyoming_event(
                writer,
                "audio-chunk",
                {
                    "rate": wav["rate"],
                    "width": wav["width"],
                    "channels": wav["channels"],
                },
                payload=audio[offset : offset + _WYOMING_CHUNK_BYTES],
            )
        await _async_write_wyoming_event(writer, "audio-stop")

        while True:
            event = await asyncio.wait_for(
                _async_read_wyoming_event(reader),
                timeout=_WYOMING_TIMEOUT_SECONDS,
            )
            if event.get("type") == "transcript":
                text = str((event.get("data") or {}).get("text") or "").strip()
                if text:
                    return text
                raise HomeAssistantError("C300X Wyoming Whisper returned empty transcript")
    except TimeoutError as err:
        raise HomeAssistantError("C300X Wyoming Whisper transcription timed out") from err
    finally:
        writer.close()
        await writer.wait_closed()


async def _async_write_wyoming_event(
    writer: asyncio.StreamWriter,
    event_type: str,
    data: dict[str, Any] | None = None,
    *,
    payload: bytes | None = None,
) -> None:
    header: dict[str, Any] = {"type": event_type}
    if data:
        header["data"] = data
    if payload:
        header["payload_length"] = len(payload)
    writer.write(json.dumps(header, separators=(",", ":")).encode("utf-8") + b"\n")
    if payload:
        writer.write(payload)
    await writer.drain()


async def _async_read_wyoming_event(reader: asyncio.StreamReader) -> dict[str, Any]:
    line = await reader.readline()
    if not line:
        raise HomeAssistantError("C300X Wyoming Whisper connection closed")
    event = json.loads(line.decode("utf-8"))
    data_length = int(event.get("data_length") or 0)
    if data_length:
        data = json.loads((await reader.readexactly(data_length)).decode("utf-8"))
        event["data"] = {**event.get("data", {}), **data}
    payload_length = int(event.get("payload_length") or 0)
    if payload_length:
        await reader.readexactly(payload_length)
    return cast(dict[str, Any], event)


def _normalize_wyoming_result(
    transcript: str,
    *,
    wav_path: str,
    capture_path: Path | None = None,
    capture_payload: dict[str, Any] | None = None,
    expected_phrase: str | None,
) -> dict[str, Any]:
    expected = expected_phrase.strip().casefold() if expected_phrase else ""
    phrase_match = bool(expected and transcript.strip().casefold() == expected)
    result: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "provider": "wyoming_whisper",
        "wav_path": wav_path,
        "transcript": transcript.strip(),
        "phrase_match": phrase_match,
        "confidence": None,
        "notes": "Local Wyoming Whisper transcription. Image analysis is not evaluated.",
        "expected_phrase": expected_phrase or "",
    }
    if capture_payload:
        result.update(
            {
                "capture_id": str(capture_payload.get("capture_id") or ""),
                "capture_path": str(capture_path or capture_payload.get("metadata_path") or ""),
                "capture_created_at": str(capture_payload.get("created_at") or ""),
                "capture_output_path": str(capture_payload.get("output_path") or ""),
            }
        )
    return result
