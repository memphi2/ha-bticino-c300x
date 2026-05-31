"""Shared event-driven message refresh helpers."""

from __future__ import annotations

from asyncio import Task
from datetime import UTC, datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .api import C300XAgentApiError
from .const import SIGNAL_MEMOS_CHANGED, SIGNAL_VIDEO_MESSAGES_CHANGED

_VOICEMAIL_CACHE_SECONDS = 10
_MEMOS_CACHE_SECONDS = 10


def schedule_memos_refresh(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Refresh memos once and notify all memo-backed entities."""

    task: Task[Any] | None = entry.runtime_data.memos_refresh_task
    if task is not None and not task.done():
        return
    task = hass.async_create_task(_async_refresh_memos_from_agent(hass, entry))
    entry.runtime_data.memos_refresh_task = task

    def _clear_task(done_task: Task[Any]) -> None:
        if entry.runtime_data.memos_refresh_task is done_task:
            entry.runtime_data.memos_refresh_task = None

    task.add_done_callback(_clear_task)


async def _async_refresh_memos_from_agent(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    try:
        await async_memos(entry, force_refresh=True)
    except C300XAgentApiError:
        entry.runtime_data.memos = {**entry.runtime_data.memos, "available": False}
        entry.runtime_data.memos_updated_at = datetime.now(UTC)
    finally:
        async_dispatcher_send(hass, SIGNAL_MEMOS_CHANGED, entry.entry_id)


def schedule_answering_machine_messages_refresh(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Refresh video-message metadata once and notify all backed entities."""

    task: Task[Any] | None = entry.runtime_data.answering_machine_messages_refresh_task
    if task is not None and not task.done():
        return
    task = hass.async_create_task(
        _async_refresh_answering_machine_messages_from_agent(hass, entry)
    )
    entry.runtime_data.answering_machine_messages_refresh_task = task

    def _clear_task(done_task: Task[Any]) -> None:
        if entry.runtime_data.answering_machine_messages_refresh_task is done_task:
            entry.runtime_data.answering_machine_messages_refresh_task = None

    task.add_done_callback(_clear_task)


async def _async_refresh_answering_machine_messages_from_agent(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    try:
        await async_answering_machine_messages(entry, force_refresh=True)
    except C300XAgentApiError:
        entry.runtime_data.answering_machine_messages = {
            **entry.runtime_data.answering_machine_messages,
            "available": False,
        }
        entry.runtime_data.answering_machine_messages_updated_at = datetime.now(UTC)
    finally:
        async_dispatcher_send(hass, SIGNAL_VIDEO_MESSAGES_CHANGED, entry.entry_id)


async def async_answering_machine_messages(
    entry: ConfigEntry,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Return cached device-agent video message metadata."""

    now = datetime.now(UTC)
    updated_at = entry.runtime_data.answering_machine_messages_updated_at
    if (
        not force_refresh
        and entry.runtime_data.answering_machine_messages
        and updated_at is not None
        and (now - updated_at).total_seconds() < _VOICEMAIL_CACHE_SECONDS
    ):
        return entry.runtime_data.answering_machine_messages
    messages = await entry.runtime_data.api.async_answering_machine_messages()
    entry.runtime_data.answering_machine_messages = messages
    entry.runtime_data.answering_machine_messages_updated_at = now
    return messages


async def async_memos(
    entry: ConfigEntry,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Return cached device-agent manual memo metadata."""

    now = datetime.now(UTC)
    updated_at = entry.runtime_data.memos_updated_at
    if (
        not force_refresh
        and entry.runtime_data.memos
        and updated_at is not None
        and (now - updated_at).total_seconds() < _MEMOS_CACHE_SECONDS
    ):
        return entry.runtime_data.memos
    memos = await entry.runtime_data.api.async_memos()
    entry.runtime_data.memos = memos
    entry.runtime_data.memos_updated_at = now
    return memos
