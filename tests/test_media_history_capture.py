"""Offline capture completion integration and history admission lifecycle."""

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from test_media_history import clip, fixture, listed
from test_on_demand_capture import _entry, _idle
from test_visitor_journal import event

from custom_components.bticino_c300x import ring_capture
from custom_components.bticino_c300x.use_cases.ring_capture import RingCaptureUseCase


@pytest.mark.parametrize("mode", ["ring", "on_demand"])
@pytest.mark.parametrize("result", ["complete", "custom", "failure", "cancel"])
def test_capture_service_publishes_only_successful_default_completions(tmp_path, monkeypatch, mode, result):
    async def run():
        manager, _, request, view = fixture(tmp_path, monkeypatch)
        status = _idle()
        if mode == "ring":
            status.update(window_available=True, video_owner="ring")
            status["bridge"].update(media_owner="ring", ring_call_active=True, ring_media_active=True)
        entry = _entry(status)
        entry.entry_id = "one"
        manager.entry = manager.journal.entry = entry
        manager.hass.bus.async_listen = lambda *args: lambda: None
        before = time.time()

        async def record(_url, target, **kwargs):
            target.write_bytes(b"completed capture")
            if result == "failure":
                raise ValueError("offline capture failure")
            if result == "cancel":
                raise asyncio.CancelledError()

        monkeypatch.setattr(ring_capture, "_async_wait_rtsp_ready", AsyncMock())
        monkeypatch.setattr(ring_capture, "_async_run_ffmpeg", record)
        monkeypatch.setattr(ring_capture, "_async_talkback_codec_is_pcmu", AsyncMock(side_effect=AssertionError("Unexpected audio")))
        call = RingCaptureUseCase(manager.hass, entry).capture(
            capture_mode=mode, include_audio=False,
            output_path=str(tmp_path / "media/c300x/custom.mp4") if result == "custom" else None,
        )
        if result in {"failure", "cancel"}:
            with pytest.raises(ValueError if result == "failure" else asyncio.CancelledError):
                await call
            assert await listed(view, request) == []
            return
        metadata = await call
        assert before <= metadata["captured_at"] <= time.time()
        stored = await manager.hass.async_add_executor_job(Path(metadata["metadata_path"]).read_text)
        assert json.loads(stored)["captured_at"] == metadata["captured_at"]
        items = await listed(view, request)
        assert len(items) == (1 if result == "complete" else 0)
        if items:
            assert items[0]["at"] == metadata["captured_at"]
            assert (await view.get(request, "one", items[0]["id"])).body == b"completed capture"
        assert manager.journal.items() == []

    asyncio.run(run())


@pytest.mark.parametrize("transition", ["close", "cancel", "new_ring"])
def test_capture_admission_holds_manager_lock_and_rechecks_lifecycle(tmp_path, monkeypatch, transition):
    async def run():
        manager, _, request, view = fixture(tmp_path, monkeypatch)
        started, finish = asyncio.Event(), asyncio.Event()
        original = manager.hass.async_add_executor_job

        async def delayed(function, *args):
            result = await original(function, *args)
            started.set()
            await finish.wait()
            return result

        manager.hass.async_add_executor_job = delayed
        task = asyncio.create_task(clip(manager))
        await started.wait()
        assert manager.lock.locked()
        with pytest.raises(web.HTTPTooManyRequests):
            await view.get(request, "one")
        if transition == "close":
            manager.close()
        elif transition == "cancel":
            task.cancel()
            await asyncio.sleep(0)
            assert manager.lock.locked() and not task.done()
        else:
            manager.journal.event(event())
        finish.set()
        if transition == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await task
        assert len(manager.journal.captures.records) == (1 if transition == "new_ring" else 0)
        assert not manager.lock.locked()
        if transition == "new_ring":
            assert manager.journal.items()[0]["clip"] is None

    asyncio.run(run())


def test_deleted_capture_metadata_cannot_be_served_after_read(tmp_path, monkeypatch):
    from custom_components.bticino_c300x.media_history import read_item

    async def run():
        manager, _, request, view = fixture(tmp_path, monkeypatch)
        await clip(manager)
        item = (await listed(view, request))[0]
        original = manager.hass.async_add_executor_job

        async def removed(function, *args):
            result = await original(function, *args)
            if function is read_item:
                manager.journal.captures.records.clear()
            return result

        manager.hass.async_add_executor_job = removed
        with pytest.raises(web.HTTPNotFound):
            await view.get(request, "one", item["id"])

    asyncio.run(run())
