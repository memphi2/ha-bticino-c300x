"""One ordered snapshot cache for HTTP responses and device metric events."""

from __future__ import annotations

from asyncio import Task, create_task, shield
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import monotonic
from typing import TYPE_CHECKING, Any, cast

from .api_errors import C300XAgentApiError
from .const import SIGNAL_SYSTEM_METRICS_CHANGED

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .entry_types import BticinoC300XConfigEntry


@dataclass(slots=True)
class SystemMetricsCache:
    """Ordering, connection generation and a single non-polling expiry timer."""

    generation: int = 0
    needs_refresh: bool = False
    expires_at: float | None = None
    cancel_expiry: Callable[[], None] | None = None
    refresh_task: Task[dict[str, Any]] | None = None
    retired_instances: deque[str] = field(default_factory=lambda: deque(maxlen=32))

    def cancel(self) -> None:
        """Release both resources when this entry runtime is unloaded."""
        self.generation += 1
        self.needs_refresh = True
        if self.cancel_expiry is not None:
            self.cancel_expiry()
            self.cancel_expiry = None
        if self.refresh_task is not None:
            self.refresh_task.cancel()
            self.refresh_task = None


def metrics_cache(entry: BticinoC300XConfigEntry) -> SystemMetricsCache:
    runtime = entry.runtime_data
    state = getattr(runtime, "system_metrics_cache", None)
    if state is None:
        state = SystemMetricsCache()
        runtime.system_metrics_cache = state
    return state


def metrics_are_fresh(entry: BticinoC300XConfigEntry) -> bool:
    """Check sample validity, independently of the short HTTP coalescing cache."""

    runtime = entry.runtime_data
    state = metrics_cache(entry)
    if state.needs_refresh or not runtime.system_metrics:
        return False
    if state.expires_at is not None:
        return monotonic() < state.expires_at
    updated_at = runtime.system_metrics_updated_at
    return (
        updated_at is not None
        and (datetime.now(UTC) - updated_at).total_seconds() < 660
    )


def invalidate_system_metrics(entry: BticinoC300XConfigEntry) -> None:
    """Invalidate the prior connection without erasing snapshot ordering."""

    state = metrics_cache(entry)
    if not state.needs_refresh:
        state.generation += 1
    state.needs_refresh = True
    cancel_metrics_expiry(entry)
    if state.refresh_task is not None:
        state.refresh_task.cancel()
        state.refresh_task = None


def cancel_metrics_expiry(entry: BticinoC300XConfigEntry) -> None:
    state = metrics_cache(entry)
    if state.cancel_expiry is not None:
        state.cancel_expiry()
        state.cancel_expiry = None


def apply_system_metrics(
    entry: BticinoC300XConfigEntry,
    metrics: dict[str, Any],
    *,
    hass: HomeAssistant | None = None,
    notify: bool = True,
    request_generation: int | None = None,
    request_snapshot: dict[str, Any] | None = None,
) -> bool:
    """Accept a snapshot only if it cannot roll back a newer push or connection."""

    runtime = entry.runtime_data
    state = metrics_cache(entry)
    current = runtime.system_metrics
    if request_generation is not None and request_generation != state.generation:
        return False
    instance = metrics.get("instance_id")
    old_instance = current.get("instance_id")
    sequence = cast(int, metrics.get("sample_sequence", 0))
    old_sequence = cast(int, current.get("sample_sequence", 0))
    if instance and instance in state.retired_instances:
        return False
    same_instance = bool(instance and instance == old_instance)
    if same_instance and sequence < old_sequence:
        return False
    if (
        request_generation is not None
        and current is not request_snapshot
        and (not same_instance or sequence <= old_sequence)
    ):
        return False
    if (
        old_instance
        and not instance
        and not (request_generation is not None and state.needs_refresh)
    ):
        return False
    if old_instance and instance != old_instance:
        state.retired_instances.append(old_instance)

    now = monotonic()
    interval = metrics.get("sample_interval_seconds") or 30
    heartbeat = metrics.get("heartbeat_seconds") or 600
    expires_at = (
        now + heartbeat + 2 * interval - (metrics.get("sample_age_ms") or 0) / 1000
    )
    # Repeated delivery of one sample is not evidence of a newer measurement.
    if same_instance and sequence == old_sequence and state.expires_at is not None:
        expires_at = min(expires_at, state.expires_at)
    runtime.system_metrics = metrics
    runtime.system_metrics_updated_at = datetime.now(UTC)
    state.expires_at = expires_at
    state.needs_refresh = False
    cancel_metrics_expiry(entry)
    if hass is not None:
        from homeassistant.core import callback
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        from homeassistant.helpers.event import async_call_later

        @callback
        def expire(_now: Any) -> None:
            if runtime.system_metrics is not metrics:
                return
            state.cancel_expiry = None
            state.expires_at = min(expires_at, monotonic())
            async_dispatcher_send(hass, SIGNAL_SYSTEM_METRICS_CHANGED, entry.entry_id)

        state.cancel_expiry = async_call_later(hass, max(0, expires_at - now), expire)
        if notify:
            async_dispatcher_send(hass, SIGNAL_SYSTEM_METRICS_CHANGED, entry.entry_id)
    return True


async def async_system_metrics(
    entry: BticinoC300XConfigEntry,
    *,
    hass: HomeAssistant | None = None,
    force_refresh: bool = False,
    required_key: str | None = None,
) -> dict[str, Any]:
    """Share one recovery request, including its failure, across all sensors."""

    runtime = entry.runtime_data
    metrics = runtime.system_metrics
    updated_at = runtime.system_metrics_updated_at
    if (
        metrics_are_fresh(entry)
        and updated_at is not None
        and (datetime.now(UTC) - updated_at).total_seconds() < 10
        and not (
            force_refresh
            and not metrics.get("instance_id")
            and (required_key is None or metrics.get(required_key) is None)
        )
    ):
        return metrics
    state = metrics_cache(entry)
    if state.refresh_task is None:
        state.refresh_task = create_task(_async_read_metrics(entry, hass))

        def clear(task: Task[dict[str, Any]]) -> None:
            if state.refresh_task is task:
                state.refresh_task = None
            if not task.cancelled():
                task.exception()

        state.refresh_task.add_done_callback(clear)
    return await shield(state.refresh_task)


async def _async_read_metrics(
    entry: BticinoC300XConfigEntry,
    hass: HomeAssistant | None,
) -> dict[str, Any]:
    runtime = entry.runtime_data
    generation = metrics_cache(entry).generation
    snapshot = runtime.system_metrics
    try:
        metrics = cast(dict[str, Any], await runtime.api.async_system_metrics())
    except C300XAgentApiError:
        if runtime.system_metrics is not snapshot and metrics_are_fresh(entry):
            return runtime.system_metrics
        raise
    apply_system_metrics(
        entry,
        metrics,
        hass=hass,
        request_generation=generation,
        request_snapshot=snapshot,
    )
    return runtime.system_metrics
