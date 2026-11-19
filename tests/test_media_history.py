"""Bounded mixed HA media history, immutable identities and camera authorization."""

import asyncio
import json
import os
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import web
from test_stream_snapshot_http import Request, setup
from test_stream_snapshot_store import jpeg
from test_visitor_journal import event

from custom_components.bticino_c300x import media_history as history
from custom_components.bticino_c300x import media_history_http as http
from custom_components.bticino_c300x import snapshot_http
from custom_components.bticino_c300x.capture_history import CaptureHistory
from custom_components.bticino_c300x.const import DOMAIN
from custom_components.bticino_c300x.snapshots import StreamSnapshots
from custom_components.bticino_c300x.visitor_journal import (
    EVENT_JOURNAL_CHANGED,
    VisitorJournal,
)


def fixture(tmp_path, monkeypatch):
    manager, registered, _ = setup(tmp_path, monkeypatch)
    manager.hass.bus = SimpleNamespace(async_fire=Mock())
    manager.journal = VisitorJournal(manager.hass, manager.entry)
    manager.journal.store = SimpleNamespace(
        async_load=AsyncMock(return_value=None), async_delay_save=Mock(), async_save=AsyncMock(),
    )
    request = Request(manager)
    request.headers = {}
    return manager, registered, request, http.C300XMediaHistoryView()


async def clip(manager, *, number=1, at=None, entry_id=None, mode="on_demand", key=None):
    path = manager.store.root.parent.parent / f"doorbell_20261116_120000_{number:032x}.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"completed video")
    await manager.journal.attach_clip(key, {
        "output_path": str(path), "entry_id": entry_id or manager.entry.entry_id,
        "capture_mode": mode, "captured_at": at or time.time() - 10,
    })
    return path


async def listed(view, request, entry="one"):
    return json.loads((await view.get(request, entry)).text)["items"]


def test_mixed_existing_snapshots_and_standalone_videos_are_stable_and_private(tmp_path, monkeypatch):
    async def run():
        manager, _, request, view = fixture(tmp_path, monkeypatch)
        # Existing HA images need no visit or new capture to appear.
        first = manager.store.save(jpeg(), "ring", 14)
        second = manager.store.save(jpeg(), "on-demand", 14)
        captured_at = time.time() - 30
        path = await clip(manager, at=captured_at)
        assert manager.journal.items() == []
        items = await listed(view, request)
        assert len(items) == 3
        assert items == await listed(view, request)
        assert [item["at"] for item in items] == sorted((first.captured_at, second.captured_at, captured_at), reverse=True)
        assert {item["kind"] for item in items} == {"image", "video"}
        for item in items:
            assert set(item) == {"id", "kind", "at", "expires_at", "revision"}
            assert len(item["id"]) == len(item["revision"]) == 64
            assert int(item["id"], 16) >= 0
            assert item["expires_at"] == item["at"] + 14 * 86400
            response = await view.get(request, "one", item["id"])
            assert response.body == (jpeg() if item["kind"] == "image" else path.read_bytes())
            assert response.headers["Cache-Control"] == "no-store"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert str(path) not in json.dumps(items) and first.name not in json.dumps(items)
        assert not hasattr(view, "post") and view.requires_auth
        video = next(item for item in items if item["kind"] == "video")
        request.http_range = slice(0, 4)
        response = await view.get(request, "one", video["id"])
        assert response.status == 206 and response.body == b"comp"
        assert video["at"] == captured_at != path.stat().st_mtime

    asyncio.run(run())


def test_two_live_entries_cannot_read_each_others_media(tmp_path, monkeypatch):
    async def run():
        manager, _, request, view = fixture(tmp_path, monkeypatch)
        await manager.save(jpeg(), "image")
        await clip(manager)
        other = StreamSnapshots(manager.hass, SimpleNamespace(entry_id="two", options={}, data={}))
        other.journal = VisitorJournal(manager.hass, other.entry)
        other.journal.store = SimpleNamespace(async_delay_save=Mock())
        manager.hass.data[DOMAIN]["stream_snapshots"]["two"] = other
        monkeypatch.setattr(snapshot_http, "runtime_entry", lambda hass, key: {"one": manager.entry, "two": other.entry}.get(key))
        await other.save(jpeg(), "image")
        await clip(other, number=2)
        one, two = await listed(view, request), await listed(view, request, "two")
        assert len(one) == len(two) == 2
        for entry_id, items in (("two", one), ("one", two)):
            for item in items:
                with pytest.raises(web.HTTPNotFound):
                    await view.get(request, entry_id, item["id"])
        await clip(manager, number=3, entry_id="two")
        assert len(await listed(view, request)) == 2
        # Unowned MP4s are never discovered even when their names look valid.
        assert len(list(manager.store.root.parent.parent.glob("*.mp4"))) == 3

    asyncio.run(run())


def test_image_switch_does_not_hide_videos_and_invalidates_subscription(tmp_path, monkeypatch):
    async def run():
        manager, _, request, view = fixture(tmp_path, monkeypatch)
        await manager.save(jpeg(), "image")
        await clip(manager)
        image = next(item for item in await listed(view, request) if item["kind"] == "image")
        manager.hass.bus.async_fire.reset_mock()
        await manager.async_set_enabled(False)
        manager.hass.bus.async_fire.assert_called_with(EVENT_JOURNAL_CHANGED, {"entry_id": "one"})
        assert [item["kind"] for item in await listed(view, request)] == ["video"]
        with pytest.raises(web.HTTPNotFound):
            await view.get(request, "one", image["id"])
        await manager.async_set_enabled(True)
        assert image in await listed(view, request)

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["image", "video"])
@pytest.mark.parametrize("change", ["replace", "rewrite", "delete", "symlink", "fifo"])
def test_changed_media_never_reuses_old_identity(tmp_path, monkeypatch, kind, change):
    async def run():
        manager, _, request, view = fixture(tmp_path, monkeypatch)
        if kind == "image":
            stored = await manager.save(jpeg(), "image")
            path = manager.store.root / stored.name
        else:
            path = await clip(manager)
        old = (await listed(view, request))[0]
        before = path.stat()
        content = path.read_bytes()
        if change == "rewrite":
            path.write_bytes(b"x" * len(content))
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        else:
            path.unlink()
            if change == "replace":
                path.write_bytes(content)
            elif change == "symlink":
                target = tmp_path / "outside"
                target.write_bytes(content)
                path.symlink_to(target)
            elif change == "fifo":
                os.mkfifo(path)
        with pytest.raises(web.HTTPNotFound):
            await view.get(request, "one", old["id"])
        assert old not in await listed(view, request)

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["image", "video"])
def test_exact_expiry_applies_to_list_and_bytes(tmp_path, monkeypatch, kind):
    async def run():
        manager, _, request, view = fixture(tmp_path, monkeypatch)
        manager.entry.options["snapshot_retention_days"] = 1
        if kind == "image":
            await manager.save(jpeg(), "image")
        else:
            await clip(manager)
        item = (await listed(view, request))[0]
        monkeypatch.setattr(time, "time", lambda: item["expires_at"])
        assert await listed(view, request) == []
        with pytest.raises(web.HTTPNotFound):
            await view.get(request, "one", item["id"])

    asyncio.run(run())


@pytest.mark.parametrize("endpoint", ["list", "bytes"])
@pytest.mark.parametrize("change", ["revoke", "disable_camera", "close", "replace_manager", "replace_runtime", "disable_images", "expire"])
def test_authorization_and_lifecycle_are_rechecked_after_io(tmp_path, monkeypatch, endpoint, change):
    async def run():
        manager, registered, request, view = fixture(tmp_path, monkeypatch)
        await manager.save(jpeg(), "image")
        item = (await listed(view, request))[0]
        original = manager.hass.async_add_executor_job

        async def changed(function, *args):
            result = await original(function, *args)
            if function is (history.inventory if endpoint == "list" else history.read_item):
                if change == "revoke":
                    request["hass_user"].permissions.check_entity.return_value = False
                elif change == "disable_camera":
                    registered.disabled_by = "user"
                elif change == "close":
                    manager.close()
                elif change == "replace_manager":
                    manager.hass.data[DOMAIN]["stream_snapshots"]["one"] = StreamSnapshots(manager.hass, manager.entry)
                elif change == "replace_runtime":
                    manager.entry.runtime_data = object()
                elif change == "disable_images":
                    manager.enabled = False
                else:
                    monkeypatch.setattr(time, "time", lambda: item["expires_at"])
            return result

        manager.hass.async_add_executor_job = changed
        key = None if endpoint == "list" else item["id"]
        if endpoint == "list" and change in {"disable_images", "expire"}:
            assert await listed(view, request) == []
        else:
            expected = web.HTTPForbidden if change in {"revoke", "disable_camera"} else web.HTTPNotFound
            with pytest.raises(expected):
                await view.get(request, "one", key)

    asyncio.run(run())


@pytest.mark.parametrize("endpoint", ["list", "bytes"])
def test_cancellation_keeps_lock_and_rejects_overload_until_executor_finishes(tmp_path, monkeypatch, endpoint):
    async def run():
        manager, _, request, view = fixture(tmp_path, monkeypatch)
        await manager.save(jpeg(), "image")
        item = (await listed(view, request))[0]
        started, finish = asyncio.Event(), asyncio.Event()
        original = manager.hass.async_add_executor_job

        async def delayed(function, *args):
            if function is (history.inventory if endpoint == "list" else history.read_item):
                started.set()
                await finish.wait()
            return await original(function, *args)

        manager.hass.async_add_executor_job = delayed
        task = asyncio.create_task(view.get(request, "one", None if endpoint == "list" else item["id"]))
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert manager.lock.locked() and not task.done()
        for key in (None, item["id"]):
            with pytest.raises(web.HTTPTooManyRequests) as err:
                await view.get(request, "one", key)
            assert err.value.headers["Retry-After"] == "2"
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not manager.lock.locked()

    asyncio.run(run())


def test_inventory_is_executor_only_and_never_reads_media_content(tmp_path, monkeypatch):
    async def run():
        manager, _, request, view = fixture(tmp_path, monkeypatch)
        await manager.save(jpeg(), "image")
        await clip(manager)
        main_thread = threading.get_ident()
        calls = []

        async def execute(function, *args):
            def checked():
                calls.append(threading.get_ident())
                return function(*args)
            return await asyncio.to_thread(checked)

        manager.hass.async_add_executor_job = execute
        monkeypatch.setattr(history, "_read", Mock(side_effect=AssertionError("Content read during list")))
        monkeypatch.setattr(history, "read_clip", Mock(side_effect=AssertionError("Content read during list")))
        for _ in range(3):
            assert len(await listed(view, request)) == 2
        assert len(calls) == 3 and all(thread != main_thread for thread in calls)

    asyncio.run(run())


def test_history_and_persisted_capture_ledger_are_bounded(tmp_path, monkeypatch):
    async def run():
        manager, _, request, view = fixture(tmp_path, monkeypatch)
        for number in range(1005):
            await clip(manager, number=number + 1, at=time.time() - 2000 + number)
        await manager.save(jpeg(), "newest")
        items = await listed(view, request)
        assert len(items) == 1000
        assert items[0]["kind"] == "image"
        assert len(manager.journal.captures.records) == 1000
        payload = manager.journal._payload()
        assert len(json.dumps(payload)) < 1024 * 1024
        restored = CaptureHistory()
        restored.load([None, {}, *payload["captures"]])
        assert restored.records == manager.journal.captures.records

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["ring", "on_demand"])
def test_completed_captures_survive_visit_end_and_storage_reload(tmp_path, monkeypatch, mode):
    async def run():
        manager, _, request, view = fixture(tmp_path, monkeypatch)
        journal = manager.journal
        journal.event(event())
        key = journal.active
        journal.event(event("doorbell_media_closed", 2))
        path = await clip(manager, key=key, mode=mode)
        # A ring clip still belongs to its visit; an on-demand capture has none.
        assert (journal.items()[0]["clip"] is None) == (mode == "on_demand")
        before = await listed(view, request)
        assert len(before) == 1
        payload = journal._payload()
        restored = VisitorJournal(manager.hass, manager.entry)
        restored.store = SimpleNamespace(async_load=AsyncMock(return_value=payload), async_delay_save=Mock())
        await restored.load()
        manager.journal = restored
        assert await listed(view, request) == before
        assert (await view.get(request, "one", before[0]["id"])).body == path.read_bytes()

    asyncio.run(run())


def test_access_denial_and_invalid_ids_do_not_submit_disk_work(tmp_path, monkeypatch):
    async def run():
        manager, registered, request, view = fixture(tmp_path, monkeypatch)
        manager.disk_job = AsyncMock(side_effect=AssertionError("Unauthorized disk work"))
        for key in ("../secret", "latest", "a" * 63, "A" * 64):
            with pytest.raises(web.HTTPNotFound):
                await view.get(request, "one", key)
        request["hass_user"].permissions.check_entity.return_value = False
        for key in (None, "a" * 64):
            with pytest.raises(web.HTTPForbidden):
                await view.get(request, "one", key)
        request["hass_user"].is_admin = True
        registered.disabled_by = "user"
        with pytest.raises(web.HTTPForbidden):
            await view.get(request, "one")
        manager.disk_job.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["image", "video"])
def test_symlinked_feature_roots_never_serve_history(tmp_path, monkeypatch, kind):
    async def run():
        manager, _, request, view = fixture(tmp_path, monkeypatch)
        if kind == "image":
            await manager.save(jpeg(), "image")
            root = manager.store.root
        else:
            root = (await clip(manager)).parent
        item = (await listed(view, request))[0]
        moved = root.with_name("moved")
        root.rename(moved)
        root.symlink_to(moved, target_is_directory=True)
        with pytest.raises(web.HTTPNotFound):
            await view.get(request, "one", item["id"])

    asyncio.run(run())


@pytest.mark.parametrize("change", ["replace", "delete", "rewrite", "symlink"])
def test_video_read_rechecks_descriptor_and_path_after_read(tmp_path, monkeypatch, change):
    from custom_components.bticino_c300x import visitor_journal_media as media

    async def run():
        manager, _, request, view = fixture(tmp_path, monkeypatch)
        path = await clip(manager)
        item = (await listed(view, request))[0]
        original = media.os.fdopen

        class ChangedReader:
            def __init__(self, *args, **kwargs):
                self.source = original(*args, **kwargs)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.source.close()

            def fileno(self):
                return self.source.fileno()

            def read(self, size):
                assert size == media.MAX_MEDIA_BYTES + 1
                content = self.source.read(size)
                info = path.stat()
                if change == "rewrite":
                    path.write_bytes(b"x" * len(content))
                    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
                elif change == "delete":
                    path.unlink()
                else:
                    target = path.with_name("outside.mp4")
                    target.write_bytes(content)
                    if change == "replace":
                        target.replace(path)
                    else:
                        path.unlink()
                        path.symlink_to(target)
                return content

        monkeypatch.setattr(media.os, "fdopen", ChangedReader)
        with pytest.raises(web.HTTPNotFound):
            await view.get(request, "one", item["id"])

    asyncio.run(run())
