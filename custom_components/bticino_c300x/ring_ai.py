"""Local C300X ring-call speech analysis helpers."""

from __future__ import annotations

import asyncio
import contextlib
import json
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from homeassistant.exceptions import HomeAssistantError

from .ring_capture import _safe_c300x_path

DEFAULT_RING_WAV_GLOB = "/config/c300x/**/*.raw.wav"
DEFAULT_RING_AI_RESULT_PATH = "/config/c300x/analysis/result.json"
_DEFAULT_RING_WAV_PATTERN = "*.raw.wav"
_WYOMING_CHUNK_BYTES = 8192
_WYOMING_TIMEOUT_SECONDS = 60


async def async_run_wyoming_ring_analysis(
    hass: Any,
    *,
    wyoming_host: str,
    wyoming_port: int = 10300,
    wav_path: str | None = None,
    result_path: str | None = None,
    language: str | None = None,
    expected_phrase: str | None = None,
) -> Path:
    """Transcribe an existing ring-call raw WAV through Wyoming Whisper."""

    host = wyoming_host.strip()
    if not host:
        raise HomeAssistantError("C300X Wyoming Whisper host is required")
    wav_file = await _async_ring_wav_path(hass, wav_path)
    target = _result_path(hass, result_path)
    wav = await _async_read_wav(hass, wav_file)
    transcript = await _async_wyoming_transcribe(
        host,
        wyoming_port,
        wav,
        language=language,
    )
    await _async_write_json(
        hass,
        target,
        _normalize_wyoming_result(
            transcript,
            wav_path=str(wav_file),
            expected_phrase=expected_phrase,
        ),
    )
    return target


def _ring_wav_path(hass: Any, wav_path: str | None) -> Path:
    if not wav_path:
        return _latest_ring_wav_path(hass)
    source = _safe_c300x_path(hass, Path(wav_path).expanduser(), "ring analysis WAV")
    return _validate_ring_wav(source)


async def _async_ring_wav_path(hass: Any, wav_path: str | None) -> Path:
    if hasattr(hass, "async_add_executor_job"):
        return await hass.async_add_executor_job(_ring_wav_path, hass, wav_path)
    return await asyncio.to_thread(_ring_wav_path, hass, wav_path)


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
        for path in resolved_root.rglob(_DEFAULT_RING_WAV_PATTERN):
            with contextlib.suppress(OSError):
                if path.is_file():
                    candidates[str(path.resolve(strict=False))] = path
    return list(candidates.values())


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
        return await hass.async_add_executor_job(_read)
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
    return event


def _normalize_wyoming_result(
    transcript: str,
    *,
    wav_path: str,
    expected_phrase: str | None,
) -> dict[str, Any]:
    phrase_match = (
        bool(expected_phrase)
        and transcript.strip().casefold() == expected_phrase.strip().casefold()
    )
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "provider": "wyoming_whisper",
        "wav_path": wav_path,
        "transcript": transcript.strip(),
        "phrase_match": phrase_match,
        "confidence": None,
        "notes": "Local Wyoming Whisper transcription. Image analysis is not evaluated.",
        "expected_phrase": expected_phrase or "",
    }


async def _async_write_json(hass: Any, path: Path, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"

    def _write() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    if hasattr(hass, "async_add_executor_job"):
        await hass.async_add_executor_job(_write)
        return
    await asyncio.to_thread(_write)
