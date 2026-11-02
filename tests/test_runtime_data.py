"""Resource ownership and diagnostic isolation without global HA stubs."""

import asyncio
from dataclasses import fields
from types import SimpleNamespace

import pytest

from custom_components.bticino_c300x import entry_locks
from custom_components.bticino_c300x.const import DATA_RUNTIME_ENTRIES, DOMAIN
from custom_components.bticino_c300x.data import (
    C300XRuntimeDiagnostics,
    C300XRuntimeResources,
)
from custom_components.bticino_c300x.runtime_manager import (
    cleanup_entry_runtime_resources,
)


@pytest.mark.parametrize("failing", ["cache", "expiry", "resources"])
def test_entry_cleanup_finishes_after_any_release_failure(failing):
    async def run():
        calls = []

        def release(name):
            calls.append(name)
            if name == failing:
                raise RuntimeError(f"synthetic {name} failure")

        task = asyncio.create_task(asyncio.Event().wait())
        runtime = SimpleNamespace(
            system_metrics_cache=SimpleNamespace(cancel=lambda: release("cache")),
            connection_state=SimpleNamespace(expire_unavailable=lambda: release("expiry")),
            resources=C300XRuntimeResources(
                unregister_webhook=lambda: release("resources"), startup_sync_task=task,
            ),
        )
        entry = SimpleNamespace(entry_id="cleanup-failure", runtime_data=runtime)
        entries = {entry.entry_id: runtime}
        hass = SimpleNamespace(data={DOMAIN: {DATA_RUNTIME_ENTRIES: entries}})
        entry_locks.entry_lock(entry.entry_id, "test")
        with pytest.raises(ExceptionGroup, match="Failed to clean up"):
            cleanup_entry_runtime_resources(hass, entry)
        await asyncio.gather(task, return_exceptions=True)
        assert task.cancelled()
        assert calls == ["cache", "expiry", "resources"]
        assert runtime.connection_state.expire_unavailable is None
        assert not runtime.display_bridge_alarm_notify_pending
        assert entries == {}
        assert not any(key[0] == entry.entry_id for key in entry_locks._locks)

    asyncio.run(run())


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
