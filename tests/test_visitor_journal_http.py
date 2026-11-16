"""Visitor metadata and media share the existing camera read authorization."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import web
from test_stream_snapshot_http import Request, setup
from test_stream_snapshot_store import jpeg
from test_visitor_journal import event

from custom_components.bticino_c300x.visitor_journal import VisitorJournal
from custom_components.bticino_c300x.visitor_journal_http import C300XVisitorJournalView


def test_list_and_media_require_camera_permission_and_entry_owner(tmp_path, monkeypatch):
    async def run():
        manager, registered, _ = setup(tmp_path, monkeypatch)
        manager.hass.bus = SimpleNamespace(async_fire=Mock())
        journal = manager.journal = VisitorJournal(manager.hass, manager.entry)
        journal.store = SimpleNamespace(async_delay_save=Mock(), async_save=AsyncMock())
        journal.event(event())
        item = await manager.save(jpeg(), "one")
        await journal.attach_snapshot(journal.active, item.name, manager.image)
        key = journal.active
        request = Request(manager)
        view = C300XVisitorJournalView()
        assert view.requires_auth
        assert not hasattr(view, "post")
        response = await view.get(request, "one")
        payload = json.loads(response.text)
        assert payload["visits"][0]["image"] is True
        assert "source" not in payload["visits"][0]
        assert "snapshot" not in payload["visits"][0]
        assert response.headers["Cache-Control"] == "no-store"
        assert (await view.get(request, "one", key, "image")).body == manager.image
        for visit, kind in (("../etc", "image"), (key, "video"), (key, "other")):
            with pytest.raises(web.HTTPNotFound):
                await view.get(request, "one", visit, kind)
        request["hass_user"].permissions.check_entity.return_value = False
        for args in ((), (key, "image"), (key, "video")):
            with pytest.raises(web.HTTPForbidden):
                await view.get(request, "one", *args)
        with pytest.raises(web.HTTPNotFound):
            await view.get(request, "two")
        request["hass_user"].is_admin = True
        registered.disabled_by = "user"
        with pytest.raises(web.HTTPForbidden):
            await view.get(request, "one")
        registered.disabled_by = None
        journal.records[key]["at"] -= 366 * 86400
        with pytest.raises(web.HTTPNotFound):
            await view.get(request, "one", key, "image")

    asyncio.run(run())


def test_clip_is_read_only_bounded_and_reauthorized_after_io(tmp_path, monkeypatch):
    async def run():
        manager, _, _ = setup(tmp_path, monkeypatch)
        manager.hass.bus = SimpleNamespace(async_fire=Mock())
        journal = manager.journal = VisitorJournal(manager.hass, manager.entry)
        journal.store = SimpleNamespace(async_delay_save=Mock())
        journal.event(event())
        name = "doorbell_20261116_120000_" + "a" * 32 + ".mp4"
        path = tmp_path / "media" / "c300x" / name
        path.parent.mkdir(parents=True)
        path.write_bytes(b"existing MP4")
        await journal.attach_clip(journal.active, {"output_path": str(path), "entry_id": "one", "capture_mode": "ring"})
        request = Request(manager)
        request.headers = {}
        view = C300XVisitorJournalView()
        response = await view.get(request, "one", journal.active, "video")
        assert response.body == b"existing MP4"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        listed = json.loads((await view.get(request, "one")).text)["visits"][0]
        revision = listed["video_revision"]
        assert len(revision) == 64
        assert listed["image_revision"] is None
        assert name not in json.dumps(listed)
        assert "signature" not in listed
        assert json.loads((await view.get(request, "one")).text)["visits"][0]["video_revision"] == revision
        path.write_bytes(b"new completed MP4")
        await journal.attach_clip(journal.active, {"output_path": str(path), "entry_id": "one", "capture_mode": "ring"})
        assert json.loads((await view.get(request, "one")).text)["visits"][0]["video_revision"] != revision
        async with manager.lock:
            with pytest.raises(web.HTTPTooManyRequests):
                await view.get(request, "one", journal.active, "video")
        original = manager.hass.async_add_executor_job

        async def revoke(function, *args):
            result = await original(function, *args)
            request["hass_user"].permissions.check_entity.return_value = False
            return result

        manager.hass.async_add_executor_job = revoke
        with pytest.raises(web.HTTPForbidden):
            await view.get(request, "one", journal.active, "video")

    asyncio.run(run())
