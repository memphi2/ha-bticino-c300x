"""Capture isolation, stable analysis input, and bounded HA-side work files."""

import asyncio
import json
import os
import shutil
import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlsplit

import pytest
from test_ring_capture import _FakeApi, _FakeEntry, _FakeHass, _FakeRuntimeData

from custom_components.bticino_c300x import capture_artifacts as artifacts
from custom_components.bticino_c300x import ring_ai, ring_capture


def test_short_video_extracts_real_frames_and_removes_absent_aliases(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg tools not installed")
    source = tmp_path / "short.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=red:s=64x64:r=10:d=1", "-c:v", "mpeg4", str(source)],
                   check=True, timeout=10)
    work = tmp_path / "new"
    work.mkdir()
    asyncio.run(ring_capture._async_extract_capture_frames(source, work, duration_seconds=5))
    assert all((work / f"frame_{index:02}.jpg").stat().st_size > 0 for index in (1, 2, 3))
    (tmp_path / "latest.raw.wav").write_bytes(b"old")
    artifacts.publish_capture_aliases(tmp_path, work)
    assert not (tmp_path / "latest.raw.wav").exists()
    assert (tmp_path / "frame_01.jpg").resolve() == work / "frame_01.jpg"


def test_h264_capture_extracts_jpeg_frames_with_native_ffmpeg(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg tools not installed")
    source = tmp_path / "limited.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
         "color=c=red:s=64x64:r=10:d=1", "-pix_fmt", "yuv420p",
         "-color_range", "tv", "-c:v", "libx264", str(source)],
        check=True, timeout=10,
    )
    work = tmp_path / "frames"
    work.mkdir()
    asyncio.run(ring_capture._async_extract_capture_frames(source, work, duration_seconds=1))
    assert all((work / f"frame_{index:02}.jpg").stat().st_size > 0 for index in (1, 2, 3))


def test_frame_extraction_explicitly_converts_each_jpeg_to_full_range(monkeypatch, tmp_path):
    commands = []

    async def run(command, **kwargs):
        if command[0] == "ffprobe":
            return b'{"streams":[{"duration":"3"}]}'
        commands.append(command)
        (tmp_path / command[-1]).write_bytes(b"test-output")
        return b""

    monkeypatch.setattr(ring_capture, "_async_run_ffmpeg_command", run)
    asyncio.run(ring_capture._async_extract_capture_frames(
        tmp_path / "clip.mp4", tmp_path, duration_seconds=3,
    ))
    assert len(commands) == 3
    for command in commands:
        assert command[command.index("-vf") + 1] == "scale=out_range=full"
        assert command.index("-vf") > command.index("-i")
        assert "-strict" not in command


def test_frame_extraction_rejects_success_without_output(monkeypatch, tmp_path):
    async def run(*args, **kwargs):
        return b'{"streams":[{"duration":"1"}]}'
    monkeypatch.setattr(ring_capture, "_async_run_ffmpeg_command", run)
    with pytest.raises(artifacts.HomeAssistantError, match="no image"):
        asyncio.run(ring_capture._async_extract_capture_frames(tmp_path / "clip.mp4", tmp_path, duration_seconds=5))


def test_two_devices_capture_and_analyse_independent_files(monkeypatch, tmp_path):
    async def run():
        hass = _FakeHass(tmp_path)
        arrived = asyncio.Event()
        outputs = []

        async def ffmpeg(url, target, *, work_dir, **kwargs):
            outputs.append(target)
            if len(outputs) == 2:
                arrived.set()
            await asyncio.wait_for(arrived.wait(), 1)
            target.write_bytes(b"mp4")
            with wave.open(str(work_dir / "latest.raw.wav"), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(urlsplit(url).hostname.encode().ljust(16, b" "))

        async def transcribe(host, port, wav, **kwargs):
            return wav["audio"].decode().strip()

        monkeypatch.setattr(ring_capture, "_async_run_ffmpeg", ffmpeg)
        monkeypatch.setattr(ring_capture, "_async_wait_rtsp_ready", AsyncMock())
        monkeypatch.setattr(ring_capture, "_async_keep_talkback_alive_when_ready", AsyncMock())
        monkeypatch.setattr(ring_ai, "_async_wyoming_transcribe", transcribe)
        entries = [_FakeEntry(
            _FakeRuntimeData(_FakeApi({"available": True})),
            {"agent_host": f"192.0.2.{i}"}, entry_id=f"entry-{i}",
        ) for i in (1, 2)]
        captures = await asyncio.gather(*(
            ring_capture.async_capture_doorbell_ring_call(hass, entry)
            for entry in entries
        ))
        for key in ("capture_id", "output_path", "metadata_path", "raw_wav_path"):
            assert captures[0][key] != captures[1][key]
        results = await asyncio.gather(*(
            ring_ai.async_run_wyoming_ring_analysis(
                hass, wyoming_host="synthetic", capture_path=item["metadata_path"],
            ) for item in captures
        ))
        assert results[0] != results[1]
        for i, (capture, result) in enumerate(zip(captures, results, strict=True), 1):
            payload = json.loads(result.read_text())
            assert capture["entry_id"] == f"entry-{i}"
            assert payload["capture_id"] == capture["capture_id"]
            assert payload["wav_path"] == capture["raw_wav_path"]
            assert payload["transcript"] == f"192.0.2.{i}"
        latest = ring_ai._ring_analysis_source(hass, capture_path=None, wav_path=None)
        assert str(latest["capture_path"]) in {item["metadata_path"] for item in captures}
        assert latest["capture_payload"]["raw_wav_path"] == str(latest["wav_path"])
        assert (tmp_path / "c300x" / "analysis" / "result.json").resolve() in results

    asyncio.run(run())


def test_explicit_output_rejects_overlap_and_releases_after_error(tmp_path):
    target = tmp_path / "clip.mp4"
    with pytest.raises(RuntimeError), artifacts.reserve_capture_output(target):
        with pytest.raises(artifacts.HomeAssistantError, match="already in use"), artifacts.reserve_capture_output(target):
            pytest.fail("overlapping output admitted")
        raise RuntimeError("cancelled capture")
    with artifacts.reserve_capture_output(target):
        pass


def test_workspaces_expire_without_deleting_unrelated_files(monkeypatch, tmp_path):
    monkeypatch.setattr(artifacts, "MAX_CAPTURE_WORKSPACES", 2)
    first = artifacts.prepare_capture_directory(tmp_path, "a" * 32)
    second = artifacts.prepare_capture_directory(tmp_path, "b" * 32)
    untouched = first.parent / "user-files"
    untouched.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (first.parent / ("c" * 32)).symlink_to(outside, target_is_directory=True)
    with pytest.raises(artifacts.HomeAssistantError, match="limit"):
        artifacts.prepare_capture_directory(tmp_path, "d" * 32)
    os.utime(first, (0, 0))
    third = artifacts.prepare_capture_directory(tmp_path, "d" * 32)
    assert not first.exists()
    assert all(path.is_dir() for path in (second, third, untouched, outside))


def test_workspace_rejects_redirected_parent(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "captures").symlink_to(outside, target_is_directory=True)
    with pytest.raises(artifacts.HomeAssistantError, match="symlink"):
        artifacts.prepare_capture_directory(root, "a" * 32)
    assert not list(outside.iterdir())


def test_workspace_rejects_invalid_capture_id(tmp_path):
    with pytest.raises(ValueError):
        artifacts.prepare_capture_directory(tmp_path, "../escape")
    assert not list(tmp_path.iterdir())


def test_guarded_unlock_rejects_another_devices_capture(monkeypatch, tmp_path):
    from custom_components.bticino_c300x.use_cases import ring_analysis

    monkeypatch.setattr(ring_analysis, "async_evaluate_ring_analysis", AsyncMock(
        return_value=SimpleNamespace(matched=True, capture_id="run", capture_entry_id="other"),
    ))
    reserve = AsyncMock()
    unlock = AsyncMock()
    monkeypatch.setattr(ring_analysis, "async_mark_ring_capture_used", reserve)
    monkeypatch.setattr(ring_analysis.DeviceActionsUseCase, "unlock", unlock)
    with pytest.raises(ring_analysis.HomeAssistantError, match="another device"):
        asyncio.run(ring_analysis.RingAnalysisUseCase(_FakeHass(tmp_path)).evaluate(
            unlock_on_match=True, unlock_entry=SimpleNamespace(entry_id="selected"),
        ))
    reserve.assert_not_called()
    unlock.assert_not_called()


def test_explicit_result_pointer_does_not_overwrite_previous_recording(tmp_path):
    from custom_components.bticino_c300x.json_io import async_write_json_file

    hass = _FakeHass(tmp_path)
    old = tmp_path / "c300x" / "captures" / ("a" * 32) / "analysis" / "result.json"
    old.parent.mkdir(parents=True)
    old.write_text('{"capture_id":"old"}')
    alias = tmp_path / "c300x" / "analysis" / "result.json"
    artifacts.publish_alias(old, alias)
    target = ring_ai._result_path(hass, str(alias))
    asyncio.run(async_write_json_file(hass, target, {"capture_id": "new"}))
    assert json.loads(old.read_text()) == {"capture_id": "old"}
    assert json.loads(alias.read_text()) == {"capture_id": "new"}
    assert not alias.is_symlink()


def test_a_ring_capture_records_the_call_and_the_unit_that_rang(monkeypatch, tmp_path):
    # An unlock after the analysis opens this unit, while the agent keeps
    # this call: not the unit of a later ring.
    from custom_components.bticino_c300x._api_calls import normalize_calls
    from custom_components.bticino_c300x.call_registry import C300XCallRegistry

    async def ffmpeg(url, target, *, work_dir, **kwargs):
        target.write_bytes(b"mp4")
        with wave.open(str(work_dir / "latest.raw.wav"), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\0" * 32)

    monkeypatch.setattr(ring_capture, "_async_run_ffmpeg", ffmpeg)
    monkeypatch.setattr(ring_capture, "_async_wait_rtsp_ready", AsyncMock())
    monkeypatch.setattr(ring_capture, "_async_keep_talkback_alive_when_ready", AsyncMock())
    runtime = _FakeRuntimeData(_FakeApi({"available": True}))
    runtime.calls = C300XCallRegistry()
    runtime.calls.set_calls(normalize_calls({"current_call_id": "0badc0de-7", "calls": [
        {"call_id": "0badc0de-7", "kind": "ring", "state": "ringing", "unit": "21"},
    ]}))
    entry = _FakeEntry(runtime, {"agent_host": "192.0.2.1"}, entry_id="entry-1")
    capture = asyncio.run(ring_capture.async_capture_doorbell_ring_call(_FakeHass(tmp_path), entry))
    stored = json.loads(Path(capture["metadata_path"]).read_text(encoding="utf-8"))
    for payload in (capture, stored):
        assert (payload["call_id"], payload["unit_id"]) == ("0badc0de-7", "21")
