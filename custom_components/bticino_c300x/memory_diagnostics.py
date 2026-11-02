"""Debug-gated periodic memory diagnostics to localize slow runtime leaks.

When the integration logger is at DEBUG level, this logs a compact snapshot
every few minutes: process RSS, asyncio task counts, and the Python object
types whose instance count grew since the previous snapshot. The type that
keeps climbing points straight at a leak.

It is scheduled only when DEBUG is enabled at entry setup (so enable debug
logging and reload the entry to activate it), has zero footprint otherwise,
and stops collecting when DEBUG is disabled. Entries share one timer, cancelled
when its last entry unloads. The object census runs in the executor.
"""

from __future__ import annotations

import asyncio
import gc
import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .entry_types import BticinoC300XConfigEntry

_LOGGER = logging.getLogger(__name__)
_SNAPSHOT_INTERVAL = timedelta(minutes=5)
_TOP_TYPES = 12
_GROWTH_MIN = 500
_DATA_KEY = "memory_diagnostics"


@dataclass
class _DiagnosticsState:
    entries: int = 0
    collecting: bool = False
    previous: Counter[str] | None = None
    unsubscribe: Callable[[], None] | None = None


def _process_rss_bytes() -> int | None:
    """Return the current process resident memory in bytes, or None."""

    try:
        with open("/proc/self/status", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except OSError, ValueError, IndexError:
        return None
    return None


def _collect_object_census() -> tuple[int | None, int, Counter[str]]:
    """Return (rss_bytes, object_count, per-type instance counts). Runs in executor."""

    rss = _process_rss_bytes()
    objects = gc.get_objects()
    counts: Counter[str] = Counter(type(obj).__name__ for obj in objects)
    return rss, len(objects), counts


def _format_growth(previous: Counter[str] | None, current: Counter[str]) -> str:
    """Return a compact 'growth[Type+N, ...]' string for types that climbed."""

    if previous is None:
        return ""
    climbing = [
        f"{name}+{current[name] - previous.get(name, 0)}"
        for name, _count in current.most_common(60)
        if current[name] - previous.get(name, 0) >= _GROWTH_MIN
    ]
    return " growth[" + ", ".join(climbing) + "]" if climbing else ""


def async_start_memory_diagnostics(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
) -> None:
    """Start debug-gated periodic memory snapshots (no-op unless DEBUG is on)."""

    if not _LOGGER.isEnabledFor(logging.DEBUG):
        return

    from homeassistant.helpers.event import async_track_time_interval

    domain_data = hass.data.setdefault(DOMAIN, {})
    state = domain_data.get(_DATA_KEY)
    first = state is None
    if first:
        state = _DiagnosticsState()
        domain_data[_DATA_KEY] = state
    state.entries += 1

    def _unload() -> None:
        state.entries -= 1
        if not state.entries:
            if state.unsubscribe is not None:
                state.unsubscribe()
            domain_data.pop(_DATA_KEY, None)

    entry.async_on_unload(_unload)
    if not first:
        return

    async def _log_snapshot(_now: Any = None) -> None:
        if (
            not state.entries
            or state.collecting
            or not _LOGGER.isEnabledFor(logging.DEBUG)
        ):
            return
        state.collecting = True
        try:
            rss, object_count, counts = await hass.async_add_executor_job(
                _collect_object_census
            )
        finally:
            state.collecting = False
        if not state.entries or not _LOGGER.isEnabledFor(logging.DEBUG):
            return
        try:
            tasks = asyncio.all_tasks()
        except RuntimeError:
            tasks = set()
        bticino_tasks = sum(1 for task in tasks if "bticino" in (task.get_name() or ""))
        growth = _format_growth(state.previous, counts)
        state.previous = counts
        _LOGGER.debug(
            "C300X memdiag: rss=%s tasks=%d(bticino=%d) gc_objects=%d top[%s]%s",
            f"{rss / 1_000_000:.0f}MB" if rss is not None else "n/a",
            len(tasks),
            bticino_tasks,
            object_count,
            ", ".join(
                f"{name}:{count}" for name, count in counts.most_common(_TOP_TYPES)
            ),
            growth,
        )

    state.unsubscribe = async_track_time_interval(
        hass, _log_snapshot, _SNAPSHOT_INTERVAL
    )
    _LOGGER.info(
        "C300X memory diagnostics active: snapshot every %d min (disable by "
        "lowering the log level)",
        int(_SNAPSHOT_INTERVAL.total_seconds() // 60),
    )
    hass.async_create_task(_log_snapshot())
