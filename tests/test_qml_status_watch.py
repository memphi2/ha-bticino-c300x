"""After an agent restart or a reconnect HA reads the Display patch status again."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from custom_components.bticino_c300x import (
    qml_status_watch,
    repair_issues,
    runtime_manager,
    webhook,
)
from custom_components.bticino_c300x._api_normalize import normalize_system_metrics
from custom_components.bticino_c300x.const import SIGNAL_QML_PATCH_CHANGED
from custom_components.bticino_c300x.entry_locks import clear_entry_locks, entry_lock
from custom_components.bticino_c300x.qml_status_watch import (
    QmlStatusWatch,
    async_schedule_qml_status_refresh,
)
from custom_components.bticino_c300x.system_metrics import apply_system_metrics

STUCK = {"available": True, "patched": True, "transaction": "stuck"}
FINISHED = {"available": True, "patched": True, "transaction": None}


class _Api:
    def __init__(self, status: dict[str, Any]) -> None:
        self.status = status
        self.reads = 0

    async def async_qml_patch_status(self) -> dict[str, Any]:
        self.reads += 1
        return dict(self.status)


def _entry(api: _Api, *, stored_at: datetime | None, qml_status: bool = True) -> Any:
    tasks: list[asyncio.Task[Any]] = []

    def _create(_hass: Any, coro: Any, _name: str, eager_start: bool = True) -> Any:
        task = asyncio.get_running_loop().create_task(coro)
        tasks.append(task)
        return task

    runtime = SimpleNamespace(
        api=api,
        capabilities={"maintenance": {"supported": True, "qml_status": qml_status}},
        qml_patch_status=dict(STUCK),
        qml_patch_status_updated_at=stored_at,
        qml_status_watch=QmlStatusWatch(),
        system_metrics={},
        diagnostics=SimpleNamespace(agent_restart_count=0),
    )
    return SimpleNamespace(
        entry_id="entry-1", data={}, options={}, runtime_data=runtime,
        async_create_background_task=_create, tasks=tasks,
    )


@pytest.fixture
def ha(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    import homeassistant.helpers.dispatcher as dispatcher
    import homeassistant.helpers.event as event

    seen = SimpleNamespace(repair_syncs=0, signals=[])
    monkeypatch.setattr(
        repair_issues, "async_sync_entry_repair_issues",
        lambda *_: setattr(seen, "repair_syncs", seen.repair_syncs + 1),
    )
    monkeypatch.setattr(dispatcher, "async_dispatcher_send", lambda _hass, *args: seen.signals.append(args))
    monkeypatch.setattr(event, "async_call_later", lambda *_: lambda: None)
    clear_entry_locks("entry-1")
    yield seen
    clear_entry_locks("entry-1")


def _metrics(instance: str) -> dict[str, Any]:
    return normalize_system_metrics({
        "cpu_count": 1, "cpu_usage_percent": 1.0, "instance_id": instance,
        "sample_sequence": 1, "sample_age_ms": 0, "sample_interval_ms": 30000,
        "sample_interval_seconds": 30, "heartbeat_seconds": 600,
    })


def test_an_agent_restart_reads_the_status_and_syncs_the_issue(ha: SimpleNamespace) -> None:
    """The agent finished the leftover at start: the stuck status, even one
    stored a moment ago, is read again and the Repairs issue follows."""

    async def run() -> None:
        api = _Api(FINISHED)
        entry = _entry(api, stored_at=datetime.now(UTC))
        hass = SimpleNamespace()
        apply_system_metrics(entry, _metrics("a" * 32), hass=hass)
        assert entry.tasks == []
        apply_system_metrics(entry, _metrics("b" * 32), hass=hass)
        assert entry.runtime_data.diagnostics.agent_restart_count == 1
        await asyncio.gather(*entry.tasks)

        assert api.reads == 1
        assert entry.runtime_data.qml_patch_status["transaction"] is None
        assert ha.repair_syncs == 1
        assert (SIGNAL_QML_PATCH_CHANGED, "entry-1") in ha.signals

    asyncio.run(run())


@pytest.mark.parametrize("stored_minutes_ago", [5, 0])
def test_a_reconnect_reads_a_status_older_than_the_window(
    monkeypatch: pytest.MonkeyPatch, ha: SimpleNamespace, stored_minutes_ago: int
) -> None:
    """A power loss mid-write: the agent reports the leftover stuck. The
    reconnect reads it; a status stored within the window is not read again."""

    async def run() -> None:
        api = _Api(STUCK)
        entry = _entry(api, stored_at=datetime.now(UTC) - timedelta(minutes=stored_minutes_ago))
        entry.runtime_data.qml_patch_status = dict(FINISHED)
        manager = runtime_manager.C300XRuntimeManager(SimpleNamespace(), entry)
        manager.api = api  # type: ignore[assignment]
        manager.unregister_event_registration = lambda: None
        monkeypatch.setattr(webhook, "async_register_webhook", lambda *_: lambda: None)
        monkeypatch.setattr(webhook, "async_register_agent_event_webhook", lambda *_: lambda: None)
        display = AsyncMock()
        monkeypatch.setattr(manager, "_async_refresh_display_registration", display)
        await manager.async_register_callbacks()
        assert manager.on_runtime_registration_created is not None

        await manager.on_runtime_registration_created()
        await asyncio.gather(*entry.tasks)

        display.assert_awaited_once()
        if stored_minutes_ago:
            assert api.reads == 1
            assert entry.runtime_data.qml_patch_status["transaction"] == "stuck"
            assert ha.repair_syncs == 1
        else:
            assert entry.tasks == []
            assert api.reads == 0

    asyncio.run(run())


def test_the_read_waits_for_a_running_write_and_is_throttled(
    monkeypatch: pytest.MonkeyPatch, ha: SimpleNamespace
) -> None:
    monkeypatch.setattr(qml_status_watch, "READ_INTERVAL_SECONDS", 0.05)

    async def run() -> None:
        api = _Api(FINISHED)
        entry = _entry(api, stored_at=None)
        lock = entry_lock("entry-1", "qml_patch")
        await lock.acquire()  # a write runs
        async_schedule_qml_status_refresh(SimpleNamespace(), entry, restarted=True)
        for _ in range(5):
            await asyncio.sleep(0)
        assert api.reads == 0
        # Triggers while the read waits collapse into one more read.
        async_schedule_qml_status_refresh(SimpleNamespace(), entry, restarted=True)
        async_schedule_qml_status_refresh(SimpleNamespace(), entry, restarted=False)
        assert len(entry.tasks) == 1
        lock.release()
        await asyncio.gather(*entry.tasks)
        assert api.reads == 2
        assert ha.repair_syncs == 2

    asyncio.run(run())


def test_no_read_without_the_status_action(ha: SimpleNamespace) -> None:
    async def run() -> None:
        api = _Api(FINISHED)
        entry = _entry(api, stored_at=None, qml_status=False)
        async_schedule_qml_status_refresh(SimpleNamespace(), entry, restarted=True)
        assert entry.tasks == []

    asyncio.run(run())
