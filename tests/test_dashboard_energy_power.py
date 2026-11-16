"""Recorder-backed power curves: bounds, coverage, caching and entry lifecycle."""

import asyncio
import json
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import pytest

from custom_components.bticino_c300x import (
    dashboard_energy_data as data,
)
from custom_components.bticino_c300x import (
    dashboard_energy_power as power,
)
from custom_components.bticino_c300x import (
    dashboard_energy_updates as updates,
)
from custom_components.bticino_c300x.dashboard_energy import (
    EnergyDay,
    EnergyMeter,
    EnergySources,
)
from custom_components.bticino_c300x.dashboard_labels import ENERGY_LABELS_BY_LANGUAGE

START = datetime(2026, 11, 15, tzinfo=UTC)
SOURCES = EnergySources(grid_from=(EnergyMeter("sensor.energy"),), grid_power=("sensor.power",))


def entry(views=None, enabled=True):
    return SimpleNamespace(entry_id="power-test", data={}, options={
        "energy_page": {"enabled": enabled, "views": ["power"] if views is None else views},
    })


def rows(start=START, values=(0, -300, -600), *, offset=0):
    stamp = start.timestamp() + offset
    return [{"start": stamp + index * 300, "end": stamp + (index + 1) * 300, "mean": value}
            for index, value in enumerate(values)]


def history(start=START, value=900):
    return power.power_history_from_statistics(
        start, start + timedelta(days=1), frozenset(SOURCES.power_entities),
        {"sensor.power": rows(start, (value,) * 3)},
    )


@pytest.fixture(autouse=True)
def cache_and_clock(monkeypatch):
    clock = {"time": 1000.0, "day": START}
    monkeypatch.setattr(power, "monotonic", lambda: clock["time"])
    monkeypatch.setattr(power.dt_util, "start_of_local_day", lambda: clock["day"])
    yield clock
    for entry_id in tuple(power._POWER_CACHE):
        power.forget_power_history(entry_id)
    data._DAY_CACHE.clear()


@pytest.mark.parametrize(("month", "day", "buckets"), [(3, 29, 92), (7, 1, 96), (10, 25, 100)])
def test_recorder_query_and_buckets_cover_exact_local_day(monkeypatch, month, day, buckets):
    from homeassistant.components.recorder import statistics
    from homeassistant.helpers import recorder

    start = datetime(2026, month, day, tzinfo=ZoneInfo("Europe/Berlin"))
    end = start + timedelta(days=1)
    calls = []

    def query(hass, since, until, ids, period, units, types):
        calls.append(1)
        assert since == start.astimezone(UTC) and until == end.astimezone(UTC)
        assert since.tzinfo is UTC and until.tzinfo is UTC
        assert (until - since).total_seconds() == buckets * 900
        assert ids == {"sensor.power"}
        assert period == "5minute" and units == {"power": "W"} and types == {"mean"}
        return {"sensor.power": rows(start, range(buckets * 3))}

    async def executor(function, *args):
        return function(*args)

    monkeypatch.setattr(statistics, "statistics_during_period", query)
    monkeypatch.setattr(recorder, "get_instance", lambda _hass: SimpleNamespace(async_add_executor_job=executor))
    result = asyncio.run(power._async_read_power_history(None, start, end, frozenset(SOURCES.power_entities)))
    assert calls == [1]
    assert result.buckets == buckets
    assert len(result.values["sensor.power"]) == buckets
    assert result.values["sensor.power"] == tuple(float(index * 3 + 1) for index in range(buckets))
    payload = power.power_history_payload(SOURCES, result, "en")
    assert payload["times"][0] == {"position": 0, "label": "00:00"}
    assert payload["times"][-1] == {"position": 1, "label": "24:00"}
    values = payload["series"][0]["values"]
    assert len(values) == buckets
    assert all(payload["axis"]["min"] <= value <= payload["axis"]["max"] for value in values)
    assert all(a < b for a, b in zip(values, values[1:], strict=False))


def test_incomplete_missing_and_duplicate_intervals_are_gaps():
    good = rows()
    readings = [
        *good, *rows(values=(3, 6), offset=900),
        *rows(values=(0, 0, 0), offset=1800),
        *rows(values=(1, 2, 3), offset=2700),
        *rows(values=(None, 2, 3), offset=3600),
        *rows(values=(float("nan"), 2, 3), offset=4500),
        *rows(values=(float("inf"), 2, 3), offset=5400),
        *rows(values=(True, 2, 3), offset=6300),
        {**good[0], "start": START.timestamp() - 300},
        {**good[0], "start": START.timestamp() + 1},
        {"mean": 99},
        *rows(offset=86400),
    ]
    readings.append(rows(values=(999,), offset=2700)[0])
    result = power.power_history_from_statistics(
        START, START + timedelta(days=1), frozenset({"sensor.power", "sensor.missing"}),
        {"sensor.power": readings, "sensor.unselected": good},
    )
    assert result.values["sensor.power"][:8] == (-300, None, 0, None, None, None, None, None)
    assert all(value is None for value in result.values["sensor.missing"])
    assert "sensor.unselected" not in result.values


@pytest.mark.parametrize("language", ["en", "de", "fr", "it", "unsupported"])
def test_presentation_shares_axis_preserves_signs_gaps_and_revision(language):
    sources = EnergySources(
        grid_from=SOURCES.grid_from, grid_power=SOURCES.grid_power,
        solar=(EnergyMeter("sensor.sun_energy"),), solar_power=("sensor.sun",),
        battery_from=(EnergyMeter("sensor.battery_energy"),), battery_power=("sensor.battery",),
    )
    raw = power.power_history_from_statistics(
        START, START + timedelta(days=1), frozenset(sources.power_entities), {
            "sensor.power": rows(values=(-1000,) * 3),
            "sensor.sun": rows(values=(3000,) * 3),
            "sensor.battery": rows(values=(-500,) * 3),
        },
    )
    result = power.power_history_payload(sources, raw, language)
    axis = result["axis"]
    assert axis["min"] <= -1000 and axis["max"] >= 3000 and axis["unit"] == "kW"
    series = {item["id"]: item for item in result["series"]}
    for key, watts in {"grid": -1000, "solar": 3000, "battery": -500, "home": 1500}.items():
        assert series[key]["values"][0] == watts
        assert all(value is None for value in series[key]["values"][1:])
        assert "points" not in series[key]
    labels = ENERGY_LABELS_BY_LANGUAGE.get(language, ENERGY_LABELS_BY_LANGUAGE["en"])
    assert result["label"] == labels["power_interval"]
    assert result["empty_text"] == labels["power_empty"]
    assert power.power_history_payload(sources, raw, language)["revision"] == result["revision"]
    assert power.power_history_payload(sources, raw, "other-language")["revision"] != result["revision"]
    raw.values["sensor.power"] = (0,) + raw.values["sensor.power"][1:]
    changed = power.power_history_payload(sources, raw, language)
    assert changed["revision"] != result["revision"]
    assert changed["series"][0]["values"][0] is not None


@pytest.mark.parametrize("missing", ["sensor.second", "unconfigured_grid", "unconfigured_solar"])
def test_unconfigured_power_is_zero_but_configured_missing_history_stays_unknown(missing):
    sources = EnergySources(
        grid_from=(*SOURCES.grid_from, EnergyMeter("sensor.grid_energy2")),
        grid_power=("sensor.power",) if missing == "unconfigured_grid" else ("sensor.power", "sensor.second"),
        solar=(EnergyMeter("sensor.sun_energy"), EnergyMeter("sensor.sun_energy2")),
        solar_power=("sensor.sun",) if missing == "unconfigured_solar" else ("sensor.sun", "sensor.sun2"),
    )
    readings = {entity_id: rows(values=(100,) * 3) for entity_id in sources.power_entities if entity_id != missing}
    raw = power.power_history_from_statistics(START, START + timedelta(days=1), frozenset(sources.power_entities), readings)
    series = {item["id"]: item for item in power.power_history_payload(sources, raw, "en")["series"]}
    if missing == "sensor.second":
        assert "grid" not in series and "home" not in series
    else:
        assert set(series) == {"grid", "solar", "home"}
        assert all(item["values"][0] is not None for item in series.values())
    for key, item in series.items():
        assert "partial" not in item
        assert item["label"] == ENERGY_LABELS_BY_LANGUAGE["en"][key]
        assert all(value is None for value in item["values"][1:])


def test_dots_only_mark_isolated_points_including_both_ends():
    raw = power.PowerHistory(START, START + timedelta(days=1), {
        "sensor.power": (0, None, 10, 20, None, -50) + (None,) * 89 + (0,),
    })
    result = power.power_history_payload(SOURCES, raw, "en")
    for series in result["series"]:
        points = series["values"]
        assert len(points) == 96
        assert series["dots"] == [0, 5, 95]
    tomorrow = power.PowerHistory(START + timedelta(days=1), START + timedelta(days=2), raw.values)
    assert power.power_history_payload(SOURCES, tomorrow, "en")["revision"] != result["revision"]


def test_recorder_converts_historical_units_to_requested_watts():
    from homeassistant.components.recorder.statistics import (
        _get_statistic_to_display_unit_converter,
    )

    converter = _get_statistic_to_display_unit_converter("power", "kW", "MW", {"power": "W"})
    assert converter(1.5) == 1500
    assert converter(-0.5) == -500
    assert converter(0) == 0
    assert converter(None) is None


def test_out_of_range_extremes_are_gaps_not_zero_and_empty_groups_are_omitted(monkeypatch):
    raw = power.PowerHistory(START, START + timedelta(days=1), {
        "sensor.power": (1e308, -1e308) + (None,) * 94,
    })
    result = power.power_history_payload(SOURCES, raw, "en")
    assert all(result["axis"]["min"] <= value <= result["axis"]["max"]
               for series in result["series"] for value in series["values"] if value is not None)
    monkeypatch.setattr(power, "chart_axis", lambda *_args: {"min": 0, "max": 1, "unit": "W", "ticks": []})
    # The negative net home's actual zero is valid; extreme grid values are not.
    result = power.power_history_payload(SOURCES, raw, "en")
    assert not any(series["id"] == "grid" for series in result["series"])
    assert result["series"][0]["values"][0] is None
    raw.values = {"sensor.power": (1e308,) + (None,) * 95}
    assert power.power_history_payload(SOURCES, raw, "en")["series"] == []


def test_shared_reads_survive_one_cancelled_caller_and_unload_cancels_delivery(monkeypatch):
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        async def read(*_args):
            started.set()
            await release.wait()
            return history()

        query = AsyncMock(side_effect=read)
        monkeypatch.setattr(power, "_async_read_power_history", query)
        first = asyncio.create_task(power.async_power_history(None, entry(), SOURCES))
        await started.wait()
        second = asyncio.create_task(power.async_power_history(None, entry(), SOURCES))
        await asyncio.sleep(0)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        release.set()
        assert (await second).values["sensor.power"][0] == 900
        assert query.await_count == 1
        power.forget_power_history("power-test")
        started.clear()
        release.clear()
        pending = asyncio.create_task(power.async_power_history(None, entry(), SOURCES))
        await started.wait()
        power.forget_power_history("power-test")
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert "power-test" not in power._POWER_CACHE

    asyncio.run(scenario())


def test_failure_backoff_keeps_only_same_day_same_sources(monkeypatch, cache_and_clock):
    query = AsyncMock(return_value=history())
    monkeypatch.setattr(power, "_async_read_power_history", query)

    async def scenario():
        first = await power.async_power_history(None, entry(), SOURCES)
        query.side_effect = RuntimeError("recorder busy")
        cache_and_clock["time"] += 299
        assert await power.async_power_history(None, entry(), SOURCES) is first
        assert query.await_count == 1
        cache_and_clock["time"] += 1
        assert await power.async_power_history(None, entry(), SOURCES) is first
        for _ in range(3):
            assert await power.async_power_history(None, entry(), SOURCES) is first
        assert query.await_count == 2
        cache_and_clock["day"] += timedelta(days=1)
        tomorrow = await power.async_power_history(None, entry(), SOURCES)
        assert tomorrow.values == {} and tomorrow.start == cache_and_clock["day"]
        assert query.await_count == 3
        other = EnergySources(grid_from=SOURCES.grid_from, grid_power=("sensor.other",))
        assert (await power.async_power_history(None, entry(), other)).values == {}
        assert query.await_count == 4

    asyncio.run(scenario())


@pytest.mark.parametrize(("views", "enabled"), [([], True), (["now"], True), (["power"], False)])
def test_disabled_history_never_queries(monkeypatch, views, enabled):
    query = AsyncMock()
    monkeypatch.setattr(power, "_async_read_power_history", query)
    assert asyncio.run(power.async_power_history(None, entry(views, enabled), SOURCES)) is None
    assert not power._POWER_CACHE
    query.assert_not_awaited()


def test_missing_power_sensors_return_localized_empty_history_without_query(monkeypatch):
    query = AsyncMock()
    monkeypatch.setattr(power, "_async_read_power_history", query)
    sources = EnergySources(grid_from=SOURCES.grid_from)
    raw = asyncio.run(power.async_power_history(None, entry(), sources))
    result = power.power_history_payload(sources, raw, "de")
    assert result["empty_text"] == ENERGY_LABELS_BY_LANGUAGE["de"]["power_empty"]
    assert all(value is None for series in result["series"] for value in series["values"])
    assert result["series"] == []
    query.assert_not_awaited()


def test_power_only_data_path_skips_energy_and_live_reads(monkeypatch):
    monkeypatch.setattr(data, "async_configured_energy_sources", AsyncMock(return_value=SOURCES))
    day = AsyncMock(return_value=EnergyDay())
    monkeypatch.setattr(data, "_async_energy_day", day)
    query = AsyncMock(return_value=history())
    monkeypatch.setattr(power, "_async_read_power_history", query)
    states = Mock(side_effect=AssertionError("unexpected live state read"))
    hass = SimpleNamespace(config=SimpleNamespace(currency="EUR"), states=SimpleNamespace(get=states))

    async def scenario():
        first = await data.async_energy_dashboard_page(hass, entry(), "en")
        second = await data.async_energy_dashboard_page(hass, entry(), "en")
        assert first["energy"]["power"] == second["energy"]["power"]
        assert [view["id"] for view in first["energy"]["views"]] == ["power"]
        assert query.await_count == 1

    asyncio.run(scenario())
    day.assert_not_awaited()
    states.assert_not_called()


@pytest.mark.parametrize("views", [[], ["power"], ["today"], ["now"], ["now", "power"]])
def test_updates_add_no_timer_and_listen_to_live_power_only_for_now(monkeypatch, views):
    from homeassistant.helpers import event

    source_read = AsyncMock(return_value=SOURCES)
    monkeypatch.setattr(updates, "async_configured_energy_sources", source_read)
    state = Mock(return_value=lambda: None)
    tick = Mock(return_value=lambda: None)
    monkeypatch.setattr(event, "async_track_state_change_event", state)
    monkeypatch.setattr(event, "async_track_time_interval", tick)

    async def scenario():
        tracker = updates.EnergyPageUpdates(None, entry(views), lambda: None)
        assert await tracker.async_start() is bool(views)
        if views:
            tick.assert_called_once()
            assert tick.call_args.args[2].total_seconds() == 300
            await tracker._async_tick()
        else:
            source_read.assert_not_awaited()
            tick.assert_not_called()
        assert state.call_count == int("now" in views)
        monkeypatch.setattr(power, "_async_read_power_history", AsyncMock(return_value=history()))
        if "power" in views:
            await power.async_power_history(None, entry(views), SOURCES)
            assert power._POWER_CACHE
        tracker.stop()
        assert not power._POWER_CACHE

    asyncio.run(scenario())


def test_empty_views_skip_source_manager_and_all_data_reads(monkeypatch):
    from homeassistant.components.energy import data as energy_data

    manager = AsyncMock()
    monkeypatch.setattr(energy_data, "async_get_manager", manager)
    hass = SimpleNamespace(config=SimpleNamespace(components={"energy"}))
    assert asyncio.run(data.async_configured_energy_sources(hass, entry([]))) == EnergySources()
    assert asyncio.run(data.async_energy_dashboard_page(hass, entry([]), "en")) is None
    manager.assert_not_awaited()


@pytest.mark.parametrize("alternating_gaps", [False, True])
def test_maximum_day_four_curves_fit_payload_budget(alternating_gaps):
    start = datetime(2026, 10, 25, tzinfo=ZoneInfo("Europe/Berlin"))
    sources = EnergySources(
        grid_from=SOURCES.grid_from, grid_power=SOURCES.grid_power,
        solar=(EnergyMeter("sensor.sun_energy"),), solar_power=("sensor.sun",),
        battery_from=(EnergyMeter("sensor.battery_energy"),), battery_power=("sensor.battery",),
    )
    raw = power.PowerHistory(start, start + timedelta(days=1), {
        "sensor.power": tuple(index * 31.234 - 1234 for index in range(100)),
        "sensor.sun": tuple(index * 71.234 for index in range(100)),
        "sensor.battery": tuple(index * 21.234 - 1234 for index in range(100)),
    })
    if alternating_gaps:
        raw.values = {key: tuple(value if index % 2 == 0 else None for index, value in enumerate(values))
                      for key, values in raw.values.items()}
    result = power.power_history_payload(sources, raw, "de")
    assert len(result["series"]) == 4
    assert all(series["dots"] == (list(range(0, 100, 2)) if alternating_gaps else [])
               for series in result["series"])
    assert all(len(series["values"]) == 100 for series in result["series"])
    assert result["time"]["count"] == 100
    assert len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()) < 30 * 1024


@pytest.mark.parametrize(("month", "day", "count", "before", "after"), [
    (3, 29, 92, "2026-03-29 01:45 UTC+0100", "2026-03-29 03:00 UTC+0200"),
    (10, 25, 100, "2026-10-25 02:45 UTC+0200", "2026-10-25 02:00 UTC+0100"),
])
def test_inspection_timestamps_follow_elapsed_buckets_across_dst(month, day, count, before, after):
    start = datetime(2026, month, day, tzinfo=ZoneInfo("Europe/Berlin"))
    raw = power.PowerHistory(start, start + timedelta(days=1), {"sensor.power": (1.23456789,) * count})
    result = power.power_history_payload(SOURCES, raw, "en")
    time = result["time"]
    stamps = []
    for index in range(time["count"]):
        offset = next(value for begin, value in reversed(time["offsets"]) if begin <= index)
        local = datetime.fromtimestamp(time["start"] + index * time["step"], UTC)
        stamps.append(local.astimezone(timezone(timedelta(seconds=offset))).strftime("%Y-%m-%d %H:%M UTC%z"))
    index = stamps.index(before)
    assert stamps[index + 1] == after
    assert len(stamps) == len(set(stamps)) == count
    assert stamps[-1].startswith(f"2026-{month:02d}-{day:02d} 23:45")
    assert result["series"][0]["values"] == [1.23456789] * count


@pytest.mark.parametrize("target", [["now"], ["today"], ["balance"], ["power"], [], None])
def test_view_subset_transitions_discard_only_inactive_cache_without_queries(monkeypatch, target):
    source_read = AsyncMock(return_value=SOURCES)
    day_read = AsyncMock(return_value=EnergyDay(hours={"sensor.energy": [1.0] * 24}))
    history_read = AsyncMock(return_value=history())
    monkeypatch.setattr(data, "async_configured_energy_sources", source_read)
    monkeypatch.setattr(data, "_async_read_energy_day", day_read)
    monkeypatch.setattr(power, "_async_read_power_history", history_read)
    states = Mock(return_value=SimpleNamespace(state="500", attributes={"unit_of_measurement": "W"}))
    hass = SimpleNamespace(config=SimpleNamespace(currency="EUR"), states=SimpleNamespace(get=states))
    config = entry(["now", "today", "balance", "power"])

    async def scenario():
        initial = await data.async_energy_dashboard_page(hass, config, "en")
        day_cache, power_cache = data._DAY_CACHE[config.entry_id], power._POWER_CACHE[config.entry_id]
        states.return_value.state = "1000"
        live = await data.async_energy_dashboard_page(hass, config, "en")
        assert live["energy"]["power"]["revision"] == initial["energy"]["power"]["revision"]
        states.reset_mock()
        source_read.reset_mock()
        if target is None:
            config.options["energy_page"]["enabled"] = False
        else:
            config.options["energy_page"]["views"] = target
        result = await data.async_energy_dashboard_page(hass, config, "en")
        if not target:
            assert result is None
            source_read.assert_not_awaited()
        else:
            assert [view["id"] for view in result["energy"]["views"]] == target
        if target == ["power"]:
            assert power._POWER_CACHE[config.entry_id] is power_cache
            assert config.entry_id not in data._DAY_CACHE
        elif target:
            assert data._DAY_CACHE[config.entry_id] is day_cache
            assert config.entry_id not in power._POWER_CACHE
        else:
            assert config.entry_id not in data._DAY_CACHE and config.entry_id not in power._POWER_CACHE
        assert states.call_count == int(target == ["now"])
        assert day_read.await_count == history_read.await_count == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("target", [["today"], ["balance"], ["power"], [], None])
def test_tracker_guards_remove_inactive_live_work_and_stop_all_off(monkeypatch, target):
    from homeassistant.helpers import event

    sources = AsyncMock(return_value=SOURCES)
    monkeypatch.setattr(updates, "async_configured_energy_sources", sources)
    unsub_state, unsub_tick, unsub_delayed, notify = Mock(), Mock(), Mock(), Mock()
    state = Mock(return_value=unsub_state)
    tick = Mock(return_value=unsub_tick)
    delayed = Mock(return_value=unsub_delayed)
    monkeypatch.setattr(event, "async_track_state_change_event", state)
    monkeypatch.setattr(event, "async_track_time_interval", tick)
    monkeypatch.setattr(event, "async_call_later", delayed)
    config = entry(["now", "power"])

    async def scenario():
        tracker = updates.EnergyPageUpdates(None, config, notify)
        assert await tracker.async_start()
        tracker._last_notify = updates.monotonic()
        tracker._handle_power_change(SimpleNamespace(data={}))
        delayed.assert_called_once()
        sources.reset_mock()
        if target is None:
            config.options["energy_page"]["enabled"] = False
        else:
            config.options["energy_page"]["views"] = target
        await tracker._async_tick()
        unsub_state.assert_called_once()
        unsub_delayed.assert_called_once()
        assert tracker._unsub_power is None and tracker._unsub_delayed is None
        if target:
            sources.assert_awaited_once()
            unsub_tick.assert_not_called()
            notify.assert_called_once()
        else:
            sources.assert_not_awaited()
            unsub_tick.assert_called_once()
            notify.assert_not_called()
        notify.reset_mock()
        tracker._handle_power_change(SimpleNamespace(data={}))
        tracker._handle_delayed()
        notify.assert_not_called()
        assert delayed.call_count == 1
        tracker.stop()
        tracker.stop()
        unsub_tick.assert_called_once()
        sources.reset_mock()
        await tracker._async_tick()
        sources.assert_not_awaited()

    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["sources", "day"])
def test_disable_during_read_does_not_start_inactive_reads_or_retain_cache(monkeypatch, stage):
    config = entry(["now", "power"])

    async def disable(result):
        config.options["energy_page"]["views"] = []
        return result

    source_read = AsyncMock(return_value=SOURCES)
    day_read = AsyncMock(return_value=EnergyDay())
    if stage == "sources":
        async def read_sources(*_args):
            return await disable(SOURCES)

        source_read.side_effect = read_sources
    else:
        async def read_day(*_args):
            return await disable(EnergyDay())

        day_read.side_effect = read_day
    history_read = AsyncMock()
    monkeypatch.setattr(data, "async_configured_energy_sources", source_read)
    monkeypatch.setattr(data, "_async_read_energy_day", day_read)
    monkeypatch.setattr(power, "_async_read_power_history", history_read)
    assert asyncio.run(data.async_energy_dashboard_page(None, config, "en")) is None
    assert not data._DAY_CACHE and not power._POWER_CACHE
    history_read.assert_not_awaited()
    assert day_read.await_count == int(stage == "day")


def test_disable_cancels_inflight_history_without_reinserting_cache(monkeypatch):
    async def scenario():
        started = asyncio.Event()

        async def read(*_args):
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(power, "_async_read_power_history", read)
        config = entry()
        pending = asyncio.create_task(power.async_power_history(None, config, SOURCES))
        await started.wait()
        config.options["energy_page"]["views"] = []
        assert await data.async_energy_dashboard_page(None, config, "en") is None
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert not power._POWER_CACHE

    asyncio.run(scenario())


def test_reload_old_tracker_cannot_clear_new_cache_or_recreate_work(monkeypatch):
    from homeassistant.helpers import event

    monkeypatch.setattr(event, "async_track_time_interval", Mock(return_value=Mock()))
    monkeypatch.setattr(power, "_async_read_power_history", AsyncMock(return_value=history()))
    config = entry()
    source_read = AsyncMock(return_value=SOURCES)
    monkeypatch.setattr(updates, "async_configured_energy_sources", source_read)

    async def scenario():
        old = updates.EnergyPageUpdates(None, config, Mock())
        assert await old.async_start()
        started, release = asyncio.Event(), asyncio.Event()

        async def read(*_args):
            started.set()
            await release.wait()
            return SOURCES

        source_read.side_effect = read
        pending = asyncio.create_task(old._async_tick())
        await started.wait()
        old.stop()
        source_read.side_effect = None
        new = updates.EnergyPageUpdates(None, config, Mock())
        assert await new.async_start()
        await power.async_power_history(None, config, SOURCES)
        cached = power._POWER_CACHE[config.entry_id]
        old.stop()
        release.set()
        await pending
        assert power._POWER_CACHE[config.entry_id] is cached
        old._notify.assert_not_called()
        old._handle_delayed()
        assert not await old.async_start()
        assert power._POWER_CACHE[config.entry_id] is cached
        new.stop()
        assert not power._POWER_CACHE

    asyncio.run(scenario())


@pytest.mark.parametrize("reload", [False, True])
def test_runtime_unload_during_day_read_prevents_followup_power_read(monkeypatch, reload):
    from custom_components.bticino_c300x.data import C300XRuntimeResources

    config = entry(["now", "power"])
    tracker = updates.EnergyPageUpdates(None, config, Mock())
    resources = C300XRuntimeResources(unregister_display_bridge_updates=tracker.stop)
    config.runtime_data = SimpleNamespace(resources=resources)

    async def read(*_args):
        resources.close()
        if reload:
            config.runtime_data = SimpleNamespace(resources=C300XRuntimeResources())
        return EnergyDay()

    monkeypatch.setattr(data, "async_configured_energy_sources", AsyncMock(return_value=SOURCES))
    monkeypatch.setattr(data, "_async_read_energy_day", read)
    history_read = AsyncMock()
    monkeypatch.setattr(power, "_async_read_power_history", history_read)
    assert asyncio.run(data.async_energy_dashboard_page(None, config, "en")) is None
    history_read.assert_not_awaited()
    assert not data._DAY_CACHE and not power._POWER_CACHE


@pytest.mark.parametrize("views", [["now"], ["now", "power"], ["today"], ["balance"]])
def test_only_cost_consuming_views_request_cost_statistics(monkeypatch, views):
    sources = EnergySources(
        grid_from=(EnergyMeter("sensor.energy", "sensor.cost"),),
        grid_to=(EnergyMeter("sensor.export", "sensor.compensation"),),
    )
    monkeypatch.setattr(data, "async_configured_energy_sources", AsyncMock(return_value=sources))
    read = AsyncMock(return_value=EnergyDay())
    monkeypatch.setattr(data, "_async_read_energy_day", read)
    hass = SimpleNamespace(config=SimpleNamespace(currency="EUR"))
    assert asyncio.run(data.async_energy_dashboard_page(hass, entry(views), "en")) is not None
    queried = read.call_args.args[2]
    assert queried.energy_stats == sources.energy_stats
    assert queried.cost_stats == (sources.cost_stats if "now" not in views else set())
    assert sources.cost_stats == {"sensor.cost", "sensor.compensation"}
