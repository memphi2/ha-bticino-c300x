"""Resource ownership and diagnostic isolation without global HA stubs."""

import asyncio
from dataclasses import fields

import pytest

from custom_components.bticino_c300x.data import (
    C300XRuntimeDiagnostics,
    C300XRuntimeResources,
)


def test_runtime_resources_close_cancels_all_tasks_and_is_idempotent():
    async def run():
        calls = []
        blocker = asyncio.Event()
        task_names = [
            item.name
            for item in fields(C300XRuntimeResources)
            if item.name.endswith("_task")
        ]
        resources = C300XRuntimeResources(
            unregister_event_registration=lambda: calls.append("registration"),
            unregister_display_bridge_updates=lambda: calls.append("display"),
            unregister_event_webhook=lambda: calls.append("event-webhook"),
            unregister_webhook=lambda: calls.append("webhook"),
        )

        async def device_action():
            raise AssertionError("Disposal must not invoke device actions")

        resources.prepare_doorbell_video_stop = device_action
        resources.prepare_home_call_stop = device_action
        resources.on_runtime_registration_created = device_action
        tasks = []
        for name in task_names:
            task = asyncio.create_task(blocker.wait())
            setattr(resources, name, task)
            tasks.append(task)
        await asyncio.sleep(0)
        resources.close()
        resources.close()
        await asyncio.gather(*tasks, return_exceptions=True)
        assert all(task.cancelled() for task in tasks)
        assert calls == ["registration", "display", "event-webhook", "webhook"]
        assert all(getattr(resources, item.name) is None for item in fields(resources))

    asyncio.run(run())


def test_runtime_resources_close_continues_after_unsubscribe_failure():
    async def run():
        calls = []

        def fail():
            raise RuntimeError("synthetic unsubscribe error")

        task = asyncio.create_task(asyncio.Event().wait())
        resources = C300XRuntimeResources(
            unregister_event_registration=fail,
            unregister_webhook=lambda: calls.append("webhook"),
            startup_sync_task=task,
        )
        with pytest.raises(ExceptionGroup) as error:
            resources.close()
        resources.close()
        await asyncio.gather(task, return_exceptions=True)
        assert task.cancelled()
        assert calls == ["webhook"]
        assert len(error.value.exceptions) == 1
        assert isinstance(error.value.exceptions[0], RuntimeError)
        assert all(getattr(resources, item.name) is None for item in fields(resources))

    asyncio.run(run())


def test_runtime_diagnostics_are_not_shared_between_entries():
    first = C300XRuntimeDiagnostics()
    second = C300XRuntimeDiagnostics()
    first.agent_diagnostics = {"agent_write_count": 2}
    first.display_bridge_diagnostics.last_error = "synthetic"
    assert second.agent_diagnostics == {}
    assert second.display_bridge_diagnostics.last_error is None
    assert not any(item.name.endswith("_task") for item in fields(first))
