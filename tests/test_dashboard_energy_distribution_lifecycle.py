"""Live distribution has no recorder dependency and shares existing wake-ups."""

import asyncio
from itertools import combinations
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.bticino_c300x import dashboard_energy_data as data
from custom_components.bticino_c300x import dashboard_energy_power as history
from custom_components.bticino_c300x import dashboard_energy_updates as updates
from custom_components.bticino_c300x.dashboard_energy import (
    ENERGY_DAY_VIEWS,
    ENERGY_LIVE_VIEWS,
    ENERGY_VIEWS,
    EnergyDay,
    EnergyMeter,
    EnergySources,
)

SOURCES = EnergySources(
    grid_from=(EnergyMeter("sensor.energy", "sensor.cost"),),
    grid_power=("sensor.power",),
)
VIEW_SETS = [list(views) for count in range(len(ENERGY_VIEWS) + 1)
             for views in combinations(ENERGY_VIEWS, count)]


@pytest.fixture
def env(monkeypatch):
    entry = SimpleNamespace(
        entry_id="distribution-lifecycle", data={},
        options={"energy_page": {"enabled": True, "views": ["distribution"]}},
        runtime_data=SimpleNamespace(resources=SimpleNamespace(closed=False)),
    )
    state = SimpleNamespace(
        entry=entry, clock=100.0, wakes=[], tracked=[], cancelled=[], delayed=[], ticks=[],
        hass=SimpleNamespace(config=SimpleNamespace(currency="EUR"), states=SimpleNamespace(
            get=Mock(return_value=SimpleNamespace(state="1.5", attributes={"unit_of_measurement": "kW"})),
        )),
        sources=AsyncMock(return_value=SOURCES),
    )
    monkeypatch.setattr(data, "async_configured_energy_sources", state.sources)
    monkeypatch.setattr(updates, "async_configured_energy_sources", state.sources)
    monkeypatch.setattr(updates, "monotonic", lambda: state.clock)

    from homeassistant.helpers import event

    def track(_hass, entities, action):
        state.tracked.append((entities, action))
        return lambda: state.cancelled.append("power")

    def tick(_hass, action, interval):
        state.ticks.append((interval.total_seconds(), action))
        return lambda: state.cancelled.append("tick")

    def delayed(_hass, delay, action):
        state.delayed.append((delay, action))
        return lambda: state.cancelled.append("delayed")

    monkeypatch.setattr(event, "async_track_state_change_event", track)
    monkeypatch.setattr(event, "async_track_time_interval", tick)
    monkeypatch.setattr(event, "async_call_later", delayed)
    state.updates = updates.EnergyPageUpdates(state.hass, entry, lambda: state.wakes.append(state.clock))
    yield state
    state.updates.stop()
    data.forget_energy_day(entry.entry_id)
    history.forget_power_history(entry.entry_id)


@pytest.mark.parametrize("views", VIEW_SETS)
def test_every_view_combination_reads_only_its_resources(env, monkeypatch, views):
    env.entry.options["energy_page"]["views"] = views
    day = AsyncMock(return_value=EnergyDay())
    power = AsyncMock(return_value=None)
    monkeypatch.setattr(data, "_async_energy_day", day)
    monkeypatch.setattr(data, "async_power_history", power)
    result = asyncio.run(data.async_energy_dashboard_page(env.hass, env.entry, "en"))
    assert (result is not None) == bool(views)
    assert day.await_count == int(bool(set(views) & set(ENERGY_DAY_VIEWS)))
    assert power.await_count == int("power" in views)
    assert env.hass.states.get.call_count == int(bool(set(views) & set(ENERGY_LIVE_VIEWS)))
    if "distribution" in views:
        assert result["energy"]["distribution"]["right"][0]["watts"] == 1500


@pytest.mark.parametrize("views", [["distribution"], ["power"], ["power", "distribution"], []])
def test_no_day_view_drops_shared_day_cache_before_reading_sources(env, views):
    data._DAY_CACHE[env.entry.entry_id] = data._DayCache(day=EnergyDay(hours={"sensor.energy": [1] * 24}))
    env.entry.options["energy_page"]["views"] = views
    assert data._active_energy_views(env.entry) == views
    assert env.entry.entry_id not in data._DAY_CACHE


def test_distribution_only_never_touches_recorder_or_caches_it(env, monkeypatch):
    from homeassistant.helpers import recorder

    recorder_access = Mock(side_effect=AssertionError("distribution must not request recorder"))
    monkeypatch.setattr(recorder, "get_instance", recorder_access)
    data._DAY_CACHE[env.entry.entry_id] = data._DayCache()
    history._POWER_CACHE[env.entry.entry_id] = SimpleNamespace(task=None)

    async def scenario():
        for _ in range(3):
            result = await data.async_energy_dashboard_page(env.hass, env.entry, "en")
            assert set(result["energy"]) == {"views", "distribution"}
            assert result["energy"]["distribution"]["complete"] is True
            assert env.entry.entry_id not in data._DAY_CACHE
            assert env.entry.entry_id not in history._POWER_CACHE

    asyncio.run(scenario())
    recorder_access.assert_not_called()


def test_unconfigured_zero_needs_no_subscription_or_recorder_and_creates_no_history(env, monkeypatch):
    from homeassistant.helpers import recorder

    recorder_access = Mock(side_effect=AssertionError("no configured power to record"))
    monkeypatch.setattr(recorder, "get_instance", recorder_access)
    env.sources.return_value = EnergySources(
        grid_from=SOURCES.grid_from, solar=(EnergyMeter("sensor.solar_energy"),),
        battery_from=(EnergyMeter("sensor.battery_energy"),),
    )
    env.entry.options["energy_page"]["views"] = ["power", "distribution"]

    async def scenario():
        result = await data.async_energy_dashboard_page(env.hass, env.entry, "en")
        distribution = result["energy"]["distribution"]
        assert distribution["complete"] is True and distribution["status"] == ""
        assert all(item["watts"] == 0 for side in ("left", "right") for item in distribution[side])
        assert result["energy"]["power"]["series"] == []
        assert await env.updates.async_start()
        assert env.tracked == [] and env.delayed == []
        assert len(env.ticks) == 1 and env.ticks[0][0] == 300

    asyncio.run(scenario())
    env.hass.states.get.assert_not_called()
    recorder_access.assert_not_called()
    assert env.entry.entry_id not in data._DAY_CACHE
    assert env.entry.entry_id not in history._POWER_CACHE


@pytest.mark.parametrize("period", ["hour", "5minute"])
def test_switch_to_distribution_retires_pending_day_read_without_followup(env, monkeypatch, period):
    from homeassistant.helpers import recorder

    calls = []

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        async def execute(_function, _hass, _since, _until, _ids, current, _units, types):
            calls.append((current, types))
            if current == period:
                started.set()
                await release.wait()
            return {}

        monkeypatch.setattr(recorder, "get_instance", lambda _hass: SimpleNamespace(async_add_executor_job=execute))
        env.entry.options["energy_page"]["views"] = ["now", "power"]
        pending = asyncio.create_task(data.async_energy_dashboard_page(env.hass, env.entry, "en"))
        await asyncio.wait_for(started.wait(), 2)
        cached = data._DAY_CACHE[env.entry.entry_id]
        waiter = asyncio.create_task(data.async_energy_dashboard_page(env.hass, env.entry, "en"))
        await asyncio.sleep(0)
        env.entry.options["energy_page"]["views"] = ["distribution"]
        result = await data.async_energy_dashboard_page(env.hass, env.entry, "en")
        assert result["energy"]["distribution"]["complete"] is True
        assert env.entry.entry_id not in data._DAY_CACHE
        release.set()
        assert await pending is None and await waiter is None
        assert cached.key is None and cached.read_at == float("-inf")
        assert env.entry.entry_id not in data._DAY_CACHE
        assert env.entry.entry_id not in history._POWER_CACHE

    asyncio.run(scenario())
    assert calls == [("hour", {"change"})] + ([("5minute", {"change"})] if period == "5minute" else [])


def test_switch_before_scheduled_history_dispatch_drops_power_cache(env, monkeypatch):
    from homeassistant.helpers import recorder

    read = Mock(side_effect=AssertionError("retired power read must not dispatch"))
    monkeypatch.setattr(recorder, "get_instance", read)

    async def scenario():
        env.entry.options["energy_page"]["views"] = ["power"]
        pending = asyncio.create_task(data.async_energy_dashboard_page(env.hass, env.entry, "en"))
        asyncio.get_running_loop().call_soon(
            env.entry.options["energy_page"].update, {"views": ["distribution"]},
        )
        assert await pending is None
        assert env.entry.entry_id not in history._POWER_CACHE

    asyncio.run(scenario())
    read.assert_not_called()


@pytest.mark.parametrize("reason", ["page_off", "all_off", "unload", "replacement"])
def test_live_page_read_does_not_outlive_runtime_or_view(env, reason):
    async def retire(*_args):
        if reason == "page_off":
            env.entry.options["energy_page"]["enabled"] = False
        elif reason == "all_off":
            env.entry.options["energy_page"]["views"] = []
        elif reason == "unload":
            env.entry.runtime_data.resources.closed = True
        else:
            env.entry.runtime_data = SimpleNamespace(resources=SimpleNamespace(closed=False))
        return SOURCES

    env.sources.side_effect = retire
    assert asyncio.run(data.async_energy_dashboard_page(env.hass, env.entry, "en")) is None
    env.hass.states.get.assert_not_called()
    assert env.entry.entry_id not in data._DAY_CACHE


@pytest.mark.parametrize("views", VIEW_SETS)
def test_subscriptions_and_expiration_follow_the_same_view_sets(env, monkeypatch, views):
    env.entry.options["energy_page"]["views"] = views
    expire = Mock()
    monkeypatch.setattr(updates, "expire_energy_day", expire)

    async def scenario():
        assert await env.updates.async_start() == bool(views)
        if views:
            assert len(env.ticks) == 1 and env.ticks[0][0] == 300
            await env.ticks[0][1]()

    asyncio.run(scenario())
    assert len(env.tracked) == int(bool(set(views) & set(ENERGY_LIVE_VIEWS)))
    assert expire.call_count == int(bool(set(views) & set(ENERGY_DAY_VIEWS)))
    assert not env.delayed


def test_distribution_uses_existing_ten_second_coalescing_and_trailing_wakeup(env):
    asyncio.run(env.updates.async_start())
    assert len(env.tracked) == 1 and env.tracked[0][0] == ["sensor.power"]
    changed = env.tracked[0][1]
    changed(None)
    assert env.wakes == [100]
    env.clock = 103
    changed(None)
    changed(None)
    assert len(env.delayed) == 1 and env.delayed[0][0] == 7
    env.clock = 110
    env.delayed[0][1]()
    assert env.wakes == [100, 110]
    env.updates.stop()
    changed(None)
    assert env.wakes == [100, 110]
    assert sorted(env.cancelled) == ["power", "tick"]


def test_switch_from_now_to_distribution_keeps_live_subscription_and_pending_wake(env):
    env.entry.options["energy_page"]["views"] = ["now"]
    asyncio.run(env.updates.async_start())
    env.updates._handle_power_change(None)
    env.clock = 103
    env.updates._handle_power_change(None)
    data._DAY_CACHE[env.entry.entry_id] = data._DayCache()
    env.entry.options["energy_page"]["views"] = ["distribution"]
    assert env.updates._active_views() == ["distribution"]
    assert env.entry.entry_id not in data._DAY_CACHE
    assert len(env.tracked) == 1 and env.cancelled == []
    env.clock = 110
    env.delayed[0][1]()
    assert env.wakes == [100, 110]


@pytest.mark.parametrize("views", [["today"], ["power"], []])
def test_removing_last_live_view_cancels_subscription_and_delayed_wake(env, views):
    asyncio.run(env.updates.async_start())
    env.updates._handle_power_change(None)
    env.clock = 103
    env.updates._handle_power_change(None)
    env.entry.options["energy_page"]["views"] = views
    env.updates._active_views()
    assert "power" in env.cancelled and "delayed" in env.cancelled
    env.clock = 110
    env.delayed[0][1]()
    assert env.wakes == [100]


@pytest.mark.parametrize("retire", ["stop", "off"])
def test_pending_source_refresh_cannot_resubscribe_after_shutdown(env, retire):
    async def scenario():
        await env.updates.async_start()

        async def read(*_args):
            if retire == "stop":
                env.updates.stop()
            else:
                env.entry.options["energy_page"]["enabled"] = False
            return EnergySources(grid_from=SOURCES.grid_from, grid_power=("sensor.replacement",))

        env.sources.side_effect = read
        await env.ticks[0][1]()
        assert env.wakes == [] and len(env.tracked) == 1
        assert env.updates._unsub_tick is None and env.updates._unsub_power is None

    asyncio.run(scenario())
