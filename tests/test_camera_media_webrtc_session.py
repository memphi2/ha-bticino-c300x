from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from custom_components.bticino_c300x.camera_media.webrtc_session import (
    async_close_provider_session,
    webrtc_message_is_error,
)


class _AsDictMessage:
    def __init__(self, data: object) -> None:
        self._data = data

    def as_dict(self) -> object:
        return self._data


class _BrokenAsDictMessage:
    def as_dict(self) -> object:
        raise RuntimeError("boom")


class WebRTCError:
    pass


def test_webrtc_message_error_detection_accepts_provider_message_shapes() -> None:
    assert webrtc_message_is_error({"type": "error"}) is True
    assert webrtc_message_is_error({"type": "answer"}) is False
    assert webrtc_message_is_error(_AsDictMessage({"type": "error"})) is True
    assert webrtc_message_is_error(_AsDictMessage({"type": "answer"})) is False
    assert webrtc_message_is_error(_AsDictMessage("not-a-dict")) is False
    assert webrtc_message_is_error(_BrokenAsDictMessage()) is False
    assert webrtc_message_is_error(WebRTCError()) is True


@pytest.mark.parametrize("replaced", [False, True])
def test_cancelled_provider_close_restores_wrapper_without_replacing_new_session(replaced):
    async def run():
        started = asyncio.Event()

        async def close():
            started.set()
            await asyncio.Future()

        original = SimpleNamespace(ws_client=SimpleNamespace(close=close), camera=object())
        replacement = object()
        provider = SimpleNamespace(_sessions={"s": original})
        task = asyncio.create_task(async_close_provider_session(provider, "s", Mock()))
        try:
            await asyncio.wait_for(started.wait(), 1)
            assert not provider._sessions
            if replaced:
                provider._sessions["s"] = replacement
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert provider._sessions["s"] is (replacement if replaced else original)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


@pytest.mark.parametrize("replaced", [False, True])
@pytest.mark.parametrize("public_close", ["missing", "works", "fails"])
def test_failed_provider_close_retries_once_and_never_leaves_its_entry(replaced, public_close):
    """The camera forgets the session after this call, so nothing retries later."""

    async def run():
        replacement = object()
        provider = SimpleNamespace(_sessions={})
        retries = []

        async def close():
            if replaced:
                provider._sessions["s"] = replacement
            raise RuntimeError("close failed")

        async def async_close_session(session_id):
            retries.append(provider._sessions.get(session_id))
            if public_close == "fails":
                raise RuntimeError("public close failed")
            provider._sessions.pop(session_id, None)

        if public_close != "missing":
            provider.async_close_session = async_close_session
        original = SimpleNamespace(ws_client=SimpleNamespace(close=close), camera=object())
        provider._sessions["s"] = original
        log = Mock()

        assert await async_close_provider_session(provider, "s", log) == "go2rtc_ws_failed"
        if replaced:
            # A new session under the same id is neither retried nor removed.
            assert provider._sessions["s"] is replacement
            assert retries == []
        else:
            assert "s" not in provider._sessions
            assert retries == ([] if public_close == "missing" else [original])
        log.assert_called_once()

    asyncio.run(run())


@pytest.mark.parametrize("awaitable", [False, True])
def test_unknown_provider_session_layout_delegates_to_public_close(awaitable):
    async def run():
        original = object()
        provider = SimpleNamespace(_sessions={"s": original})
        closed = []

        def close(session_id):
            # The public API must still be able to find its own private entry.
            assert provider._sessions.pop(session_id) is original
            closed.append(session_id)

        async def async_close(session_id):
            await asyncio.sleep(0)
            close(session_id)

        provider.async_close_session = async_close if awaitable else close
        await async_close_provider_session(provider, "s", Mock())
        assert closed == ["s"]
        assert not provider._sessions

    asyncio.run(run())


def test_unknown_provider_session_without_close_api_keeps_entry():
    original = object()
    provider = SimpleNamespace(_sessions={"s": original})

    result = asyncio.run(async_close_provider_session(provider, "s", Mock()))

    assert result == "provider_close_missing"
    assert provider._sessions["s"] is original
