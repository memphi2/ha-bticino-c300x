"""Read-only snapshot HTTP access enforces camera entity permissions."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import web
from test_stream_snapshot_store import jpeg
from test_stream_snapshots import manager_for

from custom_components.bticino_c300x import snapshot_http as http
from custom_components.bticino_c300x.const import DOMAIN


class Request(dict):
    def __init__(self, manager):
        super().__init__(hass_user=SimpleNamespace(
            is_admin=False, permissions=SimpleNamespace(check_entity=Mock(return_value=True)),
        ))
        self.app = {"hass": manager.hass}


def setup(tmp_path, monkeypatch):
    manager = manager_for(tmp_path, monkeypatch)
    manager.hass.data.setdefault(DOMAIN, {})["stream_snapshots"] = {"one": manager}
    manager.hass.states = SimpleNamespace(get=lambda _: None)
    monkeypatch.setattr(http, "runtime_entry", lambda hass, entry_id: manager.entry if entry_id == "one" else None)
    monkeypatch.setattr(http, "media_camera_unique_id", lambda *args: "unique")
    registered = SimpleNamespace(disabled_by=None)
    monkeypatch.setattr(http.er, "async_get", lambda _: SimpleNamespace(
        async_get_entity_id=lambda *args: "camera.door", async_get=lambda _: registered,
    ))
    return manager, registered, http.C300XSnapshotView()


def test_no_post_handler():
    # HA registers only implemented methods; POST therefore resolves to 405.
    assert not hasattr(http.C300XSnapshotView, "post")
    assert http.C300XSnapshotView.requires_auth


def test_authorization_policies_and_disabled_entity(tmp_path, monkeypatch):
    async def run():
        manager, registered, view = setup(tmp_path, monkeypatch)
        item = await manager.save(jpeg(), "capture")
        request = Request(manager)
        for image_id in ("latest", item.name):
            response = await view.get(request, "one", image_id)
            assert response.content_type == "image/jpeg"
            assert response.headers["Cache-Control"] == "no-store"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
        request["hass_user"].permissions.check_entity.assert_called_with("camera.door", http.POLICY_READ)
        request["hass_user"].permissions.check_entity.return_value = False
        with pytest.raises(web.HTTPForbidden):
            await view.get(request, "one", item.name)
        request["hass_user"].is_admin = True
        registered.disabled_by = "user"
        with pytest.raises(web.HTTPForbidden):
            await view.get(request, "one", "latest")
        with pytest.raises(web.HTTPNotFound):
            await view.get(request, "other", "latest")

    asyncio.run(run())


def test_disabled_preview_keeps_history_accessible(tmp_path, monkeypatch):
    async def run():
        manager, _, view = setup(tmp_path, monkeypatch)
        item = await manager.save(jpeg(), "capture")
        await manager.async_set_enabled(False)
        request = Request(manager)
        with pytest.raises(web.HTTPNotFound):
            await view.get(request, "one", "latest")
        assert (await view.get(request, "one", item.name)).status == 200
        with pytest.raises(web.HTTPNotFound):
            await view.get(request, "one", "../private.jpg")
        manager.close()
        with pytest.raises(web.HTTPNotFound):
            await view.get(request, "one", item.name)

    asyncio.run(run())


def test_history_contention_does_not_queue_disk_work(tmp_path, monkeypatch):
    async def run():
        manager, _, view = setup(tmp_path, monkeypatch)
        async with manager.lock:
            with pytest.raises(web.HTTPTooManyRequests):
                await view.get(Request(manager), "one", "image.jpg")

    asyncio.run(run())


@pytest.mark.parametrize("enabled", [True, False])
def test_concurrent_named_latest_reads_use_cache_while_disk_is_locked(tmp_path, monkeypatch, enabled):
    async def run():
        manager, _, view = setup(tmp_path, monkeypatch)
        item = await manager.save(jpeg(), "capture")
        image = manager.image
        await manager.async_set_enabled(enabled)
        disk_job = AsyncMock(side_effect=AssertionError("Cached reads must not touch disk"))
        monkeypatch.setattr(manager, "disk_job", disk_job)
        async with manager.lock:
            responses = await asyncio.wait_for(asyncio.gather(*(
                view.get(Request(manager), "one", item.name) for _ in range(10)
            )), timeout=1)
            for response in responses:
                assert response.status == 200
                assert response.body == image
                assert response.content_type == "image/jpeg"
                assert response.headers["Cache-Control"] == "no-store"
                assert response.headers["X-Content-Type-Options"] == "nosniff"
            if enabled:
                assert (await view.get(Request(manager), "one", "latest")).body == image
            else:
                with pytest.raises(web.HTTPNotFound):
                    await view.get(Request(manager), "one", "latest")
        disk_job.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("enabled", [True, False])
def test_named_cache_enforces_current_retention_at_exact_expiry(tmp_path, monkeypatch, enabled):
    async def run():
        manager, _, view = setup(tmp_path, monkeypatch)
        item = await manager.save(jpeg(), "capture")
        await manager.async_set_enabled(enabled)
        manager.entry.options["snapshot_retention_days"] = 1
        disk_job = AsyncMock(side_effect=AssertionError("Expired cache must not touch disk"))
        monkeypatch.setattr(manager, "disk_job", disk_job)
        monkeypatch.setattr(http.time, "time", lambda: item.captured_at + 86400 - 0.001)
        async with manager.lock:
            assert (await view.get(Request(manager), "one", item.name)).body == manager.image
            monkeypatch.setattr(http.time, "time", lambda: item.captured_at + 86400)
            for image_id in (item.name, "latest"):
                with pytest.raises(web.HTTPNotFound):
                    await view.get(Request(manager), "one", image_id)
        disk_job.assert_not_awaited()

    asyncio.run(run())


def test_named_cache_keeps_authorization_before_lock_free_response(tmp_path, monkeypatch):
    async def run():
        manager, registered, view = setup(tmp_path, monkeypatch)
        item = await manager.save(jpeg(), "capture")
        request = Request(manager)
        async with manager.lock:
            request["hass_user"].permissions.check_entity.return_value = False
            with pytest.raises(web.HTTPForbidden):
                await view.get(request, "one", item.name)
            request["hass_user"].is_admin = True
            registered.disabled_by = "user"
            with pytest.raises(web.HTTPForbidden):
                await view.get(request, "one", item.name)
            registered.disabled_by = None
            with pytest.raises(web.HTTPNotFound):
                await view.get(request, "other", item.name)
            manager.close()
            with pytest.raises(web.HTTPNotFound):
                await view.get(request, "one", item.name)

    asyncio.run(run())


def test_named_cache_does_not_substitute_for_other_images_or_missing_bytes(tmp_path, monkeypatch):
    async def run():
        manager, _, view = setup(tmp_path, monkeypatch)
        item = await manager.save(jpeg(), "capture")
        image = manager.image
        disk_job = AsyncMock(return_value=None)
        monkeypatch.setattr(manager, "disk_job", disk_job)
        with pytest.raises(web.HTTPNotFound):
            await view.get(Request(manager), "one", "different.jpg")
        disk_job.assert_awaited_once_with(manager.store.read, "different.jpg", 14)
        disk_job.reset_mock()
        manager.image = None
        disk_job.return_value = image
        assert (await view.get(Request(manager), "one", item.name)).body == image
        disk_job.assert_awaited_once_with(manager.store.read, item.name, 14)

    asyncio.run(run())
