"""Shared event-driven message refresh helpers."""

from __future__ import annotations

from asyncio import Lock, Task
from collections.abc import Awaitable, Callable, Coroutine
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .api import C300XAgentApiError
from .api_errors import C300XAgentApiConnectionError
from .const import SIGNAL_MEMOS_CHANGED, SIGNAL_VIDEO_MESSAGES_CHANGED
from .entry_locks import entry_lock
from .entry_types import BticinoC300XConfigEntry

if TYPE_CHECKING:
    from .data import BticinoC300XRuntimeData

_VOICEMAIL_CACHE_SECONDS = 10
_MEMOS_CACHE_SECONDS = 10


def _refresh_lock(entry: BticinoC300XConfigEntry, payload_attr: str) -> Lock:
    """Return the per-(entry, payload) lock that coalesces concurrent refreshes."""

    return entry_lock(entry.entry_id, f"message_refresh:{payload_attr}")


def schedule_memos_refresh(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> None:
    """Refresh memos once and notify all memo-backed entities."""

    _schedule_single_refresh(
        hass,
        entry,
        task_attr="memos_refresh_task",
        refresh=lambda: _async_refresh_memos_from_agent(hass, entry),
    )


async def _async_refresh_memos_from_agent(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
) -> None:
    runtime = entry.runtime_data
    try:
        await async_memos(entry, force_refresh=True)
    except C300XAgentApiError:
        if getattr(entry, "runtime_data", None) is not runtime:
            return
        _store_payload(runtime, "memos", {**runtime.memos, "available": False})
    if getattr(entry, "runtime_data", None) is runtime:
        async_dispatcher_send(hass, SIGNAL_MEMOS_CHANGED, entry.entry_id)


def schedule_answering_machine_messages_refresh(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
) -> None:
    """Refresh video-message metadata once and notify all backed entities."""

    _schedule_single_refresh(
        hass,
        entry,
        task_attr="answering_machine_messages_refresh_task",
        refresh=lambda: _async_refresh_answering_machine_messages_from_agent(
            hass,
            entry,
        ),
    )


def _schedule_single_refresh(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
    *,
    task_attr: str,
    refresh: Callable[[], Coroutine[Any, Any, None]],
) -> None:
    """Schedule one refresh task per entry/runtime-data attribute."""

    resources = entry.runtime_data.resources
    task: Task[None] | None = getattr(resources, task_attr)
    if task is not None and not task.done():
        return
    task = hass.async_create_task(refresh())
    setattr(resources, task_attr, task)

    def _clear_task(done_task: Task[None]) -> None:
        if getattr(resources, task_attr) is done_task:
            setattr(resources, task_attr, None)

    task.add_done_callback(_clear_task)


async def _async_refresh_answering_machine_messages_from_agent(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
) -> None:
    runtime = entry.runtime_data
    try:
        await async_answering_machine_messages(entry, force_refresh=True)
    except C300XAgentApiError:
        if getattr(entry, "runtime_data", None) is not runtime:
            return
        _store_payload(
            runtime,
            "answering_machine_messages",
            {
                **runtime.answering_machine_messages,
                "available": False,
            },
        )
    if getattr(entry, "runtime_data", None) is runtime:
        async_dispatcher_send(hass, SIGNAL_VIDEO_MESSAGES_CHANGED, entry.entry_id)


async def async_answering_machine_messages(
    entry: BticinoC300XConfigEntry,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Return cached device-agent video message metadata."""

    return await _async_cached_payload(
        entry,
        payload_attr="answering_machine_messages",
        ttl_seconds=_VOICEMAIL_CACHE_SECONDS,
        force_refresh=force_refresh,
        refresh=entry.runtime_data.api.async_answering_machine_messages,
    )


async def async_memos(
    entry: BticinoC300XConfigEntry,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Return cached device-agent manual memo metadata."""

    return await _async_cached_payload(
        entry,
        payload_attr="memos",
        ttl_seconds=_MEMOS_CACHE_SECONDS,
        force_refresh=force_refresh,
        refresh=entry.runtime_data.api.async_memos,
    )


async def _async_cached_payload(
    entry: BticinoC300XConfigEntry,
    *,
    payload_attr: str,
    ttl_seconds: int,
    force_refresh: bool,
    refresh: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Return one cached agent payload, refreshing after TTL or on demand."""

    runtime = entry.runtime_data
    if not force_refresh:
        cached = _fresh_cached_payload(runtime, payload_attr, ttl_seconds)
        if cached is not None:
            return cached

    async with _refresh_lock(entry, payload_attr):
        _require_current_runtime(entry, runtime)
        if not force_refresh:
            # Re-check: a concurrent caller may have just refreshed this
            # payload while we were waiting for the lock.
            cached = _fresh_cached_payload(runtime, payload_attr, ttl_seconds)
            if cached is not None:
                return cached
        payload = await refresh()
        _require_current_runtime(entry, runtime)
        _store_payload(runtime, payload_attr, payload)
        return payload


def _require_current_runtime(
    entry: BticinoC300XConfigEntry, runtime: BticinoC300XRuntimeData,
) -> None:
    if getattr(entry, "runtime_data", None) is not runtime:
        raise C300XAgentApiConnectionError("Config entry changed during message refresh")


def _fresh_cached_payload(
    runtime: BticinoC300XRuntimeData,
    payload_attr: str,
    ttl_seconds: int,
) -> dict[str, Any] | None:
    """Return the cached payload if it is still within its TTL."""

    payload = getattr(runtime, payload_attr)
    updated_at = getattr(runtime, f"{payload_attr}_updated_at")
    if (
        payload
        and updated_at is not None
        and (datetime.now(UTC) - updated_at).total_seconds() < ttl_seconds
    ):
        return cast(dict[str, Any], payload)
    return None


def _store_payload(
    runtime: BticinoC300XRuntimeData,
    payload_attr: str,
    payload: dict[str, Any],
    *,
    updated_at: datetime | None = None,
) -> None:
    """Store one runtime-data payload with its timestamp."""

    setattr(runtime, payload_attr, payload)
    setattr(
        runtime,
        f"{payload_attr}_updated_at",
        updated_at or datetime.now(UTC),
    )
