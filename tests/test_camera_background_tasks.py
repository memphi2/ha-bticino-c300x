"""Lifetime and coalescing guarantees for camera-owned work."""

import asyncio
import inspect
from types import SimpleNamespace

import pytest

from custom_components.bticino_c300x.camera_media.background_tasks import (
    CameraBackgroundTasks,
)


def test_close_cancels_and_awaits_work_and_rejects_late_callbacks():
    async def run():
        owner = CameraBackgroundTasks()
        started, cleaned = asyncio.Event(), asyncio.Event()
        hass = SimpleNamespace(async_create_task=asyncio.create_task)

        async def work():
            started.set()
            try:
                await asyncio.Future()
            finally:
                await asyncio.sleep(0)
                cleaned.set()

        owner.create(hass, work())
        await started.wait()
        tasks = tuple(owner._tasks)
        await owner.close()
        assert cleaned.is_set()
        assert all(task.cancelled() for task in tasks)
        late = work()
        owner.create(hass, late)
        assert inspect.getcoroutinestate(late) == inspect.CORO_CLOSED
        assert not owner._tasks
        await owner.close()

    asyncio.run(run())


def test_named_tasks_coalesce_only_until_the_previous_task_finishes():
    async def run():
        owner = CameraBackgroundTasks()
        hass = SimpleNamespace(async_create_task=asyncio.create_task)
        gate = asyncio.Event()
        first = gate.wait()
        owner.create(hass, first, key="watchdog")
        duplicate = gate.wait()
        owner.create(hass, duplicate, key="watchdog")
        assert inspect.getcoroutinestate(duplicate) == inspect.CORO_CLOSED
        assert len(owner._tasks) == 1
        gate.set()
        await asyncio.gather(*owner._tasks)
        assert not owner._tasks
        owner.create(hass, gate.wait(), key="watchdog")
        assert len(owner._tasks) == 1
        await owner.close()

    asyncio.run(run())


def test_failure_is_retrieved_logged_and_removed(caplog):
    async def run():
        owner = CameraBackgroundTasks()

        async def fail():
            raise ValueError("test failure")

        owner.create(SimpleNamespace(async_create_task=asyncio.create_task), fail())
        await asyncio.gather(*owner._tasks, return_exceptions=True)
        assert not owner._tasks
        await owner.close()

    asyncio.run(run())
    assert "Camera background task failed" in caplog.text


def test_creation_failure_closes_unscheduled_coroutine():
    async def work():
        pass

    def fail(_coro):
        raise RuntimeError("not running")

    coro = work()
    with pytest.raises(RuntimeError, match="not running"):
        CameraBackgroundTasks().create(SimpleNamespace(async_create_task=fail), coro)
    assert inspect.getcoroutinestate(coro) == inspect.CORO_CLOSED
