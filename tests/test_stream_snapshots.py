"""Per-entry snapshot cache and lifecycle without device access."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from test_stream_snapshot_store import fake_hass, jpeg

from custom_components.bticino_c300x import snapshots
from custom_components.bticino_c300x.config_snapshots import snapshot_options


def manager_for(tmp_path, monkeypatch, entry_id="one"):
    hass = fake_hass(tmp_path)

    async def execute(function, *args):
        return function(*args)

    hass.async_add_executor_job = execute
    entry = SimpleNamespace(entry_id=entry_id, data={}, options={})
    monkeypatch.setattr(snapshots, "async_dispatcher_send", lambda *args: None)
    monkeypatch.setattr(snapshots, "VisitorJournal", lambda *args: SimpleNamespace(
        load=AsyncMock(), start=lambda: None, close=lambda: None,
        shutdown=AsyncMock(), prune=lambda: None,
    ))
    manager = snapshots.StreamSnapshots(hass, entry)
    manager.settings = SimpleNamespace(async_load=AsyncMock(return_value=None), async_save=AsyncMock())
    return manager


def test_defaults_and_missing_runtime():
    options = snapshot_options(SimpleNamespace(data={}, options={}))
    assert (options.retention_days, options.delay_seconds) == (14, 3)
    # The image has the size the device encodes its video stream in, with the
    # capture time written into it.
    assert options.size == (688, 480)
    assert options.timestamp is True
    assert snapshots.get_snapshots(SimpleNamespace(), "one") is None


def test_real_ha_store_round_trip_is_entry_local(tmp_path, monkeypatch):
    async def run():
        hass = HomeAssistant(str(tmp_path))
        hass.config.media_dirs = {"local": str(tmp_path / "media")}
        monkeypatch.setattr(snapshots, "async_dispatcher_send", lambda *args: None)
        entry = SimpleNamespace(entry_id="one", data={}, options={})
        manager = snapshots.StreamSnapshots(hass, entry)
        await manager.async_load_settings()
        assert manager.enabled is True
        await manager.async_set_enabled(False)
        path = tmp_path / ".storage" / "bticino_c300x.snapshots.one"
        payload = await hass.async_add_executor_job(lambda: json.loads(path.read_text()))
        assert payload["data"] == {"enabled": False}
        restored = snapshots.StreamSnapshots(hass, entry)
        await restored.async_load_settings()
        assert restored.enabled is False
        other = snapshots.StreamSnapshots(hass, SimpleNamespace(entry_id="two", data={}, options={}))
        await other.async_load_settings()
        assert other.enabled is True
        await hass.async_block_till_done()

    asyncio.run(run())


def test_save_preview_disable_expire_and_reload(tmp_path, monkeypatch):
    async def run():
        manager = manager_for(tmp_path, monkeypatch)
        assert manager.enabled is True
        item = await manager.save(jpeg(), "session")
        assert manager.preview
        await manager.refresh()
        assert manager.latest == item
        await manager.async_set_enabled(False)
        assert manager.preview is None
        with pytest.raises(ValueError):
            await manager.save(jpeg(), "other")
        monkeypatch.setattr(snapshots.time, "time", lambda: item.captured_at + 15 * 86400)
        await manager.refresh()
        assert manager.latest is None
        assert list(manager.store.root.iterdir()) == []
        manager.close()
        assert manager.preview is None

    asyncio.run(run())


@pytest.mark.parametrize("stored,expected", [(None, True), ({"enabled": False}, False),
                                           ({"enabled": True}, True), ({"enabled": "false"}, False)])
def test_settings_load_and_ignore_config_enabled(tmp_path, monkeypatch, stored, expected):
    async def run():
        manager = manager_for(tmp_path, monkeypatch)
        manager.entry.options = {"stream_snapshots": not expected}
        manager.settings.async_load.return_value = stored
        await manager.async_load_settings()
        assert manager.enabled is expected
        manager.settings.async_save.assert_not_called()

    asyncio.run(run())


def test_switch_persists_and_reenables_cached_preview(tmp_path, monkeypatch):
    async def run():
        manager = manager_for(tmp_path, monkeypatch)
        await manager.save(jpeg(), "capture")
        image = manager.preview
        await manager.async_set_enabled(False)
        manager.settings.async_save.assert_awaited_once_with({"enabled": False})
        restored = manager_for(tmp_path, monkeypatch)
        restored.settings.async_load.return_value = manager.settings.async_save.call_args.args[0]
        await restored.async_load_settings()
        await restored.refresh()
        assert restored.enabled is False
        assert restored.preview is None
        assert restored.latest == manager.latest
        await restored.async_set_enabled(True)
        assert restored.preview == image
        restored.settings.async_save.assert_awaited_once_with({"enabled": True})

    asyncio.run(run())


def test_failed_persistence_leaves_state_unchanged(tmp_path, monkeypatch):
    async def run():
        manager = manager_for(tmp_path, monkeypatch)
        manager.settings.async_save.side_effect = OSError("disk full")
        with pytest.raises(OSError, match="disk full"):
            await manager.async_set_enabled(False)
        assert manager.enabled is True
        with pytest.raises(ValueError, match="boolean"):
            await manager.async_set_enabled(1)
        manager.close()
        with pytest.raises(ValueError, match="closed"):
            await manager.async_set_enabled(False)

    asyncio.run(run())


def test_concurrent_and_cancelled_switch_updates_are_serialized(tmp_path, monkeypatch):
    async def run():
        manager = manager_for(tmp_path, monkeypatch)
        started, finish = asyncio.Event(), asyncio.Event()
        writes = []

        async def persist(data):
            if not data["enabled"]:
                started.set()
                await finish.wait()
            writes.append(data)

        manager.settings.async_save.side_effect = persist
        first = asyncio.create_task(manager.async_set_enabled(False))
        await started.wait()
        first.cancel()
        second = asyncio.create_task(manager.async_set_enabled(True))
        await asyncio.sleep(0)
        assert manager.lock.locked()
        assert writes == []
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        await second
        assert writes == [{"enabled": False}, {"enabled": True}]
        assert manager.enabled is True

    asyncio.run(run())


def test_setup_loads_before_publishing_manager_and_timer(tmp_path, monkeypatch):
    async def run():
        manager = manager_for(tmp_path, monkeypatch)
        events = []

        async def load():
            assert snapshots.get_snapshots(manager.hass, "one") is None
            events.append("load")
            return {"enabled": False}

        def track(hass, callback, interval):
            assert snapshots.get_snapshots(hass, "one").enabled is False
            events.append("timer")
            return lambda: None

        callbacks = []
        manager.entry.async_on_unload = callbacks.append
        manager.settings.async_load.side_effect = load
        class ManagerFactory:
            def __new__(cls, *args):
                return manager

        monkeypatch.setattr(snapshots, "StreamSnapshots", ManagerFactory)
        monkeypatch.setattr(snapshots, "async_track_time_interval", track)
        await snapshots.async_setup_snapshots(manager.hass, manager.entry)
        assert events == ["load", "timer"]
        assert manager.enabled is False
        callbacks[0]()
        assert manager.closed
        await snapshots.async_shutdown_snapshots(manager.hass, "one")
        assert snapshots.get_snapshots(manager.hass, "one") is None

    asyncio.run(run())


def test_cancelled_disk_job_keeps_lock_until_completion(tmp_path, monkeypatch):
    async def run():
        manager = manager_for(tmp_path, monkeypatch)
        started, finish = asyncio.Event(), asyncio.Event()

        async def execute(function, *args):
            started.set()
            await finish.wait()
            return []

        manager.hass.async_add_executor_job = execute
        task = asyncio.create_task(manager.refresh())
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert manager.lock.locked()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not manager.lock.locked()

    asyncio.run(run())


def test_close_during_read_does_not_repopulate_cache(tmp_path, monkeypatch):
    async def run():
        manager = manager_for(tmp_path, monkeypatch)
        original = manager.hass.async_add_executor_job

        async def execute(function, *args):
            result = await original(function, *args)
            if function == manager.store.read:
                manager.close()
            return result

        manager.hass.async_add_executor_job = execute
        await manager.save(jpeg(), "session")
        assert manager.image is None
        assert manager.latest is None

    asyncio.run(run())


def test_unavailable_journal_does_not_break_existing_snapshots(tmp_path, monkeypatch):
    async def run():
        manager = manager_for(tmp_path, monkeypatch)
        failed = SimpleNamespace(load=AsyncMock(side_effect=OSError("unreadable")))
        monkeypatch.setattr(snapshots, "VisitorJournal", lambda *args: failed)

        class Factory:
            def __new__(cls, *args):
                return manager

        monkeypatch.setattr(snapshots, "StreamSnapshots", Factory)
        monkeypatch.setattr(snapshots, "async_track_time_interval", lambda *args: lambda: None)
        manager.entry.async_on_unload = lambda callback: None
        await snapshots.async_setup_snapshots(manager.hass, manager.entry)
        assert manager.journal is None
        await manager.save(jpeg(), "unaffected")
        assert manager.preview
        await snapshots.async_shutdown_snapshots(manager.hass, manager.entry.entry_id)

    asyncio.run(run())
