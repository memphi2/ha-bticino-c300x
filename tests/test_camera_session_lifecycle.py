"""Offer ownership without HA, provider or device operations."""

import asyncio

import pytest

from custom_components.bticino_c300x.camera_media.background_tasks import (
    CameraBackgroundTasks,
)
from custom_components.bticino_c300x.camera_media.session_lifecycle import (
    CameraWebRTCSessions,
)


def test_duplicate_offer_cannot_replace_original_owner():
    async def run():
        tasks = CameraBackgroundTasks()
        sessions = CameraWebRTCSessions(tasks)
        with sessions.opening("one"):
            with pytest.raises(ValueError, match="already opening"), sessions.opening("one"):
                pass
            assert sessions.offers["one"] is asyncio.current_task()
            assert len(tasks._tasks) == 1
        assert not sessions.offers
        assert not tasks._tasks
        with sessions.opening("one"):
            pass

    asyncio.run(run())


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
