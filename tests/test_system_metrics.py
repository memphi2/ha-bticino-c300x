"""Regression coverage for ordered, fresh CPU snapshots."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from test_sensor import (
    C300XDeviceCpuSensor,
    _async_system_metrics,
    _drain_tasks,
    _FakeEntry,
    _FakeHass,
    _FakeRuntimeData,
)

from custom_components.bticino_c300x import system_metrics
from custom_components.bticino_c300x._api_normalize import normalize_system_metrics
from custom_components.bticino_c300x.api_errors import (
    C300XAgentApiError,
    C300XAgentApiResponseError,
)
from custom_components.bticino_c300x.system_metrics import (
    apply_system_metrics,
    cancel_metrics_expiry,
    invalidate_system_metrics,
    metrics_are_fresh,
    metrics_cache,
)


def snapshot(
    sequence: int = 1, instance: str = "a" * 32, **values: Any
) -> dict[str, Any]:
    return normalize_system_metrics(
        {
            "cpu_count": 1,
            "cpu_usage_percent": 1.0,
            "instance_id": instance,
            "sample_sequence": sequence,
            "sample_age_ms": 0,
            "sample_interval_ms": 30000,
            "sample_interval_seconds": 30,
            "heartbeat_seconds": 600,
            **values,
        }
    )


def test_reconnect_does_not_keep_an_hour_old_cpu_value() -> None:
    async def run() -> None:
        entry = _FakeEntry(
            runtime_data=_FakeRuntimeData(
                system_metrics={"cpu_count": 1, "cpu_usage_percent": 15.0},
                system_metrics_updated_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )
        entity = C300XDeviceCpuSensor(entry)
        entity.hass = _FakeHass()
        entry.runtime_data.connection_state.connection_state = "reconnecting"
        entity._handle_connection_state_changed(entry.entry_id)
        entry.runtime_data.connection_state.connection_state = "connected"
        entity._handle_connection_state_changed(entry.entry_id)
        await _drain_tasks()
        assert entry.runtime_data.api.metrics_calls == 1
        assert entity.native_value == 3.5

    asyncio.run(run())


def test_ordering_and_agent_restart() -> None:
    entry = _FakeEntry()
    assert apply_system_metrics(entry, snapshot(10))
    assert not apply_system_metrics(entry, snapshot(9, cpu_usage_percent=20.0))
    assert entry.runtime_data.system_metrics["cpu_usage_percent"] == 1.0
    assert apply_system_metrics(entry, snapshot(1, "b" * 32, cpu_usage_percent=None))
    assert not apply_system_metrics(entry, snapshot(11))
    assert entry.runtime_data.system_metrics["cpu_usage_percent"] is None
    assert apply_system_metrics(entry, snapshot(2, "b" * 32))
    assert not apply_system_metrics(entry, {"cpu_usage_percent": 20.0})


def test_http_generation_and_sequence_guards() -> None:
    entry = _FakeEntry()
    prior = snapshot(5)
    apply_system_metrics(entry, prior)
    generation = metrics_cache(entry).generation
    apply_system_metrics(entry, snapshot(6))
    assert not apply_system_metrics(
        entry, snapshot(5), request_generation=generation, request_snapshot=prior
    )
    assert apply_system_metrics(
        entry, snapshot(7), request_generation=generation, request_snapshot=prior
    )
    invalidate_system_metrics(entry)
    assert not apply_system_metrics(
        entry, snapshot(8), request_generation=generation, request_snapshot=prior
    )
    assert not metrics_are_fresh(entry)
    current_generation = metrics_cache(entry).generation
    invalidate_system_metrics(entry)
    assert metrics_cache(entry).generation == current_generation
    assert apply_system_metrics(entry, snapshot(1, "b" * 32))
    assert metrics_are_fresh(entry)


def test_deliberate_agent_downgrade_accepts_authoritative_legacy_http() -> None:
    entry = _FakeEntry()
    apply_system_metrics(entry, snapshot())
    prior = entry.runtime_data.system_metrics
    invalidate_system_metrics(entry)
    assert apply_system_metrics(
        entry,
        {"cpu_usage_percent": 2.0},
        request_snapshot=prior,
        request_generation=metrics_cache(entry).generation,
    )
    assert not apply_system_metrics(entry, snapshot(2))


def test_expiry_does_not_poll_or_extend_for_duplicate_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import homeassistant.helpers.dispatcher as dispatcher
    import homeassistant.helpers.event as event

    now = [1000.0]
    monkeypatch.setattr(system_metrics, "monotonic", lambda: now[0])
    timers = []
    cancelled = []
    signals = []

    def call_later(hass, delay, function):
        timers.append((delay, function))
        index = len(timers)
        return lambda: cancelled.append(index)

    monkeypatch.setattr(event, "async_call_later", call_later)
    monkeypatch.setattr(
        dispatcher, "async_dispatcher_send", lambda *args: signals.append(args)
    )
    entry = _FakeEntry()
    hass = _FakeHass()
    entity = C300XDeviceCpuSensor(entry)
    assert apply_system_metrics(entry, snapshot(), hass=hass)
    assert entity.available
    assert timers[-1][0] == 660
    now[0] += 100
    apply_system_metrics(entry, snapshot(), hass=hass)
    assert timers[-1][0] == 560
    assert cancelled == [1]
    now[0] += 561
    timers[-1][1](None)
    assert not entity.available
    assert entry.runtime_data.api.metrics_calls == 0
    assert len(signals) == 3
    apply_system_metrics(entry, snapshot(2), hass=hass)
    assert entity.available
    timers[-2][1](None)
    assert entity.available
    cancel_metrics_expiry(entry)
    cancel_metrics_expiry(entry)
    assert cancelled == [1, 3]


def test_old_snapshot_is_not_fresh_just_because_it_arrived_now() -> None:
    entry = _FakeEntry()
    apply_system_metrics(entry, snapshot(sample_age_ms=700000))
    assert not metrics_are_fresh(entry)


@pytest.mark.parametrize(
    "values",
    [
        {"instance_id": "bad"},
        {"instance_id": "G" * 32},
        {"sample_sequence": None},
        {"sample_sequence": True},
        {"sample_sequence": 0},
        {"sample_age_ms": -1},
        {"sample_interval_seconds": 0},
        {"heartbeat_seconds": 20},
        {"sample_interval_ms": 1.2},
    ],
)
def test_rejects_invalid_snapshot_metadata(values: dict[str, Any]) -> None:
    with pytest.raises(C300XAgentApiResponseError):
        snapshot(**values)


def test_null_startup_cpu_does_not_trigger_repeated_http_reads() -> None:
    async def run() -> None:
        entry = _FakeEntry()
        apply_system_metrics(entry, snapshot(cpu_usage_percent=None))
        results = await asyncio.gather(
            *[
                _async_system_metrics(
                    entry, force_refresh=True, required_key="cpu_usage_percent"
                )
                for _ in range(4)
            ]
        )
        assert entry.runtime_data.api.metrics_calls == 0
        assert all(item["cpu_usage_percent"] is None for item in results)

    asyncio.run(run())


def test_push_during_failed_http_read_stays_available() -> None:
    async def run() -> None:
        entry = _FakeEntry()

        async def fail_after_push():
            apply_system_metrics(entry, snapshot())
            raise C300XAgentApiError("lost HTTP response")

        entry.runtime_data.api.async_system_metrics = fail_after_push
        entity = C300XDeviceCpuSensor(entry)
        await entity.async_update()
        assert entity.available
        assert entity.native_value == 1.0

    asyncio.run(run())


def test_sensor_removal_cancels_inflight_recovery() -> None:
    async def run() -> None:
        entry = _FakeEntry()
        started = asyncio.Event()

        async def blocked():
            started.set()
            await asyncio.Event().wait()

        entry.runtime_data.api.async_system_metrics = blocked
        entity = C300XDeviceCpuSensor(entry)
        entity.hass = _FakeHass()
        entity._schedule_recovery_refresh_if_needed()
        await started.wait()
        task = entity._recovery_refresh_task
        entity._cancel_recovery_refresh()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert entity._recovery_refresh_task is None
        metrics_cache(entry).cancel()

    asyncio.run(run())


def test_failed_recovery_is_shared_and_not_automatically_retried() -> None:
    async def run() -> None:
        entry = _FakeEntry()
        release = asyncio.Event()
        calls = 0

        async def failing_read():
            nonlocal calls
            calls += 1
            await release.wait()
            raise C300XAgentApiError("offline")

        entry.runtime_data.api.async_system_metrics = failing_read
        tasks = [asyncio.create_task(_async_system_metrics(entry)) for _ in range(4)]
        await _drain_tasks()
        assert calls == 1
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(result, C300XAgentApiError) for result in results)
        assert metrics_cache(entry).refresh_task is None
        await _drain_tasks()
        assert calls == 1

    asyncio.run(run())


def test_cancelled_sensor_does_not_cancel_other_sensors_shared_read() -> None:
    async def run() -> None:
        entry = _FakeEntry()
        release = asyncio.Event()

        async def read():
            await release.wait()
            return snapshot()

        entry.runtime_data.api.async_system_metrics = read
        first = asyncio.create_task(_async_system_metrics(entry))
        second = asyncio.create_task(_async_system_metrics(entry))
        await _drain_tasks()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        release.set()
        assert (await second)["cpu_usage_percent"] == 1.0

    asyncio.run(run())


def test_runtime_cleanup_cancels_shared_read_and_expiry() -> None:
    async def run() -> None:
        entry = _FakeEntry()
        stopped = []

        async def read():
            await asyncio.Event().wait()

        entry.runtime_data.api.async_system_metrics = read
        task = asyncio.create_task(_async_system_metrics(entry))
        await _drain_tasks()
        state = metrics_cache(entry)
        state.cancel_expiry = lambda: stopped.append(True)
        state.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert state.cancel_expiry is None
        assert state.refresh_task is None
        assert stopped == [True]
        assert state.needs_refresh
        state.cancel()
        assert stopped == [True]

    asyncio.run(run())


@pytest.mark.parametrize("disconnect_signal", [False, True])
def test_reconnect_replaces_inflight_request(disconnect_signal: bool) -> None:
    async def run() -> None:
        entry = _FakeEntry()
        started = asyncio.Event()
        calls = 0

        async def read():
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                await asyncio.Event().wait()
            return snapshot(2)

        entry.runtime_data.api.async_system_metrics = read
        entity = C300XDeviceCpuSensor(entry)
        entity.hass = _FakeHass()
        entity._schedule_recovery_refresh_if_needed()
        await started.wait()
        if disconnect_signal:
            entry.runtime_data.connection_state.connection_state = "reconnecting"
            entity._handle_connection_state_changed(entry.entry_id)
        else:
            invalidate_system_metrics(entry)
        entry.runtime_data.connection_state.connection_state = "connected"
        entity._handle_connection_state_changed(entry.entry_id)
        task = entity._recovery_refresh_task
        assert task is not None
        await task
        assert calls == 2
        assert entity.native_value == 1.0
        assert entity.available
        assert entity._recovery_refresh_task is None

    asyncio.run(run())


def test_http_response_cannot_overwrite_a_push_received_while_waiting() -> None:
    async def run() -> None:
        entry = _FakeEntry()
        pushed = {"cpu_count": 1, "cpu_usage_percent": 1.0}

        async def delayed_response():
            entry.runtime_data.system_metrics = pushed
            entry.runtime_data.system_metrics_updated_at = datetime.now(UTC)
            return {"cpu_count": 1, "cpu_usage_percent": 20.0}

        entry.runtime_data.api.async_system_metrics = delayed_response
        result = await _async_system_metrics(entry)
        assert result["cpu_usage_percent"] == 1.0

    asyncio.run(run())
