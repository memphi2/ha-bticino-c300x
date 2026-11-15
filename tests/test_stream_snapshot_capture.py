"""Framebuffer acquisition is event-driven, bounded, and generation-guarded."""

import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from PIL import Image
from test_stream_snapshot_store import jpeg
from test_stream_snapshots import manager_for

from custom_components.bticino_c300x import snapshot_capture as capture
from custom_components.bticino_c300x.api_errors import (
    C300XAgentApiConnectionError,
    C300XAgentApiResponseError,
)
from custom_components.bticino_c300x.const import EVENT_AGENT_EVENT_RECEIVED


def bmp(size=(512, 307)):
    output = BytesIO()
    Image.new("RGB", size, "red").save(output, format="BMP")
    return output.getvalue()


def setup(tmp_path, monkeypatch, delay=0):
    manager = manager_for(tmp_path, monkeypatch)
    manager.entry.data["video_enabled"] = True
    manager.entry.runtime_data = SimpleNamespace(api=SimpleNamespace(
        async_doorbell_snapshot=AsyncMock(return_value=(bmp(), "image/bmp")),
    ), capabilities={"doorbell_video": {"supported": True}})
    manager.hass.bus = SimpleNamespace(async_listen=Mock(return_value=Mock()))
    monkeypatch.setattr(capture, "snapshot_options", lambda _: SimpleNamespace(delay_seconds=delay))
    monkeypatch.setattr(capture, "RETRY_DELAY", 0)
    manager.capture.start()
    manager.hass.bus.async_listen.assert_called_once_with(EVENT_AGENT_EVENT_RECEIVED, manager.capture._event)
    return manager


def event(manager, key, stamp="one", entry="one"):
    manager.capture._event(SimpleNamespace(data={"entry_id": entry, "type": key, "event_at": stamp}))


async def drain(manager):
    for _ in range(10):
        task = manager.capture.task
        if task is None:
            return
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)
    pytest.fail("capture did not settle")


def test_bmp_conversion_bounds_and_metadata():
    result = capture.framebuffer_jpeg(bmp(), "image/bmp")
    with Image.open(BytesIO(result)) as image:
        assert image.format == "JPEG"
        assert image.size == (512, 307)
        assert not image.getexif()


@pytest.mark.parametrize("video_enabled,supported", [(False, True), (True, False), (False, False)])
def test_disabled_video_or_missing_capability_cannot_capture(tmp_path, monkeypatch, video_enabled, supported):
    async def run():
        manager = setup(tmp_path, monkeypatch)
        manager.capture.close()
        manager.capture = capture.SnapshotCapture(manager)
        manager.entry.data["video_enabled"] = video_enabled
        manager.entry.runtime_data.capabilities = {"doorbell_video": {"supported": supported}}
        manager.hass.bus.async_listen.reset_mock()
        manager.capture.start()
        manager.hass.bus.async_listen.assert_not_called()
        event(manager, "doorbell_pressed")
        manager.capture_requested("stream")
        await drain(manager)
        manager.entry.runtime_data.api.async_doorbell_snapshot.assert_not_called()
        manager.close()

    asyncio.run(run())


def test_video_disabled_after_scheduling_blocks_acquisition(tmp_path, monkeypatch):
    async def run():
        manager = setup(tmp_path, monkeypatch)
        event(manager, "doorbell_pressed")
        manager.entry.options["video_enabled"] = False
        await drain(manager)
        manager.entry.runtime_data.api.async_doorbell_snapshot.assert_not_called()
        manager.close()

    asyncio.run(run())


@pytest.mark.parametrize("content,kind", [
    (b"", "image/bmp"), (b"invalid", "image/bmp"), (jpeg(), "image/bmp"),
    (bmp(), "image/jpeg"), (b"x" * (512 * 1024 + 1), "image/bmp"),
])
def test_invalid_framebuffers(content, kind):
    with pytest.raises(ValueError):
        capture.framebuffer_jpeg(content, kind)


def test_pixel_limit_before_decode():
    output = BytesIO()
    Image.new("1", (513, 512)).save(output, format="BMP")
    with pytest.raises(ValueError, match="dimensions"):
        capture.framebuffer_jpeg(output.getvalue(), "image/bmp")


def test_ring_then_stream_deduplicates_without_frontend(tmp_path, monkeypatch):
    async def run():
        manager = setup(tmp_path, monkeypatch)
        api = manager.entry.runtime_data.api.async_doorbell_snapshot
        event(manager, "doorbell.pressed", entry="other")
        assert manager.capture.task is None
        event(manager, "doorbell.pressed")
        event(manager, "doorbell_pressed")
        manager.capture_requested("physical-session")
        event(manager, "doorbell.view_requested")
        await drain(manager)
        assert manager.preview
        manager.capture_requested("physical-session")
        await drain(manager)
        api.assert_awaited_once()
        assert len(manager.store.items(14)) == 1
        manager.capture_ended("old-session")
        assert manager.capture.identity is not None
        manager.capture_ended("physical-session")
        assert manager.capture.identity is None
        manager.capture_requested("next-session")
        await drain(manager)
        assert api.await_count == 2
        manager.close()

    asyncio.run(run())


@pytest.mark.parametrize("close", ["stream", "ring", "unload", "off"])
def test_quick_close_and_disable_reenable_never_restart_old_capture(tmp_path, monkeypatch, close):
    async def run():
        manager = setup(tmp_path, monkeypatch, delay=10)
        event(manager, "doorbell_pressed")
        manager.capture_requested("stream")
        if close == "stream":
            manager.capture_ended("stream")
        elif close == "ring":
            event(manager, "doorbell.media.closed")
        elif close == "unload":
            manager.close()
            manager.hass.bus.async_listen.return_value.assert_called_once()
        else:
            await manager.async_set_enabled(False)
            await manager.async_set_enabled(True)
        await drain(manager)
        manager.entry.runtime_data.api.async_doorbell_snapshot.assert_not_called()
        assert manager.capture.pending is None
        assert manager.preview is None
        manager.close()

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["connection", 409, 503])
def test_retry_at_most_three_times_and_keep_preview_on_failure(tmp_path, monkeypatch, failure):
    async def run():
        manager = setup(tmp_path, monkeypatch)
        await manager.save(jpeg(), "previous")
        previous = manager.preview
        error = C300XAgentApiConnectionError("unreachable") if failure == "connection" else C300XAgentApiResponseError("not ready")
        if isinstance(failure, int):
            error.status = failure
        api = manager.entry.runtime_data.api.async_doorbell_snapshot
        api.side_effect = error
        event(manager, "doorbell_pressed")
        await drain(manager)
        assert api.await_count == 3
        assert manager.preview == previous
        manager.close()

    asyncio.run(run())


def test_retry_recovers_on_third_attempt(tmp_path, monkeypatch):
    async def run():
        manager = setup(tmp_path, monkeypatch)
        api = manager.entry.runtime_data.api.async_doorbell_snapshot
        api.side_effect = [C300XAgentApiConnectionError("409"), C300XAgentApiConnectionError("429"), (bmp(), "image/bmp")]
        event(manager, "doorbell_view_requested")
        await drain(manager)
        assert api.await_count == 3
        assert manager.preview
        manager.close()

    asyncio.run(run())


def test_nonretryable_and_timeout_preserve_preview(tmp_path, monkeypatch):
    async def run():
        manager = setup(tmp_path, monkeypatch)
        await manager.save(jpeg(), "previous")
        previous = manager.preview
        api = manager.entry.runtime_data.api.async_doorbell_snapshot
        api.side_effect = C300XAgentApiResponseError("bad payload")
        event(manager, "doorbell_pressed")
        await drain(manager)
        assert api.await_count == 1
        event(manager, "doorbell_media_closed")
        monkeypatch.setattr(capture, "CAPTURE_TIMEOUT", 0.01)

        async def hang():
            await asyncio.Event().wait()

        api.side_effect = hang
        event(manager, "doorbell_pressed", "next")
        await asyncio.wait_for(drain(manager), 1)
        assert api.await_count == 2
        assert manager.preview == previous
        manager.close()

    asyncio.run(run())


def test_close_during_conversion_and_new_ring_do_not_save_stale_frame(tmp_path, monkeypatch):
    async def run():
        manager = setup(tmp_path, monkeypatch)
        started, finish = asyncio.Event(), asyncio.Event()
        original = manager.hass.async_add_executor_job

        async def execute(function, *args):
            if function == capture.framebuffer_jpeg and not started.is_set():
                started.set()
                await finish.wait()
            return await original(function, *args)

        manager.hass.async_add_executor_job = execute
        event(manager, "doorbell_pressed")
        await started.wait()
        event(manager, "doorbell_media_closed")
        event(manager, "doorbell_pressed", "new-ring")
        finish.set()
        await drain(manager)
        assert len(manager.store.items(14)) == 1
        assert manager.entry.runtime_data.api.async_doorbell_snapshot.await_count == 2
        manager.close()

    asyncio.run(run())


def test_generation_checked_when_executor_save_actually_runs(tmp_path, monkeypatch):
    async def run():
        manager = setup(tmp_path, monkeypatch)
        original = manager.hass.async_add_executor_job
        current = True

        async def execute(function, *args):
            nonlocal current
            current = False
            return await original(function, *args)

        manager.hass.async_add_executor_job = execute
        with pytest.raises(ValueError, match="no longer current"):
            await manager.save(jpeg(), "stale", is_current=lambda: current)
        assert not manager.store.root.exists()
        manager.close()

    asyncio.run(run())


def test_generation_invalidated_during_write_rolls_back_only_new_image(tmp_path, monkeypatch):
    async def run():
        manager = setup(tmp_path, monkeypatch)
        previous = await manager.save(jpeg(), "previous")
        preview = manager.preview
        original = manager.store.save
        current = True

        def save(*args):
            nonlocal current
            item = original(*args)
            current = False
            return item

        monkeypatch.setattr(manager.store, "save", save)
        with pytest.raises(ValueError, match="stale during storage"):
            await manager.save(jpeg(), "new-stale", is_current=lambda: current)
        assert manager.store.items(14) == [previous]
        assert manager.preview == preview
        current = True
        with pytest.raises(ValueError, match="stale during storage"):
            await manager.save(jpeg(), "previous", is_current=lambda: current)
        assert manager.store.items(14) == [previous]
        manager.close()

    asyncio.run(run())
