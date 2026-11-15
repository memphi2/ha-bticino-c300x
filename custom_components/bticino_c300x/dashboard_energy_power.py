"""Bounded, on-demand power history from HA recorder, never device polling."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from time import monotonic
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .dashboard_config import configured_energy_page
from .dashboard_controls import finite_number
from .dashboard_energy import (
    COLOR_BATTERY,
    COLOR_GRID,
    COLOR_HOME,
    COLOR_SOLAR,
    ENERGY_VIEW_POWER,
    EnergySources,
    source_power_watts,
)
from .dashboard_energy_charts import chart_axis
from .dashboard_labels import ENERGY_LABELS_BY_LANGUAGE
from .entry_types import BticinoC300XConfigEntry

POWER_HISTORY_MAX_AGE_SECONDS = 300.0
POWER_HISTORY_BUCKET_SECONDS = 900
POWER_HISTORY_MAX_BUCKETS = 100
_STATISTIC_SECONDS = 300
_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PowerHistory:
    """Local day bounds and complete quarter-hour sensor means, in watts."""

    start: datetime
    end: datetime
    values: dict[str, tuple[float | None, ...]] = field(default_factory=dict)

    @property
    def buckets(self) -> int:
        return min(POWER_HISTORY_MAX_BUCKETS, int(
            (self.end.timestamp() - self.start.timestamp()) / POWER_HISTORY_BUCKET_SECONDS
        ))


@dataclass(slots=True)
class _PowerCache:
    key: tuple[datetime, datetime, frozenset[str]]
    history: PowerHistory
    read_at: float = float("-inf")
    task: asyncio.Task[PowerHistory] | None = None


_POWER_CACHE: dict[str, _PowerCache] = {}


def forget_power_history(entry_id: str) -> None:
    """Cancel pending delivery and release an unloaded entry's cached day."""

    cached = _POWER_CACHE.pop(entry_id, None)
    if cached is not None and cached.task is not None:
        cached.task.cancel()


async def async_power_history(
    hass: HomeAssistant, entry: BticinoC300XConfigEntry, sources: EnergySources,
) -> PowerHistory | None:
    """Coalesce requests and failures for five minutes, only for a selected view."""

    settings = configured_energy_page(entry)
    runtime = getattr(entry, "runtime_data", None)
    if not settings["enabled"] or ENERGY_VIEW_POWER not in settings["views"]:
        forget_power_history(entry.entry_id)
        return None
    start = dt_util.start_of_local_day()
    end = start + timedelta(days=1)
    ids = frozenset(sources.power_entities)
    if not ids:
        forget_power_history(entry.entry_id)
        return PowerHistory(start, end)
    key = (start, end, ids)
    cached = _POWER_CACHE.get(entry.entry_id)
    if cached is None or cached.key != key:
        forget_power_history(entry.entry_id)
        cached = _PowerCache(key, PowerHistory(start, end))
        _POWER_CACHE[entry.entry_id] = cached

    def can_read() -> bool:
        current = configured_energy_page(entry)
        valid = (
            _POWER_CACHE.get(entry.entry_id) is cached
            and getattr(entry, "runtime_data", None) is runtime
            and not getattr(getattr(runtime, "resources", None), "closed", False)
            and current["enabled"] and ENERGY_VIEW_POWER in current["views"]
        )
        if not valid and _POWER_CACHE.get(entry.entry_id) is cached:
            # Do not cancel this task itself or evict a replacement runtime's cache.
            _POWER_CACHE.pop(entry.entry_id)
        return valid

    if cached.task is None and monotonic() - cached.read_at >= POWER_HISTORY_MAX_AGE_SECONDS:
        cached.task = asyncio.create_task(_async_read_and_cache(hass, cached, can_read))
    if cached.task is not None:
        # A cancelled HTTP request must not cancel the other request's read.
        return await asyncio.shield(cached.task)
    return cached.history


async def _async_read_and_cache(
    hass: HomeAssistant, cached: _PowerCache, can_read: Callable[[], bool],
) -> PowerHistory:
    try:
        if not can_read():
            return cached.history
        history = await _async_read_power_history(hass, *cached.key)
        if can_read():
            cached.history = history
    except Exception:  # noqa: BLE001 - keep same-day data and back off on recorder failure
        _LOGGER.debug("Power history could not be read", exc_info=True)
    finally:
        can_read()
        cached.read_at = monotonic()
        cached.task = None
    # The cache object may have been removed during the read; never reinsert it.
    return cached.history


async def _async_read_power_history(
    hass: HomeAssistant, start: datetime, end: datetime, statistic_ids: frozenset[str],
) -> PowerHistory:
    from homeassistant.components.recorder.statistics import statistics_during_period
    from homeassistant.helpers.recorder import get_instance

    result = await get_instance(hass).async_add_executor_job(
        statistics_during_period, hass, dt_util.as_utc(start), dt_util.as_utc(end),
        set(statistic_ids), "5minute", {"power": "W"}, {"mean"},
    )
    return power_history_from_statistics(start, end, statistic_ids, result)


def power_history_from_statistics(
    start: datetime, end: datetime, statistic_ids: frozenset[str],
    result: Mapping[str, Sequence[Mapping[str, Any]]],
) -> PowerHistory:
    """Keep gaps explicit; never average a partial bucket as a full interval."""

    history = PowerHistory(start, end)
    since = start.timestamp()
    slots = history.buckets * 3
    for statistic_id in statistic_ids:
        samples: dict[int, float | None] = {}
        for row in result.get(statistic_id, ()):
            stamp, until = finite_number(row.get("start")), finite_number(row.get("end"))
            if stamp is None or until is None:
                continue
            offset = (stamp - since) / _STATISTIC_SECONDS
            if not offset.is_integer() or not 0 <= offset < slots or until != stamp + _STATISTIC_SECONDS:
                continue
            slot = int(offset)
            value = finite_number(row.get("mean"))
            # Unexpected duplicate intervals are ambiguous, not extra samples.
            samples[slot] = value if slot not in samples else None
        buckets: list[float | None] = []
        for slot in range(0, slots, 3):
            values = [samples.get(slot + index) for index in range(3)]
            known = [value for value in values if value is not None]
            buckets.append(sum(value / 3 for value in known) if len(known) == 3 else None)
        history.values[statistic_id] = tuple(buckets)
    return history


def power_history_payload(
    sources: EnergySources, history: PowerHistory, language: str,
) -> dict[str, Any]:
    """Prepare bounded coordinates, shared scales and labels for the display."""

    labels = ENERGY_LABELS_BY_LANGUAGE.get(language, ENERGY_LABELS_BY_LANGUAGE["en"])
    groups: dict[str, list[float | None]] = {
        key: [] for key in source_power_watts(sources, {})
    }
    entities = sources.power_entities
    for index in range(history.buckets):
        power = {
            entity_id: values[index] if index < len(values) else None
            for entity_id, values in history.values.items()
        }
        # Zero for unconfigured power is a policy, not a recorded observation.
        # Without any configured sample, gaps and future buckets stay empty.
        group_power = (
            source_power_watts(sources, power)
            if any(finite_number(power.get(entity)) is not None for entity in entities)
            else dict.fromkeys(groups)
        )
        for key, value in group_power.items():
            groups[key].append(finite_number(value))
    known = [value for values in groups.values() for value in values if value is not None]
    axis = chart_axis(min(known, default=0), max(known, default=0), language, "W")
    span = axis["max"] - axis["min"]
    colors = {"grid": COLOR_GRID, "solar": COLOR_SOLAR, "battery": COLOR_BATTERY, "home": COLOR_HOME}
    since = history.start.timestamp()
    duration = history.end.timestamp() - since
    times = [history.start + timedelta(hours=hour) for hour in (0, 6, 12, 18, 24)]
    series: list[dict[str, Any]] = []
    for key, values in groups.items():
        points: list[float | None] = []
        for value in values:
            y = None
            if (value is not None and axis["min"] <= value <= axis["max"]
                    and finite_number(span) is not None and span > 0):
                y = finite_number((value - axis["min"]) / span)
            points.append(None if y is None or not 0 <= y <= 1 else round(y, 5))
        if not any(point is not None for point in points):
            continue
        series.append({
            "id": key,
            "label": labels[key],
            "color": colors[key], "points": points,
            "dots": [index for index, point in enumerate(points)
                     if point is not None
                     and (index == 0 or points[index - 1] is None)
                     and (index == len(points) - 1 or points[index + 1] is None)],
        })
    payload: dict[str, Any] = {
        "axis": axis,
        "times": [{"position": round((time.timestamp() - since) / duration, 6),
                   "label": "24:00" if time == history.end else time.strftime("%H:%M")}
                  for time in times],
        "series": series,
        "label": labels["power_interval"], "empty_text": labels["power_empty"],
    }
    payload["revision"] = hashlib.sha256(json.dumps(
        [history.start.isoformat(), history.end.isoformat(), language, payload],
        sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()[:16]
    return payload
