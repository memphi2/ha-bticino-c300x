"""Shared event-driven message refresh helpers."""

from __future__ import annotations

from asyncio import Task
from collections.abc import Awaitable, Callable, Coroutine
from datetime import UTC, datetime
from typing import Any, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .api import C300XAgentApiError
from .const import SIGNAL_MEMOS_CHANGED, SIGNAL_VIDEO_MESSAGES_CHANGED

_VOICEMAIL_CACHE_SECONDS = 10
_MEMOS_CACHE_SECONDS = 10


def schedule_memos_refresh(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Refresh memos once and notify all memo-backed entities."""

    _schedule_single_refresh(
        hass,
        entry,
        task_attr="memos_refresh_task",
        refresh=lambda: _async_refresh_memos_from_agent(hass, entry),
    )


async def _async_refresh_memos_from_agent(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    try:
        await async_memos(entry, force_refresh=True)
    except C300XAgentApiError:
        _store_payload(entry, "memos", {**entry.runtime_data.memos, "available": False})
    finally:
        async_dispatcher_send(hass, SIGNAL_MEMOS_CHANGED, entry.entry_id)


def schedule_answering_machine_messages_refresh(
    hass: HomeAssistant,
    entry: ConfigEntry,
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
    entry: ConfigEntry,
    *,
    task_attr: str,
    refresh: Callable[[], Coroutine[Any, Any, None]],
) -> None:
    """Schedule one refresh task per entry/runtime-data attribute."""

    task: Task[Any] | None = getattr(entry.runtime_data, task_attr)
    if task is not None and not task.done():
        return
    task = hass.async_create_task(refresh())
    setattr(entry.runtime_data, task_attr, task)

    def _clear_task(done_task: Task[Any]) -> None:
        if getattr(entry.runtime_data, task_attr) is done_task:
            setattr(entry.runtime_data, task_attr, None)

    task.add_done_callback(_clear_task)


async def _async_refresh_answering_machine_messages_from_agent(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    try:
        await async_answering_machine_messages(entry, force_refresh=True)
    except C300XAgentApiError:
        _store_payload(
            entry,
            "answering_machine_messages",
            {
                **entry.runtime_data.answering_machine_messages,
                "available": False,
            },
        )
    finally:
        async_dispatcher_send(hass, SIGNAL_VIDEO_MESSAGES_CHANGED, entry.entry_id)


async def async_answering_machine_messages(
    entry: ConfigEntry,
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
    entry: ConfigEntry,
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
    entry: ConfigEntry,
    *,
    payload_attr: str,
    ttl_seconds: int,
    force_refresh: bool,
    refresh: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Return one cached agent payload, refreshing after TTL or on demand."""

    now = datetime.now(UTC)
    payload = getattr(entry.runtime_data, payload_attr)
    updated_at = getattr(entry.runtime_data, f"{payload_attr}_updated_at")
    if (
        not force_refresh
        and payload
        and updated_at is not None
        and (now - updated_at).total_seconds() < ttl_seconds
    ):
        return cast(dict[str, Any], payload)
    payload = await refresh()
    _store_payload(entry, payload_attr, payload, updated_at=now)
    return payload


def _store_payload(
    entry: ConfigEntry,
    payload_attr: str,
    payload: dict[str, Any],
    *,
    updated_at: datetime | None = None,
) -> None:
    """Store one runtime-data payload with its timestamp."""

    setattr(entry.runtime_data, payload_attr, payload)
    setattr(
        entry.runtime_data,
        f"{payload_attr}_updated_at",
        updated_at or datetime.now(UTC),
    )
