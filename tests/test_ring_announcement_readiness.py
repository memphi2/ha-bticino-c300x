"""Announcement admission must not turn a never-started playback into success."""

from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_ring_capture import (
    _capture_fakes,
    _capture_workspaces,
    _talkback_failure_entry,
)
from test_ring_capture import (
    ring_capture_module as capture,
)
from test_ring_talkback import (
    _FakeAudioFrame,
    _FakeInputContainer,
    _FakeSocket,
    _install_fake_av,
)
from test_ring_talkback import (
    ring_talkback as talkback,
)


@pytest.mark.parametrize("announcement", [False, True])
def test_capture_shutdown_during_unadmitted_talkback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, announcement: bool,
) -> None:
    hass, entry, target = _talkback_failure_entry(tmp_path)
    source = target.parent / "announcement.wav"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fixture")
    checked = asyncio.Event()
    finished = asyncio.Event()
    original_wait_for = asyncio.wait_for

    async def status():
        checked.set()
        return {"answered": True, "audio_active": True, "talkback_ready": False}

    async def ffmpeg(_url, path, **kwargs):
        await checked.wait()
        path.write_bytes(b"clip")

    async def sender(*args, **kwargs):
        try:
            await talkback.async_keep_talkback_alive_when_ready(*args, **kwargs)
        finally:
            finished.set()

    async def forbidden_worker(*args, **kwargs):
        pytest.fail("Unadmitted playback must not start an audio worker")

    async def bounded_wait(awaitable, timeout):  # noqa: ASYNC109 - mirrors asyncio.wait_for
        return await original_wait_for(awaitable, 0.02 if timeout == 2.0 else timeout)

    _capture_fakes(monkeypatch, ffmpeg)
    monkeypatch.setattr(entry.runtime_data.api, "async_doorbell_call_status", status, raising=False)
    monkeypatch.setattr(capture, "_async_keep_talkback_alive_when_ready", sender)
    monkeypatch.setattr(talkback, "_async_run_talkback_worker", forbidden_worker)
    monkeypatch.setattr(asyncio, "wait_for", bounded_wait)

    async def run():
        pending = capture.async_capture_doorbell_ring_call(
            hass, entry, output_path=str(target), duration_seconds=1,
            announcement_path=str(source) if announcement else None,
        )
        if announcement:
            with pytest.raises(capture.HomeAssistantError, match="announcement"):
                await pending
            assert not target.exists()
            assert _capture_workspaces(tmp_path) == []
        else:
            result = await pending
            assert result["announcement_used"] is False
            assert target.read_bytes() == b"clip"
        assert finished.is_set()

    asyncio.run(run())


@pytest.fixture
def playback(monkeypatch: pytest.MonkeyPatch):
    _install_fake_av(monkeypatch, with_audio=True)
    monkeypatch.setattr(talkback, "_ANNOUNCEMENT_PREROLL_SECONDS", 0)
    stop = threading.Event()
    sock = _FakeSocket()
    monkeypatch.setattr(talkback, "_open_talkback_socket", lambda _: (sock, ("fake", 0)))
    return sock, stop


@pytest.mark.parametrize("stage", ["initial", "preroll", "empty", "non_audio", "resampler", "encoder"])
def test_source_without_sent_payload_fails(
    monkeypatch: pytest.MonkeyPatch, playback, stage: str,
) -> None:
    sock, stop = playback
    if stage == "initial":
        stop.set()
    elif stage == "preroll":
        monkeypatch.setattr(talkback, "_ANNOUNCEMENT_PREROLL_SECONDS", 1)
        send = sock.sendto

        def stop_after_preroll(data, target):
            send(data, target)
            stop.set()

        monkeypatch.setattr(sock, "sendto", stop_after_preroll)
    elif stage in {"empty", "non_audio"}:
        monkeypatch.setattr(
            _FakeInputContainer, "decode", lambda *_: [] if stage == "empty" else [object()],
        )
    elif stage == "resampler":
        monkeypatch.setattr(sys.modules["av.audio.resampler"].AudioResampler, "resample", lambda *_: [])
    else:
        class BufferedEncoder:
            def encode(self, frame):
                stop.set()
                return []

        monkeypatch.setattr(talkback, "_create_talkback_encoder", lambda *a, **k: BufferedEncoder())

    with pytest.raises(talkback.HomeAssistantError, match="announcement.*never started"):
        talkback._keep_talkback_alive_sync("fake", Path("source.wav"), stop, keep_alive=False)
    assert len(sock.sent) == (1 if stage == "preroll" else 0)
    assert sock.closed is (stage != "initial")


@pytest.mark.parametrize("samples", [80, 160, 1600])
def test_started_source_cooperatively_truncates_after_actual_payload(
    monkeypatch: pytest.MonkeyPatch, playback, samples: int,
) -> None:
    sock, stop = playback
    monkeypatch.setattr(_FakeInputContainer, "decode", lambda *_: [_FakeAudioFrame(samples=samples)])
    # Exercise sequence wrap as well as a partial FIFO tail and full frames.
    monkeypatch.setattr(talkback.random, "randrange", lambda *_: 65535)
    send = sock.sendto

    def stop_after_source(data, target):
        send(data, target)
        stop.set()

    monkeypatch.setattr(sock, "sendto", stop_after_source)
    talkback._keep_talkback_alive_sync("fake", Path("source.wav"), stop)
    assert len(sock.sent) == 1
    assert sock.closed


def test_admission_after_capture_stop_cannot_report_announcement_success(
    monkeypatch: pytest.MonkeyPatch, playback,
) -> None:
    sock, stop = playback

    async def status():
        stop.set()
        return {"answered": True, "audio_active": True, "talkback_ready": True}

    entry = SimpleNamespace(runtime_data=SimpleNamespace(
        api=SimpleNamespace(async_doorbell_call_status=status),
    ))
    with pytest.raises(talkback.HomeAssistantError, match="announcement.*never started"):
        asyncio.run(talkback.async_keep_talkback_alive_when_ready(
            entry, "fake", Path("source.wav"), stop,
        ))
    assert not sock.sent


def test_cancel_while_waiting_for_admission_keeps_cancellation(
    monkeypatch: pytest.MonkeyPatch, playback,
) -> None:
    sock, stop = playback

    async def run():
        checked = asyncio.Event()

        async def status():
            checked.set()
            await asyncio.Event().wait()

        entry = SimpleNamespace(runtime_data=SimpleNamespace(
            api=SimpleNamespace(async_doorbell_call_status=status),
        ))
        task = asyncio.create_task(talkback.async_keep_talkback_alive_when_ready(
            entry, "fake", Path("source.wav"), stop,
        ))
        await checked.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert not sock.sent


def test_capture_preserves_success_after_worker_sent_source_audio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, playback,
) -> None:
    sock, _stop = playback
    hass, entry, target = _talkback_failure_entry(tmp_path)
    source = target.parent / "announcement.wav"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fixture")
    monkeypatch.setattr(_FakeInputContainer, "decode", lambda *_: [_FakeAudioFrame(samples=16000)])

    async def status():
        return {"answered": True, "audio_active": True, "talkback_ready": True}

    async def run():
        loop = asyncio.get_running_loop()
        sent = asyncio.Event()
        send = sock.sendto

        def source_sent(data, destination):
            send(data, destination)
            loop.call_soon_threadsafe(sent.set)

        async def ffmpeg(_url, path, **kwargs):
            await asyncio.wait_for(sent.wait(), timeout=2)
            path.write_bytes(b"clip")

        monkeypatch.setattr(sock, "sendto", source_sent)
        _capture_fakes(monkeypatch, ffmpeg)
        monkeypatch.setattr(entry.runtime_data.api, "async_doorbell_call_status", status, raising=False)
        monkeypatch.setattr(capture, "_async_keep_talkback_alive_when_ready", talkback.async_keep_talkback_alive_when_ready)
        result = await capture.async_capture_doorbell_ring_call(
            hass, entry, output_path=str(target), duration_seconds=1,
            announcement_path=str(source),
        )
        assert result["announcement_used"] is True
        assert target.read_bytes() == b"clip"
        assert sock.sent
        assert sock.closed

    asyncio.run(run())
