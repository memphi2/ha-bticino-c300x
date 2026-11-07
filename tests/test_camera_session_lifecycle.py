"""Offer ownership without HA, provider or device operations."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import pytest

from custom_components.bticino_c300x.camera_media import session_lifecycle
from custom_components.bticino_c300x.camera_media.background_tasks import (
    CameraBackgroundTasks,
)
from custom_components.bticino_c300x.camera_media.session_lifecycle import (
    CameraWebRTCSessions,
    media_owner_stopping,
    media_stop_scope,
)
from custom_components.bticino_c300x.camera_media.webrtc_session import (
    ProviderWebRTCSession,
)
from custom_components.bticino_c300x.data import C300XRuntimeResources


def _session(owner="doorbell", resource="shared"):
    return ProviderWebRTCSession(
        provider=SimpleNamespace(async_on_webrtc_candidate=AsyncMock()),
        owner=owner, resource_id=resource, send_message=lambda _: None,
        wants_audio=False, wants_backchannel=False,
    )


def test_session_queries_distinguish_active_offers_and_shared_resources():
    async def run():
        sessions = CameraWebRTCSessions(CameraBackgroundTasks())
        sessions.active.update({
            "one": _session(), "two": _session(),
            "home": _session("home_call", "home-resource"),
        })
        with sessions.opening("one"), sessions.opening("pending"):
            active = sessions.active_ids()
            assert active == ["one", "two", "home"]
            assert sessions.active_ids("doorbell") == ["one", "two"]
            assert sessions.active_ids("home_call") == ["home"]
            assert sessions.active_ids("unknown") == []
            assert sessions.ids_by_owner("doorbell") == ["one", "two", "pending"]
            assert sessions.has_resource("shared")
            sessions.active.pop("one")
            assert active == ["one", "two", "home"]
            assert sessions.has_resource("shared")
            sessions.active.pop("two")
            assert not sessions.has_resource("shared")
            assert sessions.has_resource("home-resource")

    asyncio.run(run())


def test_candidates_stay_bounded_and_flush_only_when_ready(monkeypatch):
    monkeypatch.setattr(session_lifecycle, "MAX_PRESESSION_WEBRTC_SESSIONS", 2)
    monkeypatch.setattr(session_lifecycle, "MAX_PRESESSION_WEBRTC_CANDIDATES", 3)

    async def run():
        tasks = CameraBackgroundTasks()
        sessions = CameraWebRTCSessions(tasks)
        for key in ("oldest", "kept", "newest"):
            for candidate in range(4):
                await sessions.on_candidate(key, candidate)
        assert sessions.candidates == {"kept": [0, 1, 2], "newest": [0, 1, 2]}

        session = sessions.active["kept"] = _session()
        session.pending_candidates = sessions.candidates.pop("kept")
        send = session.provider.async_on_webrtc_candidate
        await sessions.on_candidate("kept", "overflow")
        await sessions.flush_candidates("missing")
        await sessions.flush_candidates("kept")
        send.assert_not_awaited()
        assert session.pending_candidates == [0, 1, 2]
        session.ready = True
        await sessions.flush_candidates("kept")
        await sessions.on_candidate("kept", "live")
        assert not session.pending_candidates
        assert send.await_args_list == [call("kept", value) for value in (0, 1, 2, "live")]
        await tasks.close()
        await sessions.on_candidate("kept", "after close")
        await sessions.on_candidate("after close", "ignored")
        assert send.await_count == 4
        assert sessions.candidates == {"newest": [0, 1, 2]}

    asyncio.run(run())


def test_provider_messages_require_current_uncancelled_session():
    async def run():
        sessions = CameraWebRTCSessions(CameraBackgroundTasks())
        session = sessions.active["one"] = _session()
        assert sessions.accepts_provider_messages("one", session)
        assert not sessions.accepts_provider_messages("one", replace(session))
        assert not sessions.accepts_provider_messages("unknown", session)
        entered = asyncio.Event()

        async def offer():
            with sessions.opening("one"):
                entered.set()
                await asyncio.Future()

        pending = asyncio.create_task(offer())
        try:
            await entered.wait()
            assert sessions.accepts_provider_messages("one", session)
            sessions.cancel_offer("one")
            assert not sessions.accepts_provider_messages("one", session)
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        replacement = sessions.active["one"] = replace(session)
        assert not sessions.accepts_provider_messages("one", session)
        assert sessions.accepts_provider_messages("one", replacement)
        sessions.active.pop("one")
        assert not sessions.accepts_provider_messages("one", replacement)

    asyncio.run(run())


def test_duplicate_offer_cannot_replace_original_owner():
    async def run():
        tasks = CameraBackgroundTasks()
        sessions = CameraWebRTCSessions(tasks)
        with sessions.opening("one"):
            with pytest.raises(ValueError, match="already opening"), sessions.opening("one"):
                pass
            assert sessions.offers["one"].task is asyncio.current_task()
            assert len(tasks._tasks) == 1
        assert not sessions.offers
        assert not tasks._tasks
        with sessions.opening("one"):
            pass

    asyncio.run(run())


def test_nested_stop_scopes_survive_runtime_disposal():
    resources = C300XRuntimeResources()
    with media_stop_scope(resources, "doorbell"):
        with media_stop_scope(resources, "doorbell"):
            assert media_owner_stopping(resources, "doorbell")
            assert not media_owner_stopping(resources, "home_call")
        assert media_owner_stopping(resources, "doorbell")
        resources.close()
    assert not resources.media_stop_counts


def test_repeated_close_waits_for_cleanup_without_recancelling_or_touching_other_offer():
    async def run():
        tasks = CameraBackgroundTasks()
        sessions = CameraWebRTCSessions(tasks)
        started, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        calls = []

        async def offer():
            with sessions.opening("one"):
                started.set()
                try:
                    await asyncio.Future()
                finally:
                    cleaning.set()
                    await release.wait()
                    calls.append("cleaned")

        async def close():
            calls.append("closed")

        pending = asyncio.create_task(offer())
        await started.wait()
        with sessions.opening("other"):
            cancelled = sessions.cancel_offer("one")
            await cleaning.wait()
            assert sessions.cancel_offer("one") is cancelled
            assert pending.cancelling() == 1
            assert sessions.cancel_offer("unknown") is None
            closer = asyncio.create_task(sessions.close_after_offer(cancelled, close))
            await asyncio.sleep(0)
            assert not closer.done()
            release.set()
            await closer
            assert pending.cancelled()
            assert "other" in sessions.offers
        assert calls == ["cleaned", "closed"]
        assert not sessions.offers
        assert not tasks._tasks

    asyncio.run(run())
