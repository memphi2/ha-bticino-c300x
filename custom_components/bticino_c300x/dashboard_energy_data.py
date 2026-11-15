"""Reads today's energy figures from Home Assistant for the display page.

The meter values come from the recorder's statistics, as they do for Home
Assistant's own Energy dashboard. Statistics change every five minutes at
most, so one read is kept for that long: the display asks for its pages on
every event, and each ask must not cost a database query. The power values
are plain entity states and always current.
"""

from __future__ import annotations

import logging
from time import monotonic
from typing import Any

from homeassistant.core import HomeAssistant

from .dashboard_config import configured_energy_page
from .dashboard_energy import (
    EnergyDay,
    EnergySources,
    energy_page,
    energy_sources,
    power_watts,
)
from .entry_types import BticinoC300XConfigEntry

_LOGGER = logging.getLogger(__name__)

ENERGY_STATISTICS_MAX_AGE_SECONDS = 300.0
_CURRENCY_SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF"}

# entry id -> (read at, local day, statistic ids, day)
_DAY_CACHE: dict[str, tuple[float, str, frozenset[str], EnergyDay]] = {}


def forget_energy_day(entry_id: str) -> None:
    """Drop the kept statistics of an entry that is unloaded."""

    _DAY_CACHE.pop(entry_id, None)


async def async_configured_energy_sources(
    hass: HomeAssistant, entry: BticinoC300XConfigEntry,
) -> EnergySources:
    """Return the sources of the energy page, none while the page is off."""

    if not configured_energy_page(entry)["enabled"]:
        return EnergySources()
    if "energy" not in getattr(getattr(hass, "config", None), "components", ()):
        return EnergySources()
    try:
        from homeassistant.components.energy.data import async_get_manager

        manager = await async_get_manager(hass)
    except Exception:  # noqa: BLE001 - the display works without the page
        _LOGGER.debug("Home Assistant's Energy setup could not be read", exc_info=True)
        return EnergySources()
    energy_data = hass.data.get("energy")
    cost_sensors = energy_data.get("cost_sensors") if isinstance(energy_data, dict) else None
    return energy_sources(manager.data, cost_sensors)


async def async_energy_dashboard_page(
    hass: HomeAssistant, entry: BticinoC300XConfigEntry, language: str,
) -> dict[str, Any] | None:
    """Return the energy page of the display, or None when there is none."""

    sources = await async_configured_energy_sources(hass, entry)
    if not sources.any:
        return None
    day = await _async_energy_day(hass, entry.entry_id, sources)
    power = {
        entity_id: power_watts(hass.states.get(entity_id))
        for entity_id in sources.power_entities
    }
    currency = str(getattr(hass.config, "currency", "") or "")
    return energy_page(
        sources, day, power,
        language=language,
        views=configured_energy_page(entry)["views"],
        currency=_CURRENCY_SYMBOLS.get(currency, currency),
    )


async def _async_energy_day(
    hass: HomeAssistant, entry_id: str, sources: EnergySources,
) -> EnergyDay:
    from homeassistant.util import dt as dt_util

    start = dt_util.start_of_local_day()
    statistic_ids = frozenset(sources.energy_stats | sources.cost_stats)
    cached = _DAY_CACHE.get(entry_id)
    now = monotonic()
    if (
        cached is not None
        and now - cached[0] < ENERGY_STATISTICS_MAX_AGE_SECONDS
        and cached[1] == start.isoformat()
        and cached[2] == statistic_ids
    ):
        return cached[3]
    try:
        day = await _async_read_energy_day(hass, start, sources)
    except Exception:  # noqa: BLE001 - the display works without fresh figures
        _LOGGER.debug("Energy statistics could not be read", exc_info=True)
        # Yesterday's figures are not shown as today's.
        if cached is not None and cached[1] == start.isoformat() and cached[2] == statistic_ids:
            return cached[3]
        return EnergyDay()
    _DAY_CACHE[entry_id] = (now, start.isoformat(), statistic_ids, day)
    return day


async def _async_read_energy_day(
    hass: HomeAssistant, start: Any, sources: EnergySources,
) -> EnergyDay:
    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.statistics import statistics_during_period
    from homeassistant.util import dt as dt_util

    statistic_ids = sources.energy_stats | sources.cost_stats
    recorder = get_instance(hass)

    async def read(since: Any, period: str) -> dict[str, list[dict[str, Any]]]:
        return await recorder.async_add_executor_job(  # type: ignore[no-any-return]
            statistics_during_period,
            hass, since, None, statistic_ids, period, {"energy": "kWh"}, {"change"},
        )

    hourly = await read(start, "hour")
    # The running hour has no hourly statistic yet; its five-minute ones
    # bring the figures up to date.
    covered = max(
        (float(row["end"]) for rows in hourly.values() for row in rows if row.get("end") is not None),
        default=start.timestamp(),
    )
    recent = await read(dt_util.utc_from_timestamp(covered), "5minute")
    return energy_day_from_statistics(
        sources, (hourly, recent),
        lambda timestamp: dt_util.as_local(dt_util.utc_from_timestamp(timestamp)).hour,
    )


def energy_day_from_statistics(
    sources: EnergySources,
    results: tuple[dict[str, list[dict[str, Any]]], ...],
    local_hour: Any,
) -> EnergyDay:
    """Sort the changes of each statistic into the local hours of the day."""

    costs = sources.cost_stats
    day = EnergyDay()
    for result in results:
        for statistic_id, rows in result.items():
            for row in rows:
                change = row.get("change")
                if change is None or row.get("start") is None:
                    continue
                if statistic_id in costs:
                    day.costs[statistic_id] = day.costs.get(statistic_id, 0.0) + float(change)
                    continue
                hours = day.hours.setdefault(statistic_id, [0.0] * 24)
                hours[int(local_hour(float(row["start"]))) % 24] += float(change)
    return day
