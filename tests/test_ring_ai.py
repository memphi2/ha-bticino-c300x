from __future__ import annotations

# ruff: noqa: E402
import asyncio
import json
import os
import sys
import time
import types
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

homeassistant = sys.modules.setdefault(
    "homeassistant",
    types.ModuleType("homeassistant"),
)
homeassistant.__path__ = []
exceptions = sys.modules.setdefault(
    "homeassistant.exceptions",
    types.ModuleType("homeassistant.exceptions"),
)


class _HomeAssistantError(Exception):  # pragma: no cover - import-time stub only
    pass


exceptions.HomeAssistantError = getattr(
    exceptions,
    "HomeAssistantError",
    _HomeAssistantError,
)
homeassistant.exceptions = exceptions
sys.modules["homeassistant.exceptions"] = exceptions

from homeassistant.exceptions import HomeAssistantError

from custom_components.bticino_c300x import ring_ai as ring_ai_module
from custom_components.bticino_c300x.json_io import async_write_json_file
from custom_components.bticino_c300x.ring_ai import (
    DEFAULT_RING_AI_RESULT_PATH,
    DEFAULT_RING_CAPTURE_METADATA_GLOB,
    _async_read_wav,
    _async_read_wyoming_event,
    _async_ring_analysis_source,
    _async_ring_wav_path,
    _async_write_wyoming_event,
    _async_wyoming_transcribe,
    _latest_ring_capture_metadata_path,
    _normalize_wyoming_result,
    _read_capture_metadata,
    _result_path,
    _ring_analysis_source,
    _ring_capture_metadata_path,
    _ring_wav_path,
    _safe_mtime,
    async_run_wyoming_ring_analysis,
)


class _FakeConfig:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, *parts: str) -> str:
        return str(self.root.joinpath(*parts))


class _FakeHass:
    def __init__(self, root: Path) -> None:
        self.config = _FakeConfig(root)
        self.executor_jobs: list[str] = []

    async def async_add_executor_job(self, func, *args):
        self.executor_jobs.append(getattr(func, "__name__", str(func)))
        return func(*args)


class _FakeWyomingWriter:
    def __init__(self) -> None:
        self.data = bytearray()
        self.drained = False
        self.closed = False

    def write(self, data: bytes) -> None:
        self.data.extend(data)

    async def drain(self) -> None:
        self.drained = True

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        pass


def _write_wav(path: Path, *, channels: int = 1, width: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(16000)
        wav.writeframes(b"\x01\x00\x02\x00")


def test_ring_ai_default_uses_latest_raw_wav_directly_below_config(tmp_path: Path) -> None:
    nested = tmp_path / "c300x" / "analysis" / "newer_nested.raw.wav"
    older = tmp_path / "c300x" / "doorbell_older.raw.wav"
    newer = tmp_path / "c300x" / "latest.raw.wav"
    nested.parent.mkdir(parents=True)
    older.parent.mkdir(parents=True, exist_ok=True)
    nested.write_bytes(b"ignored")
    older.write_bytes(b"old")
    newer.write_bytes(b"new")
    old_time = time.time() - 60
    os.utime(older, (old_time, old_time))
    future_time = time.time() + 60
    os.utime(nested, (future_time, future_time))

    hass = SimpleNamespace(config=_FakeConfig(tmp_path))

    assert _ring_wav_path(hass, None) == newer


def test_ring_ai_default_result_path_uses_config_analysis_dir(tmp_path: Path) -> None:
    hass = SimpleNamespace(config=_FakeConfig(tmp_path))

    assert DEFAULT_RING_AI_RESULT_PATH == "/config/c300x/analysis/result.json"
    assert _result_path(hass, None) == Path("/config/c300x/analysis/result.json")


def test_ring_ai_prefers_latest_capture_metadata_by_default(tmp_path: Path) -> None:
    hass = SimpleNamespace(config=_FakeConfig(tmp_path))
    wav = tmp_path / "c300x" / "latest.raw.wav"
    capture = tmp_path / "c300x" / "latest.capture.json"
    _write_wav(wav)
    capture.write_text(
        json.dumps(
            {
                "capture_id": "capture-1",
                "created_at": "2026-06-14T12:00:00+00:00",
                "raw_wav_path": str(wav),
            }
        ),
        encoding="utf-8",
    )

    source = _ring_analysis_source(hass, capture_path=None, wav_path=None)

    assert DEFAULT_RING_CAPTURE_METADATA_GLOB == "/config/c300x/*.capture.json"
    assert source["wav_path"] == wav
    assert source["capture_path"] == capture
    assert source["capture_payload"]["capture_id"] == "capture-1"


def test_ring_ai_selects_newest_capture_metadata(tmp_path: Path) -> None:
    hass = SimpleNamespace(config=_FakeConfig(tmp_path))
    c300x = tmp_path / "c300x"
    older = c300x / "older.capture.json"
    newer = c300x / "newer.capture.json"
    wav = c300x / "latest.raw.wav"
    _write_wav(wav)
    older.write_text(
        json.dumps({"capture_id": "old", "raw_wav_path": str(wav)}),
        encoding="utf-8",
    )
    newer.write_text(
        json.dumps({"capture_id": "new", "raw_wav_path": str(wav)}),
        encoding="utf-8",
    )
    old_time = time.time() - 60
    os.utime(older, (old_time, old_time))

    assert _latest_ring_capture_metadata_path(hass) == newer
    assert _ring_capture_metadata_path(hass, str(newer)) == newer


def test_ring_ai_rejects_invalid_capture_metadata(tmp_path: Path) -> None:
    hass = SimpleNamespace(config=_FakeConfig(tmp_path))
    capture = tmp_path / "c300x" / "latest.capture.json"
    capture.parent.mkdir(parents=True)

    capture.write_text("{bad-json", encoding="utf-8")
    with pytest.raises(HomeAssistantError, match="invalid JSON"):
        _read_capture_metadata(capture)

    capture.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    with pytest.raises(HomeAssistantError, match="must be a JSON object"):
        _read_capture_metadata(capture)

    capture.write_text(json.dumps({"raw_wav_path": "/config/c300x/latest.raw.wav"}), encoding="utf-8")
    with pytest.raises(HomeAssistantError, match="has no capture_id"):
        _read_capture_metadata(capture)

    with pytest.raises(HomeAssistantError, match="capture JSON file"):
        _ring_capture_metadata_path(hass, str(capture.with_name("latest.json")))


def test_ring_ai_async_source_uses_executor_when_available(tmp_path: Path) -> None:
    hass = _FakeHass(tmp_path)
    wav = tmp_path / "c300x" / "latest.raw.wav"
    _write_wav(wav)

    source = asyncio.run(
        _async_ring_analysis_source(
            hass,
            capture_path=None,
            wav_path=str(wav),
        )
    )

    assert source == {"wav_path": wav}
    assert hass.executor_jobs == ["<lambda>"]


def test_ring_ai_rejects_wav_that_does_not_match_capture_metadata(tmp_path: Path) -> None:
    hass = SimpleNamespace(config=_FakeConfig(tmp_path))
    wav = tmp_path / "c300x" / "latest.raw.wav"
    other_wav = tmp_path / "c300x" / "other.raw.wav"
    capture = tmp_path / "c300x" / "latest.capture.json"
    _write_wav(wav)
    _write_wav(other_wav)
    capture.write_text(
        json.dumps({"capture_id": "capture-1", "raw_wav_path": str(wav)}),
        encoding="utf-8",
    )

    with pytest.raises(HomeAssistantError, match="does not match capture metadata"):
        _ring_analysis_source(
            hass,
            capture_path=str(capture),
            wav_path=str(other_wav),
        )


def test_ring_ai_rejects_missing_and_non_wav_inputs(tmp_path: Path) -> None:
    hass = SimpleNamespace(config=_FakeConfig(tmp_path))
    source = tmp_path / "c300x" / "analysis" / "latest.raw.wav"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"not-a-real-wav")

    assert _ring_wav_path(hass, str(source)) == source
    with pytest.raises(HomeAssistantError, match="must be a WAV file"):
        _ring_wav_path(hass, str(source.with_suffix(".raw")))
    with pytest.raises(HomeAssistantError, match="does not exist"):
        _ring_wav_path(hass, str(source.with_name("missing.raw.wav")))
    with pytest.raises(HomeAssistantError, match="found no WAV files"):
        _ring_wav_path(SimpleNamespace(config=_FakeConfig(tmp_path / "empty")), None)


def test_result_path_rejects_non_json_target(tmp_path: Path) -> None:
    hass = SimpleNamespace(config=_FakeConfig(tmp_path))

    with pytest.raises(HomeAssistantError, match="must be a JSON file"):
        _result_path(hass, str(tmp_path / "c300x" / "analysis" / "result.txt"))


def test_read_wav_accepts_mono_16_bit_audio(tmp_path: Path) -> None:
    hass = _FakeHass(tmp_path)
    source = tmp_path / "c300x" / "latest.raw.wav"
    _write_wav(source)

    payload = asyncio.run(_async_read_wav(hass, source))

    assert payload == {
        "rate": 16000,
        "width": 2,
        "channels": 1,
        "audio": b"\x01\x00\x02\x00",
    }
    assert hass.executor_jobs == ["_read"]


def test_async_ring_wav_path_and_read_wav_use_thread_fallback(tmp_path: Path) -> None:
    source = tmp_path / "c300x" / "latest.raw.wav"
    _write_wav(source)
    hass = SimpleNamespace(config=_FakeConfig(tmp_path))

    assert asyncio.run(_async_ring_wav_path(hass, str(source))) == source
    assert asyncio.run(_async_read_wav(hass, source))["audio"] == b"\x01\x00\x02\x00"


def test_read_wav_rejects_non_mono_16_bit_audio(tmp_path: Path) -> None:
    hass = _FakeHass(tmp_path)
    source = tmp_path / "c300x" / "latest.raw.wav"
    _write_wav(source, channels=2)

    with pytest.raises(HomeAssistantError, match="mono 16-bit WAV"):
        asyncio.run(_async_read_wav(hass, source))


def test_write_wyoming_event_serializes_header_and_payload() -> None:
    writer = _FakeWyomingWriter()

    asyncio.run(
        _async_write_wyoming_event(
            writer,
            "audio-chunk",
            {"rate": 16000},
            payload=b"abc",
        )
    )

    header, payload = bytes(writer.data).split(b"\n", 1)
    assert json.loads(header) == {
        "type": "audio-chunk",
        "data": {"rate": 16000},
        "payload_length": 3,
    }
    assert payload == b"abc"
    assert writer.drained is True


def test_read_wyoming_event_merges_data_and_discards_payload() -> None:
    data = json.dumps({"text": "Open"}).encode()

    async def _run() -> dict[str, object]:
        reader = asyncio.StreamReader()
        reader.feed_data(
            json.dumps(
                {
                    "type": "transcript",
                    "data": {"partial": False},
                    "data_length": len(data),
                    "payload_length": 3,
                },
                separators=(",", ":"),
            ).encode()
            + b"\n"
            + data
            + b"abc"
        )
        reader.feed_eof()
        return await _async_read_wyoming_event(reader)

    assert asyncio.run(_run()) == {
        "type": "transcript",
        "data": {"partial": False, "text": "Open"},
        "data_length": len(data),
        "payload_length": 3,
    }


def test_read_wyoming_event_rejects_closed_connection() -> None:
    async def _run() -> None:
        reader = asyncio.StreamReader()
        reader.feed_eof()
        await _async_read_wyoming_event(reader)

    with pytest.raises(HomeAssistantError, match="connection closed"):
        asyncio.run(_run())


def test_safe_mtime_returns_zero_for_unreadable_path(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_os_error(self: Path):  # noqa: ANN202
        raise OSError

    monkeypatch.setattr(Path, "stat", _raise_os_error)

    assert _safe_mtime(Path("/config/c300x/missing.raw.wav")) == 0.0


def test_normalize_wyoming_result_matches_expected_phrase() -> None:
    result = _normalize_wyoming_result(
        " Open the door ",
        wav_path="/config/c300x/latest.raw.wav",
        expected_phrase="open the door",
    )

    assert result["provider"] == "wyoming_whisper"
    assert result["transcript"] == "Open the door"
    assert result["phrase_match"] is True
    assert result["confidence"] is None


def test_run_wyoming_ring_analysis_writes_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    hass = _FakeHass(tmp_path)
    source = tmp_path / "c300x" / "latest.raw.wav"
    result = tmp_path / "c300x" / "analysis" / "result.json"
    _write_wav(source)
    transcribe_calls: list[tuple[str, int, str | None, dict[str, object]]] = []

    async def _transcribe(host, port, wav, *, language):  # noqa: ANN001
        transcribe_calls.append((host, port, language, wav))
        return "Open"

    monkeypatch.setattr(ring_ai_module, "_async_wyoming_transcribe", _transcribe)

    assert (
        asyncio.run(
            async_run_wyoming_ring_analysis(
                hass,
                wyoming_host=" whisper.local ",
                wyoming_port=10301,
                wav_path=str(source),
                result_path=str(result),
                language="de",
                expected_phrase="open",
            )
        )
        == result
    )

    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["transcript"] == "Open"
    assert payload["phrase_match"] is True
    assert transcribe_calls[0][:3] == ("whisper.local", 10301, "de")


def test_run_wyoming_ring_analysis_writes_capture_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    hass = _FakeHass(tmp_path)
    source = tmp_path / "c300x" / "latest.raw.wav"
    capture = tmp_path / "c300x" / "latest.capture.json"
    result = tmp_path / "c300x" / "analysis" / "result.json"
    _write_wav(source)
    capture.write_text(
        json.dumps(
            {
                "capture_id": "capture-1",
                "created_at": "2026-06-14T12:00:00+00:00",
                "metadata_path": str(capture),
                "output_path": "/media/c300x/doorbell.mp4",
                "raw_wav_path": str(source),
            }
        ),
        encoding="utf-8",
    )

    async def _transcribe(*_args: object, **_kwargs: object) -> str:
        return "Open"

    monkeypatch.setattr(ring_ai_module, "_async_wyoming_transcribe", _transcribe)

    asyncio.run(
        async_run_wyoming_ring_analysis(
            hass,
            wyoming_host="127.0.0.1",
            capture_path=str(capture),
            result_path=str(result),
            expected_phrase="open",
        )
    )

    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["capture_id"] == "capture-1"
    assert payload["capture_path"] == str(capture)
    assert payload["capture_output_path"] == "/media/c300x/doorbell.mp4"
    assert payload["wav_path"] == str(source)


def test_run_wyoming_ring_analysis_rejects_missing_host(tmp_path: Path) -> None:
    hass = SimpleNamespace(config=_FakeConfig(tmp_path))

    with pytest.raises(HomeAssistantError, match="host is required"):
        asyncio.run(async_run_wyoming_ring_analysis(hass, wyoming_host=" "))


def test_wyoming_transcribe_roundtrip_with_local_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> str:
        writer = _FakeWyomingWriter()

        async def _open_connection(host: str, port: int) -> tuple[asyncio.StreamReader, _FakeWyomingWriter]:
            assert host == "127.0.0.1"
            assert port == 10300
            reader = asyncio.StreamReader()
            reader.feed_data(b'{"type":"transcript","data":{"text":"Open"}}\n')
            return reader, writer

        monkeypatch.setattr(ring_ai_module.asyncio, "open_connection", _open_connection)

        transcript = await _async_wyoming_transcribe(
            "127.0.0.1",
            10300,
            {
                "rate": 16000,
                "width": 2,
                "channels": 1,
                "audio": b"a" * 9000,
            },
            language="de",
        )
        received: list[str] = []
        data = bytes(writer.data)
        while data:
            header, _separator, data = data.partition(b"\n")
            event = json.loads(header)
            received.append(event["type"])
            payload_length = int(event.get("payload_length") or 0)
            data = data[payload_length:]
        assert received == [
            "transcribe",
            "audio-start",
            "audio-chunk",
            "audio-chunk",
            "audio-stop",
        ]
        return transcript

    assert asyncio.run(_run()) == "Open"


def test_wyoming_transcribe_reports_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _open_connection(_host: str, _port: int):
        raise OSError

    monkeypatch.setattr(ring_ai_module.asyncio, "open_connection", _open_connection)

    with pytest.raises(HomeAssistantError, match="connection failed"):
        asyncio.run(
            _async_wyoming_transcribe(
                "127.0.0.1",
                10300,
                {"rate": 16000, "width": 2, "channels": 1, "audio": b""},
                language=None,
            )
        )


def test_wyoming_transcribe_rejects_empty_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _open_connection(
        _host: str,
        _port: int,
    ) -> tuple[asyncio.StreamReader, _FakeWyomingWriter]:
        reader = asyncio.StreamReader()
        reader.feed_data(b'{"type":"transcript","data":{"text":"  "}}\n')
        return reader, _FakeWyomingWriter()

    monkeypatch.setattr(ring_ai_module.asyncio, "open_connection", _open_connection)

    with pytest.raises(HomeAssistantError, match="empty transcript"):
        asyncio.run(
            _async_wyoming_transcribe(
                "127.0.0.1",
                10300,
                {"rate": 16000, "width": 2, "channels": 1, "audio": b""},
                language=None,
            )
        )


def test_write_json_uses_thread_fallback(tmp_path: Path) -> None:
    target = tmp_path / "c300x" / "analysis" / "result.json"

    asyncio.run(
        async_write_json_file(
            SimpleNamespace(config=_FakeConfig(tmp_path)),
            target,
            {"transcript": "Open"},
        )
    )

    assert json.loads(target.read_text(encoding="utf-8")) == {"transcript": "Open"}
