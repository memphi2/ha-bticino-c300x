"""Consumers reuse the live push coalescer, never recorder or inferred sensors."""

import asyncio
from itertools import combinations
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.bticino_c300x import dashboard_energy_data as data
from custom_components.bticino_c300x import dashboard_energy_power as history
from custom_components.bticino_c300x import dashboard_energy_updates as updates
from custom_components.bticino_c300x.dashboard_energy import (
    ENERGY_DAY_VIEWS, ENERGY_VIEWS, EnergyDay, EnergyMeter, EnergySources,
)
from custom_components.bticino_c300x.dashboard_energy_consumers import EnergyConsumer

SOURCES = EnergySources(grid_from=(EnergyMeter("sensor.energy", "sensor.cost"),),
                        grid_power=("sensor.grid",), consumers=(EnergyConsumer("sensor.consumer"),))
VIEW_SETS = [list(views) for count in range(len(ENERGY_VIEWS) + 1) for views in combinations(ENERGY_VIEWS, count)]


@pytest.fixture
def env(monkeypatch):
    entry = SimpleNamespace(entry_id="consumers-lifecycle", data={},
                            options={"energy_page": {"enabled": True, "views": ["consumers"]}},
                            runtime_data=SimpleNamespace(resources=SimpleNamespace(closed=False)))
    state = SimpleNamespace(entry=entry, clock=100., wakes=[], tracked=[], cancelled=[], delayed=[], ticks=[],
        hass=SimpleNamespace(config=SimpleNamespace(currency="EUR", components={"energy"}), states=SimpleNamespace(
            get=Mock(return_value=SimpleNamespace(state="1.5", attributes={"unit_of_measurement": "kW"})))),
        sources=AsyncMock(return_value=SOURCES))
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


@pytest.mark.parametrize("views", VIEW_SETS)
def test_every_view_combination_reads_and_tracks_only_its_resources(env, monkeypatch, views):
    env.entry.options["energy_page"]["views"] = views
    day, power = AsyncMock(return_value=EnergyDay()), AsyncMock(return_value=None)
    expire = Mock()
    monkeypatch.setattr(data, "_async_energy_day", day)
    monkeypatch.setattr(data, "async_power_history", power)
    monkeypatch.setattr(updates, "expire_energy_day", expire)

    async def scenario():
        result = await data.async_energy_dashboard_page(env.hass, env.entry, "en")
        assert (result is not None) == bool(views)
        if "consumers" in views:
            assert result["energy"]["consumers"]["items"][0]["value"] == "1500 W"
        assert await env.updates.async_start() == bool(views)
        if views:
            assert len(env.ticks) == 1 and env.ticks[0][0] == 300
            await env.ticks[0][1]()

    asyncio.run(scenario())
    assert day.await_count == int(bool(set(views) & set(ENERGY_DAY_VIEWS)))
    assert power.await_count == int("power" in views)
    ids = SOURCES.live_power_entities(views)
    assert {call.args[0] for call in env.hass.states.get.call_args_list} == ids
    assert env.hass.states.get.call_count == len(ids)
    assert [entities for entities, _ in env.tracked] == ([sorted(ids)] if ids else [])
    assert expire.call_count == int(bool(set(views) & set(ENERGY_DAY_VIEWS)))
    assert env.delayed == []


@pytest.mark.parametrize("views", [["distribution"], ["bogus"], [], [None]])
def test_retired_or_unknown_selection_reads_nothing_and_starts_no_watch(env, views):
    env.entry.options["energy_page"]["views"] = views

    async def scenario():
        assert await data.async_energy_dashboard_page(env.hass, env.entry, "en") is None
        assert not await env.updates.async_start()

    asyncio.run(scenario())
    env.sources.assert_not_awaited()
    env.hass.states.get.assert_not_called()
    assert env.ticks == env.tracked == env.delayed == env.wakes == []


def test_consumers_only_never_accesses_recorder_or_starts_history(env, monkeypatch):
    from homeassistant.helpers import recorder

    recorder_access = Mock(side_effect=AssertionError("Consumers must never read recorder"))
    monkeypatch.setattr(recorder, "get_instance", recorder_access)
    data._DAY_CACHE[env.entry.entry_id] = data._DayCache()
    history._POWER_CACHE[env.entry.entry_id] = SimpleNamespace(task=None)

    async def scenario():
        for _ in range(3):
            result = await data.async_energy_dashboard_page(env.hass, env.entry, "en")
            assert set(result["energy"]) == {"views", "consumers"}
            assert env.entry.entry_id not in data._DAY_CACHE
            assert env.entry.entry_id not in history._POWER_CACHE

    asyncio.run(scenario())
    assert [call.args[0] for call in env.hass.states.get.call_args_list] == ["sensor.consumer"] * 3
    recorder_access.assert_not_called()


def event(old, new, unit="W", entity_id="sensor.consumer"):
    def state(value):
        return SimpleNamespace(state=value, attributes={"unit_of_measurement": unit})
    return SimpleNamespace(data={"entity_id": entity_id, "old_state": state(old), "new_state": state(new)})


def test_exact_rank_changes_reuse_ten_second_coalescing_and_trailing_wakeup(env):
    asyncio.run(env.updates.async_start())
    changed = env.tracked[0][1]
    assert env.tracked[0][0] == ["sensor.consumer"]
    changed(event(1000, 1001))
    assert env.wakes == [100]
    env.clock = 103
    changed(event(1001, 1002))
    changed(event(1002, 1003))
    assert len(env.delayed) == 1 and env.delayed[0][0] == 7
    env.clock = 110
    env.delayed[0][1]()
    assert env.wakes == [100, 110]
    env.updates.stop()
    changed(event(1003, 1004))
    assert env.wakes == [100, 110]


@pytest.mark.parametrize(("old", "new"), [(1000, 1000), (None, None), ("unknown", "unavailable"), (-1, -2)])
def test_unchanged_unavailable_or_invalid_watts_does_not_wake(env, old, new):
    asyncio.run(env.updates.async_start())
    env.tracked[0][1](event(old, new))
    assert env.wakes == env.delayed == []


def test_unit_or_name_changes_and_recovery_from_unknown_wake(env):
    asyncio.run(env.updates.async_start())
    change = event(1000, 1000)
    change.data["new_state"].attributes["unit_of_measurement"] = None
    env.tracked[0][1](change)
    assert env.wakes == [100]
    env.clock = 115
    env.tracked[0][1](event("unavailable", 0))
    assert env.wakes == [100, 115]


def test_switching_live_views_removes_inactive_sensor_subscription(env):
    env.entry.options["energy_page"]["views"] = ["now", "consumers"]
    asyncio.run(env.updates.async_start())
    assert env.tracked[-1][0] == ["sensor.consumer", "sensor.grid"]
    env.entry.options["energy_page"]["views"] = ["consumers"]
    env.updates._active_views()
    assert env.tracked[-1][0] == ["sensor.consumer"]
    env.updates._handle_power_change(event(1, 2, entity_id="sensor.grid"))
    assert env.wakes == []


@pytest.mark.parametrize("views", [["today"], ["power"], [], ["distribution"]])
def test_removing_last_live_view_cancels_delayed_wakeup(env, views):
    asyncio.run(env.updates.async_start())
    env.updates._handle_power_change(event(1, 2))
    env.clock = 103
    env.updates._handle_power_change(event(2, 3))
    env.entry.options["energy_page"]["views"] = views
    env.updates._active_views()
    assert "power" in env.cancelled and "delayed" in env.cancelled
    env.delayed[0][1]()
    assert env.wakes == [100]


@pytest.mark.parametrize("reason", ["page_off", "all_off", "unload", "replacement"])
def test_pending_source_read_cannot_read_states_or_resubscribe_after_retirement(env, reason):
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


def test_consumers_only_without_aggregate_sources_or_power_mapping_is_empty_not_zero(env):
    env.sources.return_value = EnergySources()
    result = asyncio.run(data.async_energy_dashboard_page(env.hass, env.entry, "en"))
    assert result["energy"]["consumers"]["items"] == []
    env.hass.states.get.assert_not_called()
    asyncio.run(env.updates.async_start())
    asyncio.run(env.ticks[0][1]())
    assert env.tracked == env.wakes == []


def test_shared_live_sensor_is_read_once_and_keeps_now_semantics(env):
    env.sources.return_value = EnergySources(grid_from=SOURCES.grid_from, grid_power=("sensor.consumer",),
                                             consumers=SOURCES.consumers)
    env.entry.options["energy_page"]["views"] = ["now", "consumers"]
    asyncio.run(env.updates.async_start())
    # Now's legacy no-unit fallback must still refresh even though Consumers
    # correctly rejects the sensor without an explicit power unit.
    env.updates._handle_power_change(event(100, 200, unit=None))
    assert env.wakes == [100]


@pytest.mark.parametrize("views", [["consumers"], ["power", "consumers"], ["now"], ["power"], [], ["distribution"]])
def test_actual_manager_maps_only_enabled_consumers_without_other_live_or_recorder_reads(monkeypatch, views):
    from homeassistant.components.energy import data as energy_data
    from homeassistant.helpers import recorder

    preferences = {"energy_sources": [], "device_consumption": [
        {"stat_consumption": "sensor.desk_energy", "stat_rate": "sensor.desk_watts", "name": "Desk"},
        {"stat_consumption": "sensor.no_power_mapping"},
    ]}
    manager = AsyncMock(return_value=SimpleNamespace(data=preferences))
    monkeypatch.setattr(energy_data, "async_get_manager", manager)
    recorder_access = Mock(side_effect=AssertionError("no recorder reads for device power"))
    monkeypatch.setattr(recorder, "get_instance", recorder_access)
    entry = SimpleNamespace(entry_id="consumer-manager", data={}, options={"energy_page": {"enabled": True, "views": views}})
    get_state = Mock(return_value=SimpleNamespace(state="1.5", attributes={"unit_of_measurement": "kW"}))
    hass = SimpleNamespace(config=SimpleNamespace(components={"energy"}, currency="EUR"), data={},
                           states=SimpleNamespace(get=get_state))
    result = asyncio.run(data.async_energy_dashboard_page(hass, entry, "en"))
    assert manager.await_count == int(bool(set(views) & set(ENERGY_VIEWS)))
    if "consumers" in views:
        assert result["energy"]["consumers"]["items"][0]["value"] == "1500 W"
        get_state.assert_called_once_with("sensor.desk_watts")
        if "power" in views:
            assert result["energy"]["power"]["series"] == []
    else:
        assert result is None
        get_state.assert_not_called()
    recorder_access.assert_not_called()
    assert entry.entry_id not in data._DAY_CACHE
    assert entry.entry_id not in history._POWER_CACHE


@pytest.mark.parametrize("period", ["hour", "5minute"])
def test_switch_to_consumers_retires_pending_day_and_history_work(env, monkeypatch, period):
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
        env.entry.options["energy_page"]["views"] = ["consumers"]
        result = await data.async_energy_dashboard_page(env.hass, env.entry, "en")
        assert result["energy"]["consumers"]["items"][0]["watts"] == 1500
        assert env.entry.entry_id not in data._DAY_CACHE
        release.set()
        assert await pending is None and await waiter is None
        assert cached.key is None and cached.read_at == float("-inf")
        assert env.entry.entry_id not in data._DAY_CACHE
        assert env.entry.entry_id not in history._POWER_CACHE

    asyncio.run(scenario())
    assert calls == [("hour", {"change"})] + ([("5minute", {"change"})] if period == "5minute" else [])


def test_existing_tick_refreshes_consumer_configuration_without_another_timer(env):
    async def scenario():
        await env.updates.async_start()
        env.sources.return_value = EnergySources(consumers=(EnergyConsumer("sensor.replacement"),))
        await env.ticks[0][1]()

    asyncio.run(scenario())
    assert [entities for entities, _ in env.tracked] == [["sensor.consumer"], ["sensor.replacement"]]
    assert len(env.ticks) == 1 and env.ticks[0][0] == 300
    assert env.wakes == [100]


@pytest.mark.parametrize("retire", ["stop", "off"])
def test_pending_configuration_read_cannot_resubscribe_after_shutdown(env, retire):
    async def scenario():
        await env.updates.async_start()

        async def read(*_args):
            if retire == "stop":
                env.updates.stop()
            else:
                env.entry.options["energy_page"]["enabled"] = False
            return EnergySources(consumers=(EnergyConsumer("sensor.replacement"),))

        env.sources.side_effect = read
        await env.ticks[0][1]()
        assert env.wakes == [] and len(env.tracked) == 1
        assert env.updates._unsub_tick is None and env.updates._unsub_power is None

    asyncio.run(scenario())
