"""No new recorder dispatch after an Energy view or its runtime is retired."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.bticino_c300x import dashboard_energy_data as data
from custom_components.bticino_c300x import dashboard_energy_power as power
from custom_components.bticino_c300x.dashboard_energy import EnergyMeter, EnergySources

SOURCES = EnergySources(
    grid_from=(EnergyMeter("sensor.energy"),), grid_power=("sensor.power",),
)


@pytest.fixture
def reads(monkeypatch):
    from homeassistant.components import recorder
    from homeassistant.helpers import recorder as recorder_helper

    entry = SimpleNamespace(
        entry_id="read-lifecycle", data={},
        options={"energy_page": {"enabled": True, "views": ["today", "power"]}},
        runtime_data=SimpleNamespace(resources=SimpleNamespace(closed=False)),
    )
    state = SimpleNamespace(
        entry=entry, calls=[], block=None, started=asyncio.Event(), release=asyncio.Event(),
        hass=SimpleNamespace(config=SimpleNamespace(currency="EUR")),
    )

    async def execute(_function, _hass, since, _until, _ids, period, _units, types):
        state.calls.append((period, frozenset(types)))
        if period == state.block:
            state.started.set()
            await state.release.wait()
        if types == {"mean"}:
            return {"sensor.power": [
                {"start": since.timestamp() + index * 300,
                 "end": since.timestamp() + (index + 1) * 300, "mean": 100}
                for index in range(3)
            ]}
        return {}

    instance = SimpleNamespace(async_add_executor_job=execute)
    monkeypatch.setattr(recorder, "get_instance", lambda _hass: instance)
    monkeypatch.setattr(recorder_helper, "get_instance", lambda _hass: instance)
    state.sources = AsyncMock(return_value=SOURCES)
    monkeypatch.setattr(data, "async_configured_energy_sources", state.sources)

    def retire(reason):
        if reason == "all_off":
            entry.options["energy_page"]["views"] = []
        elif reason == "page_off":
            entry.options["energy_page"]["enabled"] = False
        elif reason == "power_only":
            entry.options["energy_page"]["views"] = ["power"]
        elif reason == "today_only":
            entry.options["energy_page"]["views"] = ["today"]
        elif reason == "unload":
            entry.runtime_data.resources.closed = True
        elif reason == "runtime_identity":
            # Deliberately do not close the old resources: identity must guard too.
            entry.runtime_data = SimpleNamespace(resources=SimpleNamespace(closed=False))
        else:
            raise AssertionError(reason)

    state.retire = retire
    yield state
    data.forget_energy_day(entry.entry_id)
    power.forget_power_history(entry.entry_id)


@pytest.mark.parametrize("reason", ["all_off", "page_off", "power_only", "unload", "runtime_identity"])
@pytest.mark.parametrize("period", ["hour", "5minute"])
def test_retired_day_read_starts_no_followup_and_does_not_cache(reads, reason, period):
    async def scenario():
        reads.block = period
        pending = asyncio.create_task(data.async_energy_dashboard_page(reads.hass, reads.entry, "en"))
        await reads.started.wait()
        cached = data._DAY_CACHE[reads.entry.entry_id]
        reads.retire(reason)
        reads.release.set()
        assert await pending is None
        expected = [("hour", frozenset({"change"}))]
        if period == "5minute":
            expected.append(("5minute", frozenset({"change"})))
        assert reads.calls == expected
        assert cached.key is None and cached.read_at == float("-inf")
        assert not power._POWER_CACHE

    asyncio.run(scenario())


@pytest.mark.parametrize("reason", ["all_off", "power_only", "unload", "runtime_identity"])
def test_retired_day_lock_waiter_does_not_query_after_leader_cancellation(reads, reason):
    async def scenario():
        reads.block = "hour"
        first = asyncio.create_task(data.async_energy_dashboard_page(reads.hass, reads.entry, "en"))
        await reads.started.wait()
        cached = data._DAY_CACHE[reads.entry.entry_id]
        second = asyncio.create_task(data.async_energy_dashboard_page(reads.hass, reads.entry, "en"))
        await asyncio.sleep(0)
        assert reads.sources.await_count == 2 and not second.done()
        reads.retire(reason)
        first.cancel()
        reads.release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert await second is None
        assert reads.calls == [("hour", frozenset({"change"}))]
        assert cached.key is None and cached.read_at == float("-inf")

    asyncio.run(scenario())


@pytest.mark.parametrize("reason", ["all_off", "page_off", "today_only", "unload", "runtime_identity"])
def test_scheduled_power_read_checks_activity_without_options_listener(reads, reason):
    async def scenario():
        reads.entry.options["energy_page"]["views"] = ["power"]
        pending = asyncio.create_task(data.async_energy_dashboard_page(reads.hass, reads.entry, "en"))
        # The page schedules its shared task, then this callback runs before it.
        asyncio.get_running_loop().call_soon(reads.retire, reason)
        assert await pending is None
        assert reads.calls == []
        assert not power._POWER_CACHE

    asyncio.run(scenario())


@pytest.mark.parametrize("reason", ["all_off", "today_only", "unload", "runtime_identity"])
def test_already_dispatched_power_read_can_finish_but_does_not_retain_cache(reads, reason):
    async def scenario():
        reads.entry.options["energy_page"]["views"] = ["power"]
        reads.block = "5minute"
        pending = asyncio.create_task(data.async_energy_dashboard_page(reads.hass, reads.entry, "en"))
        await reads.started.wait()
        reads.retire(reason)
        reads.release.set()
        assert await pending is None
        assert reads.calls == [("5minute", frozenset({"mean"}))]
        assert not power._POWER_CACHE

    asyncio.run(scenario())


def test_retired_power_task_cannot_evict_replacement_runtime_cache(reads):
    async def scenario():
        reads.entry.options["energy_page"]["views"] = ["power"]
        pending = asyncio.create_task(data.async_energy_dashboard_page(reads.hass, reads.entry, "en"))
        replacement = None

        def replace():
            nonlocal replacement
            old = power._POWER_CACHE[reads.entry.entry_id]
            reads.retire("runtime_identity")
            replacement = power._PowerCache(old.key, old.history)
            power._POWER_CACHE[reads.entry.entry_id] = replacement

        asyncio.get_running_loop().call_soon(replace)
        assert await pending is None
        assert reads.calls == []
        assert power._POWER_CACHE[reads.entry.entry_id] is replacement
        assert replacement.read_at == float("-inf")

    asyncio.run(scenario())


def test_retired_day_read_cannot_touch_replacement_runtime_cache(reads):
    async def scenario():
        reads.block = "hour"
        pending = asyncio.create_task(data.async_energy_dashboard_page(reads.hass, reads.entry, "en"))
        await reads.started.wait()
        reads.retire("runtime_identity")
        replacement = data._DayCache()
        data._DAY_CACHE[reads.entry.entry_id] = replacement
        reads.release.set()
        assert await pending is None
        assert reads.calls == [("hour", frozenset({"change"}))]
        assert data._DAY_CACHE[reads.entry.entry_id] is replacement
        assert replacement.key is None and replacement.read_at == float("-inf")

    asyncio.run(scenario())


def test_day_view_change_keeps_shared_cache_usable_by_new_request(reads):
    async def scenario():
        reads.block = "hour"
        first = asyncio.create_task(data.async_energy_dashboard_page(reads.hass, reads.entry, "en"))
        await reads.started.wait()
        cached = data._DAY_CACHE[reads.entry.entry_id]
        reads.entry.options["energy_page"]["views"] = ["balance"]
        second = asyncio.create_task(data.async_energy_dashboard_page(reads.hass, reads.entry, "en"))
        await asyncio.sleep(0)
        reads.release.set()
        assert await first is None
        assert await second is not None
        assert reads.calls == [
            ("hour", frozenset({"change"})),
            ("hour", frozenset({"change"})), ("5minute", frozenset({"change"})),
        ]
        assert data._DAY_CACHE[reads.entry.entry_id] is cached
        assert cached.key is not None

    asyncio.run(scenario())
