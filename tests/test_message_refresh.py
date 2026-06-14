from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from custom_components.bticino_c300x import message_refresh
from custom_components.bticino_c300x.api import C300XAgentApiError
from custom_components.bticino_c300x.const import (
    SIGNAL_MEMOS_CHANGED,
    SIGNAL_VIDEO_MESSAGES_CHANGED,
)
from custom_components.bticino_c300x.message_refresh import (
    _async_refresh_answering_machine_messages_from_agent,
    _async_refresh_memos_from_agent,
    async_memos,
    schedule_memos_refresh,
)


class _FakeApi:
    def __init__(
        self,
        *,
        memos: dict[str, Any] | None = None,
        video_messages: dict[str, Any] | None = None,
        fail_memos: bool = False,
        fail_video_messages: bool = False,
    ) -> None:
        self.memos = memos or {"available": True, "total": 1}
        self.video_messages = video_messages or {"available": True, "total": 2}
        self.fail_memos = fail_memos
        self.fail_video_messages = fail_video_messages
        self.memo_reads = 0
        self.video_message_reads = 0

    async def async_memos(self) -> dict[str, Any]:
        self.memo_reads += 1
        if self.fail_memos:
            raise C300XAgentApiError("memos unavailable")
        return self.memos

    async def async_answering_machine_messages(self) -> dict[str, Any]:
        self.video_message_reads += 1
        if self.fail_video_messages:
            raise C300XAgentApiError("messages unavailable")
        return self.video_messages


class _FakeHass:
    def async_create_task(self, coro):
        return asyncio.create_task(coro)


def _entry(api: _FakeApi) -> SimpleNamespace:
    return SimpleNamespace(
        entry_id="entry-1",
        runtime_data=SimpleNamespace(
            api=api,
            memos={"available": True, "total": 7},
            memos_updated_at=None,
            memos_refresh_task=None,
            answering_machine_messages={"available": True, "total": 9},
            answering_machine_messages_updated_at=None,
            answering_machine_messages_refresh_task=None,
        ),
    )


def test_memos_cache_hit_skips_agent_read() -> None:
    api = _FakeApi()
    entry = _entry(api)
    entry.runtime_data.memos_updated_at = datetime.now(UTC)

    result = asyncio.run(async_memos(entry))

    assert result == {"available": True, "total": 7}
    assert api.memo_reads == 0


def test_memos_refresh_error_marks_cache_unavailable_and_dispatches(monkeypatch) -> None:
    signals: list[tuple[str, str]] = []
    monkeypatch.setattr(
        message_refresh,
        "async_dispatcher_send",
        lambda _hass, signal, entry_id: signals.append((signal, entry_id)),
    )
    entry = _entry(_FakeApi(fail_memos=True))

    asyncio.run(_async_refresh_memos_from_agent(SimpleNamespace(), entry))

    assert entry.runtime_data.memos["available"] is False
    assert entry.runtime_data.memos["total"] == 7
    assert signals == [(SIGNAL_MEMOS_CHANGED, "entry-1")]


def test_answering_machine_refresh_error_marks_cache_unavailable_and_dispatches(
    monkeypatch,
) -> None:
    signals: list[tuple[str, str]] = []
    monkeypatch.setattr(
        message_refresh,
        "async_dispatcher_send",
        lambda _hass, signal, entry_id: signals.append((signal, entry_id)),
    )
    entry = _entry(_FakeApi(fail_video_messages=True))

    asyncio.run(
        _async_refresh_answering_machine_messages_from_agent(SimpleNamespace(), entry)
    )

    assert entry.runtime_data.answering_machine_messages["available"] is False
    assert entry.runtime_data.answering_machine_messages["total"] == 9
    assert signals == [(SIGNAL_VIDEO_MESSAGES_CHANGED, "entry-1")]


def test_scheduled_refresh_deduplicates_pending_task_and_clears_when_done(
    monkeypatch,
) -> None:
    signals: list[tuple[str, str]] = []
    monkeypatch.setattr(
        message_refresh,
        "async_dispatcher_send",
        lambda _hass, signal, entry_id: signals.append((signal, entry_id)),
    )

    async def _run() -> None:
        entry = _entry(_FakeApi(memos={"available": True, "total": 3}))

        schedule_memos_refresh(_FakeHass(), entry)
        first_task = entry.runtime_data.memos_refresh_task
        schedule_memos_refresh(_FakeHass(), entry)

        assert entry.runtime_data.memos_refresh_task is first_task
        await first_task
        await asyncio.sleep(0)
        assert entry.runtime_data.memos_refresh_task is None
        assert entry.runtime_data.memos == {"available": True, "total": 3}

    asyncio.run(_run())
    assert signals == [(SIGNAL_MEMOS_CHANGED, "entry-1")]
