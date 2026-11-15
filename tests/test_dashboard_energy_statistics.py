"""Exercise the production recorder adapter, not just pre-assembled day values."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from custom_components.bticino_c300x import dashboard_energy_data
from custom_components.bticino_c300x.dashboard_energy import EnergyMeter, EnergySources


def test_short_term_reads_cover_each_meters_own_hourly_boundary(monkeypatch):
    from homeassistant.components import recorder
    from homeassistant.components.recorder import statistics

    start = datetime(2026, 11, 15, tzinfo=UTC)
    stamp = start.timestamp()
    sources = EnergySources(
        grid_from=(EnergyMeter("sensor.grid"),),
        solar=(EnergyMeter("sensor.solar"),),
    )
    calls = []
    hourly = {
        "sensor.grid": [{"start": stamp, "end": stamp + 3600, "change": 2.0}],
    }
    recent = {
        "sensor.grid": [
            {"start": stamp + 3300, "end": stamp + 3600, "change": 0.2},
            {"start": stamp + 3600, "end": stamp + 3900, "change": 0.3},
        ],
        "sensor.solar": [
            {"start": stamp + 3300, "end": stamp + 3600, "change": 0.4},
            {"start": stamp + 3600, "end": stamp + 3900, "change": 0.5},
        ],
    }

    def read(_hass, since, until, ids, period, units, types):
        calls.append((since, period))
        assert ids == sources.energy_stats
        assert until is None and units == {"energy": "kWh"} and types == {"change"}
        rows = hourly if period == "hour" else recent
        return {key: [row for row in values if row["start"] >= since.timestamp()]
                for key, values in rows.items()}

    async def executor(function, *args):
        return function(*args)

    monkeypatch.setattr(statistics, "statistics_during_period", read)
    monkeypatch.setattr(recorder, "get_instance", lambda _hass: SimpleNamespace(
        async_add_executor_job=executor,
    ))
    day = asyncio.run(dashboard_energy_data._async_read_energy_day(None, start, sources))

    assert day.total(sources.grid_from[0]) == 2.3
    assert day.total(sources.solar[0]) == 0.9
    assert len(calls) == 2
    assert calls[1][0] <= start + timedelta(minutes=55)
