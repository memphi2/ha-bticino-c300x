from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.bticino_c300x import message_refresh
from custom_components.bticino_c300x.api import C300XAgentApiError
from custom_components.bticino_c300x.const import (
    SIGNAL_MEMOS_CHANGED,
    SIGNAL_VIDEO_MESSAGES_CHANGED,
)
from custom_components.bticino_c300x.data import C300XRuntimeResources
from custom_components.bticino_c300x.message_refresh import (
    _async_refresh_answering_machine_messages_from_agent,
    _async_refresh_memos_from_agent,
    async_memos,
    schedule_memos_refresh,
)


@pytest.mark.parametrize("kind", ["memos", "answering_machine_messages"])
@pytest.mark.parametrize("failure", [False, True])
@pytest.mark.parametrize("unloaded", [False, True])
def test_late_refresh_never_writes_or_notifies_replacement_runtime(
    monkeypatch, kind, failure, unloaded,
):
    signals = []
    monkeypatch.setattr(message_refresh, "async_dispatcher_send", lambda *args: signals.append(args))

    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        api = _FakeApi()

        async def fetch():
            started.set()
            await release.wait()
            if failure:
                raise C300XAgentApiError("old request failed")
            return {"available": True, "total": 99}

        setattr(api, f"async_{kind}", fetch)
        entry = _entry(api)
        original = entry.runtime_data
        refresh = getattr(message_refresh, f"_async_refresh_{kind}_from_agent")
        task = asyncio.create_task(refresh(SimpleNamespace(), entry))
        await started.wait()
        replacement = _entry(_FakeApi()).runtime_data
        if unloaded:
            del entry.runtime_data
        else:
            entry.runtime_data = replacement
        release.set()
        await task
        assert getattr(replacement, kind)["total"] == (7 if kind == "memos" else 9)
        assert getattr(original, kind)["total"] == (7 if kind == "memos" else 9)
        assert getattr(replacement, f"{kind}_updated_at") is None
        assert signals == []

    asyncio.run(run())


def test_queued_old_refresh_never_calls_agent_after_reload():
    async def run():
        entry = _entry(_FakeApi())
        entry.entry_id = "queued-reload"
        original = entry.runtime_data
        lock = message_refresh._refresh_lock(entry, "memos")
        await lock.acquire()
        task = asyncio.create_task(async_memos(entry, force_refresh=True))
        await asyncio.sleep(0)
        entry.runtime_data = _entry(_FakeApi()).runtime_data
        lock.release()
        with pytest.raises(C300XAgentApiError, match="Config entry changed"):
            await task
        assert original.api.memo_reads == 0

    asyncio.run(run())


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
            answering_machine_messages={"available": True, "total": 9},
            answering_machine_messages_updated_at=None,
            resources=C300XRuntimeResources(
                memos_refresh_task=None, answering_machine_messages_refresh_task=None
            ),
        ),
    )


def test_concurrent_memos_refresh_after_ttl_expiry_coalesces_into_one_agent_call() -> (
    None
):
    class _SlowApi(_FakeApi):
        async def async_memos(self) -> dict[str, Any]:
            await asyncio.sleep(0.02)
            return await super().async_memos()

    api = _SlowApi(memos={"available": True, "total": 42})
    entry = _entry(api)
    entry.runtime_data.memos_updated_at = None  # already stale/expired

    async def _run() -> tuple[dict[str, Any], dict[str, Any]]:
        return await asyncio.gather(async_memos(entry), async_memos(entry))

    first, second = asyncio.run(_run())

    assert api.memo_reads == 1
    assert first == {"available": True, "total": 42}
    assert second == {"available": True, "total": 42}


def test_memos_cache_hit_skips_agent_read() -> None:
    api = _FakeApi()
    entry = _entry(api)
    entry.runtime_data.memos_updated_at = datetime.now(UTC)

    result = asyncio.run(async_memos(entry))

    assert result == {"available": True, "total": 7}
    assert api.memo_reads == 0


def test_memos_refresh_error_marks_cache_unavailable_and_dispatches(
    monkeypatch,
) -> None:
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


def test_refresh_completion_keeps_original_resource_owner_after_reload() -> None:
    async def run():
        entry = _entry(_FakeApi())
        old_resources = entry.runtime_data.resources
        done = asyncio.Event()
        message_refresh._schedule_single_refresh(
            _FakeHass(),
            entry,
            task_attr="memos_refresh_task",
            refresh=done.wait,
        )
        old_task = old_resources.memos_refresh_task
        replacement_task = asyncio.create_task(asyncio.Event().wait())
        new_resources = C300XRuntimeResources(memos_refresh_task=replacement_task)
        entry.runtime_data = SimpleNamespace(resources=new_resources)
        done.set()
        await old_task
        await asyncio.sleep(0)
        assert old_resources.memos_refresh_task is None
        assert new_resources.memos_refresh_task is replacement_task
        new_resources.close()
        await asyncio.gather(replacement_task, return_exceptions=True)

    asyncio.run(run())


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
        first_task = entry.runtime_data.resources.memos_refresh_task
        schedule_memos_refresh(_FakeHass(), entry)

        assert entry.runtime_data.resources.memos_refresh_task is first_task
        await first_task
        await asyncio.sleep(0)
        assert entry.runtime_data.resources.memos_refresh_task is None
        assert entry.runtime_data.memos == {"available": True, "total": 3}

    asyncio.run(_run())
    assert signals == [(SIGNAL_MEMOS_CHANGED, "entry-1")]


@pytest.mark.parametrize("kind", ["memos", "answering_machine_messages"])
@pytest.mark.parametrize("fail_first", [False, True])
def test_events_during_refresh_trigger_one_trailing_fetch(monkeypatch, kind, fail_first):
    monkeypatch.setattr(message_refresh, "async_dispatcher_send", lambda *_: None)

    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        entry = _entry(_FakeApi())
        entry.entry_id = f"trailing-{kind}-{fail_first}"
        reads = []
        total = 1

        async def fetch():
            snapshot = {"available": True, "total": total}
            reads.append(snapshot)
            if len(reads) == 1:
                started.set()
                await release.wait()
                if fail_first:
                    raise C300XAgentApiError("first snapshot failed")
            return snapshot

        setattr(entry.runtime_data.api, f"async_{kind}", fetch)
        schedule = getattr(message_refresh, f"schedule_{kind}_refresh")
        schedule(_FakeHass(), entry)
        task = getattr(entry.runtime_data.resources, f"{kind}_refresh_task")
        await started.wait()
        total = 2
        for _ in range(5):
            schedule(_FakeHass(), entry)
        release.set()
        await task
        await asyncio.sleep(0)
        assert len(reads) == 2
        assert getattr(entry.runtime_data, kind) == {"available": True, "total": 2}
        assert not entry.runtime_data.resources.pending_message_refreshes
        assert getattr(entry.runtime_data.resources, f"{kind}_refresh_task") is None

    asyncio.run(run())


@pytest.mark.parametrize("close", [False, True])
def test_pending_refresh_does_not_run_after_runtime_replacement_or_close(close):
    async def run():
        entry = _entry(_FakeApi())
        old = entry.runtime_data
        schedule_memos_refresh(_FakeHass(), entry)
        task = old.resources.memos_refresh_task
        if close:
            old.resources.close()
        else:
            entry.runtime_data = _entry(_FakeApi()).runtime_data
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)
        assert old.api.memo_reads == 0
        assert entry.runtime_data.api.memo_reads == 0
        assert not old.resources.pending_message_refreshes

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["memos", "answering_machine_messages"])
def test_media_reads_share_cache_but_expiry_and_changes_fetch_fresh_data(kind):
    from custom_components.bticino_c300x import media_source

    async def run():
        class SlowApi(_FakeApi):
            async def async_memos(self):
                await asyncio.sleep(0)
                return await super().async_memos()

            async def async_answering_machine_messages(self):
                await asyncio.sleep(0)
                return await super().async_answering_machine_messages()

        api = SlowApi()
        entry = _entry(api)
        entry.entry_id = f"media-cache-{kind}"
        read = (media_source._async_memos_for_entry if kind == "memos"
                else media_source._async_messages_for_entry)
        count_attr = "memo_reads" if kind == "memos" else "video_message_reads"
        await asyncio.gather(*(read(entry) for _ in range(3)))
        assert getattr(api, count_attr) == 1
        await read(entry)
        assert getattr(api, count_attr) == 1
        setattr(entry.runtime_data, f"{kind}_updated_at", datetime.now(UTC) - timedelta(seconds=11))
        await read(entry)
        assert getattr(api, count_attr) == 2
        await getattr(message_refresh, f"async_{kind}")(entry, force_refresh=True)
        assert getattr(api, count_attr) == 3
        await read(entry)
        assert getattr(api, count_attr) == 3

    asyncio.run(run())
