from __future__ import annotations

import asyncio

import pytest

from custom_components.bticino_c300x import media_cache
from custom_components.bticino_c300x.media_cache import MediaBusyError, MediaCache


def test_identical_requests_share_work_and_cached_result():
    async def run():
        cache = MediaCache()
        calls = []

        async def load():
            calls.append(True)
            await asyncio.sleep(0)
            return b"video", "video/mp4"

        results = await asyncio.gather(*(cache.get("a", load) for _ in range(8)))
        assert results == [(b"video", "video/mp4")] * 8
        assert await cache.get("a", load) == results[0]
        assert len(calls) == 1

    asyncio.run(run())


def test_queue_is_bounded_and_cancelled_viewer_does_not_cancel_shared_work():
    async def run():
        cache = MediaCache()
        release = asyncio.Event()
        started = []

        async def load():
            started.append(True)
            await release.wait()
            return b"video", "video/mp4"

        tasks = [asyncio.create_task(cache.get(key, load)) for key in range(4)]
        await asyncio.sleep(0)
        with pytest.raises(MediaBusyError):
            await cache.get(5, load)
        viewer = asyncio.create_task(cache.get(0, load))
        tasks[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await tasks[0]
        assert len(started) == 1
        release.set()
        await asyncio.gather(viewer, *tasks[1:])
        assert len(started) == 4

    asyncio.run(run())


def test_cache_expires_and_enforces_byte_budget(monkeypatch):
    monkeypatch.setattr(media_cache, "_CACHE_SECONDS", 0.01)
    monkeypatch.setattr(media_cache, "MAX_MEDIA_BYTES", 8)

    async def run():
        cache = MediaCache()
        calls = []

        async def load():
            calls.append(True)
            return b"123456", "video/mp4"

        await cache.get("a", load)
        await cache.get("b", load)
        await cache.get("a", load)
        assert len(calls) == 3
        await asyncio.sleep(0.03)
        await cache.get("a", load)
        assert len(calls) == 4

        async def oversized():
            return b"x" * 9, "video/mp4"

        with pytest.raises(ValueError, match="size limit"):
            await cache.get("large", oversized)
        assert await cache.get("large", load) == (b"123456", "video/mp4")

    asyncio.run(run())
