"""Journal image identity survives reloads and rejects replacement and races."""

import asyncio
import json
import os
import threading
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import web
from homeassistant.core import HomeAssistant
from PIL import Image
from test_stream_snapshot_http import Request, setup
from test_visitor_journal import event

from custom_components.bticino_c300x import snapshot_identity as identity
from custom_components.bticino_c300x.visitor_journal import VisitorJournal
from custom_components.bticino_c300x.visitor_journal_http import C300XVisitorJournalView


def frame(color):
    output = BytesIO()
    Image.new("RGB", (64, 48), color).save(output, format="JPEG")
    # Equal sizes let the rewrite test isolate the content digest check.
    return output.getvalue().ljust(1024, b"\0")


async def linked(tmp_path, monkeypatch):
    manager, registered, _ = setup(tmp_path, monkeypatch)
    manager.hass.bus = SimpleNamespace(async_fire=Mock())
    journal = manager.journal = VisitorJournal(manager.hass, manager.entry)
    journal.store = SimpleNamespace(async_load=AsyncMock(), async_delay_save=Mock())
    journal.event(event())
    item = await manager.save(frame("red"), "first-visit")
    await journal.attach_snapshot(journal.active, item.name, frame("red"))
    return manager, journal, item, registered


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("change", ["replace", "delete", "rewrite", "symlink", "fifo"])
def test_red_blue_replacement_and_missing_files_never_serve_another_image(
    tmp_path, monkeypatch, cached, change,
):
    async def run():
        manager, journal, item, _ = await linked(tmp_path, monkeypatch)
        if not cached:
            await manager.save(frame("red"), "second-image")
        path = manager.store.root / item.name
        before = path.stat()
        if change == "replace":
            replacement = path.with_name("replacement.jpg")
            replacement.write_bytes(frame("blue"))
            replacement.replace(path)
            assert path.stat().st_ino != before.st_ino
        elif change == "rewrite":
            path.write_bytes(frame("blue"))
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
            assert identity._signature(path.stat()) == identity._signature(before)
        else:
            path.unlink()
            if change == "symlink":
                outside = tmp_path / "outside.jpg"
                outside.write_bytes(frame("blue"))
                path.symlink_to(outside)
            elif change == "fifo":
                os.mkfifo(path)
        assert manager.image == frame("red")
        view = C300XVisitorJournalView()
        with pytest.raises(web.HTTPNotFound):
            await view.get(Request(manager), "one", journal.active, "image")
        manager.close()

    asyncio.run(run())


def test_valid_file_ignores_wrong_preview_cache_and_keeps_headers(tmp_path, monkeypatch):
    async def run():
        manager, journal, _, _ = await linked(tmp_path, monkeypatch)
        manager.image = frame("blue")
        await manager.async_set_enabled(False)
        response = await C300XVisitorJournalView().get(Request(manager), "one", journal.active, "image")
        assert response.body == frame("red")
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.content_type == "image/jpeg"
        manager.close()

    asyncio.run(run())


@pytest.mark.parametrize("change", ["replace", "delete"])
def test_association_cannot_bind_changed_file_to_acquired_frame(tmp_path, monkeypatch, change):
    async def run():
        manager, journal, item, _ = await linked(tmp_path, monkeypatch)
        journal.records[journal.active]["snapshot"] = None
        path = manager.store.root / item.name
        if change == "replace":
            path.write_bytes(frame("blue"))
        else:
            path.unlink()
        await journal.attach_snapshot(journal.active, item.name, frame("red"))
        assert journal.records[journal.active]["snapshot"] is None
        manager.close()

    asyncio.run(run())


@pytest.mark.parametrize("transition", ["ring", "close", "cancel"])
def test_association_rechecks_lifecycle_after_executor(tmp_path, monkeypatch, transition):
    async def run():
        manager, journal, item, _ = await linked(tmp_path, monkeypatch)
        key = journal.active
        journal.records[key]["snapshot"] = None
        started, finish = asyncio.Event(), asyncio.Event()
        original = manager.hass.async_add_executor_job

        async def delayed(function, *args):
            result = await original(function, *args)
            started.set()
            await finish.wait()
            return result

        manager.hass.async_add_executor_job = delayed
        task = asyncio.create_task(journal.attach_snapshot(key, item.name, frame("red")))
        await started.wait()
        if transition == "ring":
            journal.event(event(sequence=2))
        elif transition == "close":
            journal.close()
        else:
            task.cancel()
        finish.set()
        if transition == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await task
        assert all(record["snapshot"] is None for record in journal.items())
        manager.close()

    asyncio.run(run())


@pytest.mark.parametrize("race", ["before_open", "during_read", "unlink_during_read", "rewrite_during_read"])
def test_playback_checks_open_descriptor_and_path_identity(tmp_path, monkeypatch, race):
    async def run():
        manager, journal, item, _ = await linked(tmp_path, monkeypatch)
        path = manager.store.root / item.name

        def replace():
            if race == "unlink_during_read":
                path.unlink()
            else:
                replacement = path.with_name("replacement.jpg")
                replacement.write_bytes(frame("blue"))
                replacement.replace(path)

        if race == "before_open":
            original_open = identity.os.open

            def open_replaced(*args, **kwargs):
                replace()
                return original_open(*args, **kwargs)

            monkeypatch.setattr(identity.os, "open", open_replaced)
        else:
            original_fdopen = identity.os.fdopen

            class ReplacingReader:
                def __init__(self, *args, **kwargs):
                    self.source = original_fdopen(*args, **kwargs)

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    self.source.close()

                def fileno(self):
                    return self.source.fileno()

                def read(self, *args):
                    if race == "rewrite_during_read":
                        before = path.stat()
                        path.write_bytes(frame("blue"))
                        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
                        return self.source.read(*args)
                    content = self.source.read(*args)
                    replace()
                    return content

            monkeypatch.setattr(identity.os, "fdopen", ReplacingReader)
        with pytest.raises(web.HTTPNotFound):
            await C300XVisitorJournalView().get(Request(manager), "one", journal.active, "image")
        manager.close()

    asyncio.run(run())


@pytest.mark.parametrize("invalid", [
    None, "filename-only", {}, {"name": "../outside.jpg"},
    {"signature": [1, 2, True, 4]}, {"signature": [1, 2, 0, 4]},
    {"signature": [1, 2, identity.MAX_SNAPSHOT_BYTES + 1, 4]},
    {"signature": [1, 2, 100, -1]}, {"sha256": "invalid"},
])
def test_unverified_snapshot_descriptors_are_rejected(tmp_path, monkeypatch, invalid):
    async def run():
        manager, journal, _, _ = await linked(tmp_path, monkeypatch)
        raw = {**journal.items()[0]["snapshot"], **invalid} if isinstance(invalid, dict) else invalid
        if invalid == {}:
            raw.pop("sha256")
        assert identity.valid_snapshot(raw) is None
        monkeypatch.setattr(identity, "_read", Mock(side_effect=AssertionError("Unverified file access")))
        assert identity.read_snapshot(manager.hass, "one", raw, 14) is None
        manager.close()

    asyncio.run(run())


def test_identity_reader_preserves_entry_root_and_retention_boundaries(tmp_path, monkeypatch):
    async def run():
        manager, journal, item, _ = await linked(tmp_path, monkeypatch)
        bound = journal.items()[0]["snapshot"]
        assert identity.read_snapshot(manager.hass, "two", bound, 14) is None
        with monkeypatch.context() as timing:
            timing.setattr(identity.time, "time", lambda: item.captured_at + 14 * 86400)
            assert identity.read_snapshot(manager.hass, "one", bound, 14) is None
        manager.store.root.rename(manager.store.root.with_name("moved"))
        manager.store.root.symlink_to(manager.store.root.with_name("moved"), target_is_directory=True)
        with pytest.raises(ValueError, match="symlink"):
            identity.read_snapshot(manager.hass, "one", bound, 14)
        manager.close()

    asyncio.run(run())


def test_real_storage_preserves_identity_without_rebinding_legacy_records(tmp_path):
    async def run():
        hass = HomeAssistant(str(tmp_path))
        hass.config.media_dirs = {"local": str(tmp_path / "media")}
        entry = SimpleNamespace(entry_id="one", data={}, options={})
        journal = VisitorJournal(hass, entry)
        await journal.load()
        journal.event(event())
        store = identity.SnapshotStore(hass, "one")
        item = await hass.async_add_executor_job(store.save, frame("red"), "capture", 14)
        await journal.attach_snapshot(journal.active, item.name, frame("red"))
        original = journal.items()[0]["snapshot"]
        assert original is not None
        journal.event(event(sequence=2))
        journal.records[journal.active]["snapshot"] = item.name  # Pre-fix storage format.
        await journal.shutdown()
        path = store.root / item.name
        await hass.async_add_executor_job(path.write_bytes, frame("blue"))
        restored = VisitorJournal(hass, entry)
        await restored.load()
        assert restored.items()[0]["snapshot"] is None
        assert restored.items()[1]["snapshot"] == original
        assert await hass.async_add_executor_job(identity.read_snapshot, hass, "one", original, 14) is None
        await restored.shutdown()
        await hass.async_block_till_done()

    asyncio.run(run())


def test_legacy_link_restore_never_reads_current_file_or_exposes_revision(tmp_path, monkeypatch):
    async def run():
        manager, journal, item, _ = await linked(tmp_path, monkeypatch)
        key = journal.active
        journal.store.async_load.return_value = {"visits": [{**journal.records[key], "snapshot": item.name}]}
        (manager.store.root / item.name).write_bytes(frame("blue"))
        monkeypatch.setattr(identity, "_read", Mock(side_effect=AssertionError("Legacy link rebound")))
        await journal.load()
        view = C300XVisitorJournalView()
        listed = json.loads((await view.get(Request(manager), "one")).text)["visits"][0]
        assert listed["image"] is False
        assert listed["image_revision"] is None
        with pytest.raises(web.HTTPNotFound):
            await view.get(Request(manager), "one", key, "image")
        manager.close()

    asyncio.run(run())


@pytest.mark.parametrize("change", ["revoke", "disable", "close", "expire"])
def test_image_rechecks_access_and_lifecycle_after_io(tmp_path, monkeypatch, change):
    async def run():
        manager, journal, _, registered = await linked(tmp_path, monkeypatch)
        key = journal.active
        request = Request(manager)
        original = manager.hass.async_add_executor_job

        async def changed(function, *args):
            result = await original(function, *args)
            if change == "revoke":
                request["hass_user"].permissions.check_entity.return_value = False
            elif change == "disable":
                registered.disabled_by = "user"
            elif change == "close":
                manager.close()
            else:
                journal.records[key]["at"] -= 366 * 86400
            return result

        manager.hass.async_add_executor_job = changed
        expected = web.HTTPForbidden if change in {"revoke", "disable"} else web.HTTPNotFound
        with pytest.raises(expected):
            await C300XVisitorJournalView().get(request, "one", key, "image")
        manager.close()

    asyncio.run(run())


def test_image_cancellation_holds_disk_lock_until_read_finishes(tmp_path, monkeypatch):
    async def run():
        manager, journal, _, _ = await linked(tmp_path, monkeypatch)
        started, finish = asyncio.Event(), asyncio.Event()
        original = manager.hass.async_add_executor_job

        async def delayed(function, *args):
            started.set()
            await finish.wait()
            return await original(function, *args)

        manager.hass.async_add_executor_job = delayed
        view = C300XVisitorJournalView()
        task = asyncio.create_task(view.get(Request(manager), "one", journal.active, "image"))
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert manager.lock.locked() and not task.done()
        with pytest.raises(web.HTTPTooManyRequests):
            await view.get(Request(manager), "one", journal.active, "image")
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not manager.lock.locked()
        manager.close()

    asyncio.run(run())


def test_identity_work_uses_executor_and_revisions_are_opaque(tmp_path, monkeypatch):
    async def run():
        manager, journal, item, _ = await linked(tmp_path, monkeypatch)
        main_thread = threading.get_ident()
        threads = []

        async def execute(function, *args):
            def checked():
                threads.append(threading.get_ident())
                return function(*args)
            return await asyncio.to_thread(checked)

        manager.hass.async_add_executor_job = execute
        await journal.attach_snapshot(journal.active, item.name, frame("red"))
        view = C300XVisitorJournalView()
        assert (await view.get(Request(manager), "one", journal.active, "image")).body == frame("red")
        assert len(threads) == 2 and all(thread != main_thread for thread in threads)
        first = json.loads((await view.get(Request(manager), "one")).text)["visits"][0]
        second = json.loads((await view.get(Request(manager), "one")).text)["visits"][0]
        assert first["image_revision"] == second["image_revision"]
        assert len(first["image_revision"]) == 64
        assert first["video_revision"] is None
        assert first["image_revision"] != journal.items()[0]["snapshot"]["sha256"]
        assert item.name not in json.dumps(first)
        assert "signature" not in first
        other = await manager.save(frame("blue"), "another-image")
        await journal.attach_snapshot(journal.active, other.name, frame("blue"))
        third = json.loads((await view.get(Request(manager), "one")).text)["visits"][0]
        assert third["image_revision"] != first["image_revision"]
        manager.close()

    asyncio.run(run())
