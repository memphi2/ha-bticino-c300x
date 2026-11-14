"""Unload and replacement must drain the previous snapshot manager's workers."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from test_stream_snapshots import manager_for

from custom_components.bticino_c300x import runtime_manager, snapshots
from custom_components.bticino_c300x.const import DOMAIN


async def blocked_manager(tmp_path, monkeypatch):
    manager = manager_for(tmp_path, monkeypatch)
    manager.hass.data.setdefault(DOMAIN, {})["stream_snapshots"] = {"one": manager}
    started, finish = asyncio.Event(), asyncio.Event()

    async def execute(function, *args):
        started.set()
        await finish.wait()
        return function(*args)

    manager.hass.async_add_executor_job = execute
    work = asyncio.create_task(manager.disk_job(lambda: "completed"))
    await started.wait()
    return manager, work, finish


def test_replacement_waits_for_closed_manager_executor(tmp_path, monkeypatch):
    async def run():
        old, work, finish = await blocked_manager(tmp_path, monkeypatch)
        old.close()
        replacement = manager_for(tmp_path, monkeypatch)
        replacement.hass = old.hass
        constructed = []

        class Factory:
            def __new__(cls, *args):
                constructed.append(True)
                return replacement

        monkeypatch.setattr(snapshots, "StreamSnapshots", Factory)
        monkeypatch.setattr(snapshots, "async_track_time_interval", lambda *args: lambda: None)
        old.entry.async_on_unload = Mock()
        setup = asyncio.create_task(snapshots.async_setup_snapshots(old.hass, old.entry))
        await asyncio.sleep(0)
        assert constructed == []
        assert snapshots.get_snapshots(old.hass, "one") is old
        finish.set()
        assert await work == "completed"
        await setup
        assert constructed == [True]
        assert snapshots.get_snapshots(old.hass, "one") is replacement
        await snapshots.async_shutdown_snapshots(old.hass, "one")

    asyncio.run(run())


def test_cancelled_shutdown_does_not_release_manager_before_worker_finishes(tmp_path, monkeypatch):
    async def run():
        manager, work, finish = await blocked_manager(tmp_path, monkeypatch)
        shutdown = asyncio.create_task(snapshots.async_shutdown_snapshots(manager.hass, "one"))
        await asyncio.sleep(0)
        shutdown.cancel()
        await asyncio.sleep(0)
        assert not shutdown.done()
        assert snapshots.get_snapshots(manager.hass, "one") is manager
        assert manager.closed
        finish.set()
        await work
        with pytest.raises(asyncio.CancelledError):
            await shutdown
        assert snapshots.get_snapshots(manager.hass, "one") is None

    asyncio.run(run())


@pytest.mark.parametrize("rollback", [False, True])
def test_runtime_teardown_awaits_snapshot_shutdown(tmp_path, monkeypatch, rollback):
    async def run():
        manager, work, finish = await blocked_manager(tmp_path, monkeypatch)
        manager.entry.runtime_data = SimpleNamespace(loaded_platforms=())
        manager.hass.config_entries = SimpleNamespace(async_unload_platforms=AsyncMock(return_value=True))
        runtime = runtime_manager.C300XRuntimeManager(manager.hass, manager.entry)
        cleanup = Mock()
        if rollback:
            monkeypatch.setattr(runtime, "_required_config_present", lambda: True)
            monkeypatch.setattr(runtime, "_async_prepare_runtime", AsyncMock(side_effect=RuntimeError("setup failed")))
            monkeypatch.setattr(runtime, "_cleanup_interrupted_setup", cleanup)
            teardown = asyncio.create_task(runtime.async_prepare())
        else:
            monkeypatch.setattr(runtime_manager, "cleanup_entry_runtime_resources", cleanup)
            teardown = asyncio.create_task(runtime.async_unload())
        await asyncio.sleep(0)
        assert manager.closed
        assert not teardown.done()
        cleanup.assert_not_called()
        finish.set()
        await work
        if rollback:
            with pytest.raises(RuntimeError, match="setup failed"):
                await teardown
        else:
            assert await teardown is True
        cleanup.assert_called_once()
        assert snapshots.get_snapshots(manager.hass, "one") is None

    asyncio.run(run())


def test_failed_platform_unload_leaves_snapshot_manager_running(tmp_path, monkeypatch):
    async def run():
        manager = manager_for(tmp_path, monkeypatch)
        manager.hass.data.setdefault(DOMAIN, {})["stream_snapshots"] = {"one": manager}
        manager.entry.runtime_data = SimpleNamespace(loaded_platforms=())
        manager.hass.config_entries = SimpleNamespace(async_unload_platforms=AsyncMock(return_value=False))
        runtime = runtime_manager.C300XRuntimeManager(manager.hass, manager.entry)
        assert await runtime.async_unload() is False
        assert not manager.closed
        await snapshots.async_shutdown_snapshots(manager.hass, "one")

    asyncio.run(run())
