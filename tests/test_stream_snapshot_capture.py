"""Framebuffer acquisition is event-driven, bounded, and generation-guarded."""

import asyncio
import contextlib
import time
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


def bmp(size=(688, 480)):
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
    monkeypatch.setattr(capture, "snapshot_options", lambda _: SimpleNamespace(
        delay_seconds=delay, size=(688, 480), timestamp=False,
    ))
    monkeypatch.setattr(capture, "RETRY_DELAY", 0)
    manager.capture.start()
    manager.hass.bus.async_listen.assert_called_once_with(EVENT_AGENT_EVENT_RECEIVED, manager.capture._event)
    return manager


def event(manager, key, stamp="one", entry="one"):
    manager.capture._event(SimpleNamespace(data={"entry_id": entry, "event_type": key, "event_at": stamp}))


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
        # The agent delivered the configured size; it is not rescaled here.
        assert image.size == (688, 480)
        assert not image.getexif()


def test_capture_time_is_written_into_the_image_only_when_asked():
    plain = capture.framebuffer_jpeg(bmp(), "image/bmp")
    stamped = capture.framebuffer_jpeg(bmp(), "image/bmp", "2026-11-15 14:32:07")
    with Image.open(BytesIO(plain)) as image:
        corner = image.convert("RGB").crop((488, 440, 688, 480))
        assert len(set(corner.get_flattened_data())) < 8
    with Image.open(BytesIO(stamped)) as image:
        assert image.size == (688, 480)
        rgb = image.convert("RGB")
        # White text with a dark outline in the lower right corner only.
        corner = list(rgb.crop((488, 440, 688, 480)).get_flattened_data())
        assert any(min(pixel) > 200 for pixel in corner)
        assert any(max(pixel) < 60 for pixel in corner)
        assert len(set(rgb.crop((0, 0, 200, 40)).get_flattened_data())) < 8


def test_the_agent_is_asked_for_the_configured_size_and_the_stamp_follows_the_option(
    tmp_path, monkeypatch,
):
    async def run(timestamp):
        manager = setup(tmp_path / str(timestamp), monkeypatch)
        monkeypatch.setattr(capture, "snapshot_options", lambda _: SimpleNamespace(
            delay_seconds=0, size=(400, 288), timestamp=timestamp,
        ))
        seen = []
        real = capture.framebuffer_jpeg
        monkeypatch.setattr(
            capture, "framebuffer_jpeg",
            lambda content, kind, stamp=None: seen.append(stamp) or real(content, kind, stamp),
        )
        event(manager, "doorbell_pressed")
        await drain(manager)
        manager.entry.runtime_data.api.async_doorbell_snapshot.assert_awaited_once_with(400, 288)
        return seen

    assert asyncio.run(run(False)) == [None]
    stamps = asyncio.run(run(True))
    assert len(stamps) == 1 and len(stamps[0]) == 19


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
    Image.new("1", (801, 480)).save(output, format="BMP")
    with pytest.raises(ValueError, match="dimensions"):
        capture.framebuffer_jpeg(output.getvalue(), "image/bmp")


def test_ring_then_stream_deduplicates_without_frontend(tmp_path, monkeypatch):
    async def run():
        manager = setup(tmp_path, monkeypatch)
        api = manager.entry.runtime_data.api.async_doorbell_snapshot
        event(manager, "doorbell_pressed", entry="other")
        assert manager.capture.task is None
        event(manager, "doorbell_pressed")
        event(manager, "doorbell_pressed")
        manager.capture_requested("physical-session")
        event(manager, "doorbell_view_requested")
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
            event(manager, "doorbell_media_closed")
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


def test_a_failing_visitor_image_is_reported_once_per_cause(tmp_path, monkeypatch, caplog):
    """No firmware gate: a station whose screen cannot be read says so (firmware 3.0.6)."""

    async def run():
        manager = setup(tmp_path, monkeypatch)
        api = manager.entry.runtime_data.api.async_doorbell_snapshot
        api.side_effect = C300XAgentApiConnectionError("device agent returned HTTP 503: snapshot_unavailable")
        for stamp in ("one", "two"):
            event(manager, "doorbell_pressed", stamp)
            await drain(manager)
            event(manager, "doorbell_media_closed", stamp)
        assert manager.capture.last_failure == "snapshot_unavailable"
        warnings = [record for record in caplog.records if record.levelname == "WARNING"]
        assert len(warnings) == 1 and "snapshot_unavailable" in warnings[0].getMessage()
        api.side_effect = C300XAgentApiResponseError("bad payload")
        event(manager, "doorbell_pressed", "three")
        await drain(manager)
        assert manager.capture.last_failure == "agent_error"
        api.side_effect = None
        api.return_value = (bmp(), "image/bmp")
        event(manager, "doorbell_media_closed", "three")
        event(manager, "doorbell_pressed", "four")
        await drain(manager)
        assert manager.capture.last_failure is None and manager.preview
        manager.close()

    asyncio.run(run())


def test_a_visitor_image_that_cannot_be_stored_is_not_blamed_on_the_agent(tmp_path, monkeypatch, caplog):
    async def run():
        manager = setup(tmp_path, monkeypatch)
        api = manager.entry.runtime_data.api.async_doorbell_snapshot
        api.return_value = (bmp(), "image/bmp")
        changes = []
        original_notify = manager.notify
        manager.notify = lambda: (changes.append(manager.capture.last_failure), original_notify())

        async def full_disk(*args, **kwargs):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(manager, "save", full_disk)
        event(manager, "doorbell_pressed", "one")
        await drain(manager)
        assert manager.capture.last_failure == "save_failed"
        assert changes == ["save_failed"]
        warnings = [record for record in caplog.records if record.levelname == "WARNING"]
        assert len(warnings) == 1 and "save_failed" in warnings[0].getMessage()
        manager.close()

    asyncio.run(run())


def test_a_visitor_image_that_became_stale_while_storing_is_no_failure(tmp_path, monkeypatch):
    async def run():
        manager = setup(tmp_path, monkeypatch)
        api = manager.entry.runtime_data.api.async_doorbell_snapshot
        api.return_value = (bmp(), "image/bmp")

        async def stale(*args, **kwargs):
            manager.capture.generation += 1
            raise ValueError("Snapshot capture became stale during storage")

        monkeypatch.setattr(manager, "save", stale)
        event(manager, "doorbell_pressed", "one")
        await drain(manager)
        assert manager.capture.last_failure is None
        manager.close()

    asyncio.run(run())


def test_a_visitor_image_the_store_refuses_is_reported(tmp_path, monkeypatch, caplog):
    async def run():
        manager = setup(tmp_path, monkeypatch)
        api = manager.entry.runtime_data.api.async_doorbell_snapshot
        api.return_value = (bmp(), "image/bmp")

        async def refused(*args, **kwargs):
            raise ValueError("Snapshot directory must not be a symlink")

        monkeypatch.setattr(manager, "save", refused)
        event(manager, "doorbell_pressed", "one")
        await drain(manager)
        assert manager.capture.last_failure == "save_failed"
        warnings = [record for record in caplog.records if record.levelname == "WARNING"]
        assert len(warnings) == 1 and "save_failed" in warnings[0].getMessage()
        manager.close()

    asyncio.run(run())


def test_a_visitor_image_save_that_runs_out_of_time_is_not_blamed_on_the_agent(tmp_path, monkeypatch):
    from custom_components.bticino_c300x import snapshot_capture

    async def run():
        manager = setup(tmp_path, monkeypatch)
        api = manager.entry.runtime_data.api.async_doorbell_snapshot
        api.return_value = (bmp(), "image/bmp")
        monkeypatch.setattr(snapshot_capture, "CAPTURE_TIMEOUT", 0.2)

        async def slow(*args, **kwargs):
            await asyncio.sleep(5)

        monkeypatch.setattr(manager, "save", slow)
        event(manager, "doorbell_pressed", "one")
        await drain(manager)
        assert manager.capture.last_failure == "save_failed"
        manager.close()

    asyncio.run(run())


def swallowed_limit(calls):
    """Wait for the capture limit and turn its cancellation into a time-out,
    as an HTTP client does when its own timer expires in the same loop pass.
    The real asyncio.timeout is then expiring while the task runs on."""

    async def wait(*args, **kwargs):
        calls.append(args)
        if len(calls) > 1:
            return bmp(), "image/bmp"
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            raise TimeoutError from None

    return wait


def test_a_capture_limit_reported_as_a_request_time_out_ends_the_capture(tmp_path, monkeypatch, caplog):
    async def run():
        manager = setup(tmp_path, monkeypatch)
        calls = []
        manager.entry.runtime_data.api.async_doorbell_snapshot = swallowed_limit(calls)
        monkeypatch.setattr(capture, "CAPTURE_TIMEOUT", 0.05)
        event(manager, "doorbell_pressed", "one")
        task = manager.capture.task
        await drain(manager)
        # Over with the limit: no further attempt, a recorded cause, no crash.
        assert task.exception() is None and len(calls) == 1
        assert manager.capture.last_failure == "agent_unreachable"
        assert manager.latest is None and manager.store.items(30) == []
        assert "Unexpected snapshot acquisition failure" not in caplog.text
        manager.close()

    asyncio.run(run())


def test_a_capture_limit_that_already_fired_stops_the_store_before_it_writes(tmp_path, monkeypatch, caplog):
    async def run():
        manager = setup(tmp_path, monkeypatch)
        monkeypatch.setattr(capture, "CAPTURE_TIMEOUT", 0.05)
        disk_job = manager.disk_job
        waited = []
        wait = swallowed_limit(waited)

        async def conversion_outliving_the_limit(function, *args):
            if function is capture.framebuffer_jpeg:
                with contextlib.suppress(TimeoutError):
                    await wait()
            return await disk_job(function, *args)

        monkeypatch.setattr(manager, "disk_job", conversion_outliving_the_limit)
        event(manager, "doorbell_pressed", "one")
        task = manager.capture.task
        await drain(manager)
        assert len(waited) == 1 and task.exception() is None
        assert manager.capture.last_failure == "save_failed"
        assert manager.latest is None and manager.store.items(30) == []
        assert "Unexpected snapshot acquisition failure" not in caplog.text
        manager.close()

    asyncio.run(run())


def test_a_slow_visit_link_after_the_image_is_stored_is_no_failure(tmp_path, monkeypatch):
    from custom_components.bticino_c300x import snapshot_capture

    async def run():
        manager = setup(tmp_path, monkeypatch)
        api = manager.entry.runtime_data.api.async_doorbell_snapshot
        api.return_value = (bmp(), "image/bmp")
        monkeypatch.setattr(snapshot_capture, "CAPTURE_TIMEOUT", 0.3)
        journal = SimpleNamespace()

        attached = []

        async def slow_attach(*args, **kwargs):
            attached.append(args[1])
            await asyncio.sleep(5)

        journal.attach_snapshot = slow_attach
        journal.close = journal.invalidate = lambda: None
        manager.journal = journal
        event(manager, "doorbell_pressed", "one")
        await drain(manager)
        assert manager.latest is not None and attached == [manager.latest.name]
        assert manager.capture.last_failure is None
        manager.close()

    asyncio.run(run())


def _store_on_threads(manager, monkeypatch, step, seconds):
    """Run disk work on real threads and make one store step outlast the limit."""

    manager.hass.async_add_executor_job = (
        lambda function, *args: asyncio.get_running_loop().run_in_executor(None, function, *args)
    )
    original = getattr(manager.store, step)

    def slow(*args, **kwargs):
        time.sleep(seconds)
        return original(*args, **kwargs)

    monkeypatch.setattr(manager.store, step, slow)


def _recording_journal(manager):
    attached = []

    async def attach(visitor, name, image):
        attached.append(name)

    manager.journal = SimpleNamespace(
        attach_snapshot=attach, close=lambda: None, invalidate=lambda: None,
    )
    return attached


@pytest.mark.parametrize("step", ["read", "save"])
def test_an_image_the_store_wrote_after_the_time_limit_counts_as_stored(tmp_path, monkeypatch, step):
    """The limit ran out while the store wrote the file or HA read it back:
    the file is there, so it is the preview and no failure."""

    async def run():
        manager = setup(tmp_path, monkeypatch)
        monkeypatch.setattr(capture, "CAPTURE_TIMEOUT", 0.3)
        _store_on_threads(manager, monkeypatch, step, 0.8)
        attached = _recording_journal(manager)
        event(manager, "doorbell_pressed", "one")
        await drain(manager)
        stored = manager.store.items(14)
        assert len(stored) == 1
        assert manager.capture.last_failure is None
        assert manager.latest == stored[0] and manager.preview == manager.store.read("latest", 14)
        assert attached == [stored[0].name]
        manager.close()

    asyncio.run(run())


def test_waiting_for_the_store_beyond_the_time_limit_stores_nothing_and_is_reported(tmp_path, monkeypatch):
    async def run():
        manager = setup(tmp_path, monkeypatch)
        monkeypatch.setattr(capture, "CAPTURE_TIMEOUT", 0.3)
        attached = _recording_journal(manager)
        async with manager.lock:
            event(manager, "doorbell_pressed", "one")
            await drain(manager)
        assert manager.store.items(14) == [] and manager.latest is None
        assert manager.capture.last_failure == "save_failed"
        assert attached == []
        manager.close()

    asyncio.run(run())


def test_a_conversion_that_runs_out_of_time_is_not_blamed_on_the_agent(tmp_path, monkeypatch):
    from custom_components.bticino_c300x import snapshot_capture

    async def run():
        manager = setup(tmp_path, monkeypatch)
        api = manager.entry.runtime_data.api.async_doorbell_snapshot
        api.return_value = (bmp(), "image/bmp")
        monkeypatch.setattr(snapshot_capture, "CAPTURE_TIMEOUT", 0.2)
        original = manager.disk_job

        async def slow_job(function, *args):
            if function is snapshot_capture.framebuffer_jpeg:
                await asyncio.sleep(5)
            return await original(function, *args)

        monkeypatch.setattr(manager, "disk_job", slow_job)
        event(manager, "doorbell_pressed", "one")
        await drain(manager)
        assert manager.capture.last_failure == "save_failed"
        manager.close()

    asyncio.run(run())


def test_a_view_that_closes_during_a_ring_keeps_the_rings_image(tmp_path, monkeypatch):
    # doorbell.media.closed says whose media closed (kind, call_id): a live
    # view that ends while the visitor rings, or another ring's media, leaves
    # the ring's image; the ring's own close and an agent restart end it.
    def send(manager, key, stamp, call_id=None, media=None):
        manager.capture._event(SimpleNamespace(data={
            "entry_id": "one", "event_type": key, "event_at": stamp, "call_id": call_id,
            "data": {"kind": media} if media else {},
        }))

    async def run():
        manager = setup(tmp_path, monkeypatch)
        api = manager.entry.runtime_data.api.async_doorbell_snapshot
        send(manager, "doorbell_pressed", "ring", "0badc0de-2")
        send(manager, "doorbell_media_closed", "view", "0badc0de-3", "view")
        send(manager, "doorbell_media_closed", "view-unnamed", None, "view")
        send(manager, "doorbell_media_closed", "other-ring", "0badc0de-1", "ring")
        await drain(manager)
        api.assert_awaited_once()
        assert len(manager.store.items(14)) == 1
        assert manager.capture.identity is not None
        send(manager, "doorbell_media_closed", "ring-close", "0badc0de-2", "ring")
        assert manager.capture.identity is None
        # A ring whose call the agent did not name ends with its close, as before.
        send(manager, "doorbell_pressed", "ring-2")
        assert manager.capture.identity is not None
        send(manager, "doorbell_media_closed", "ring-2-close", "0badc0de-4", "ring")
        assert manager.capture.identity is None
        # An agent restart ends the ring; a view's own close ends the view's image.
        send(manager, "doorbell_pressed", "ring-3", "0badc0de-5")
        send(manager, "agent_restarted", "restart")
        assert manager.capture.identity is None
        send(manager, "doorbell_view_requested", "view-2", "0badc0de-6")
        assert manager.capture.identity is not None
        send(manager, "doorbell_media_closed", "view-2-close", "0badc0de-6", "view")
        assert manager.capture.identity is None
        await drain(manager)
        manager.close()

    asyncio.run(run())
