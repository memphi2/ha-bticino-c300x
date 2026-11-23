"""The card learns the on-demand picture scope from the session it belongs to."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.bticino_c300x import camera_picture_scope
from custom_components.bticino_c300x.camera import C300XDoorbellCamera
from custom_components.bticino_c300x.camera_media.state_machine import MediaState
from tests.test_camera import _FakeApi, _FakeEntry, _FakeRuntimeData

SCOPE = "picture_controls_scope"


class _OwnedMediaApi(_FakeApi):
    """An agent that verified direct picture control in the running session."""

    def __init__(self) -> None:
        super().__init__()
        self.status_calls = 0

    async def async_doorbell_video_status(self) -> dict[str, Any]:
        self.status_calls += 1
        return {
            "available": True, "window_available": True, "media_owner": "agent",
            "bridge": {"media_owner": "agent", "media_active": True, "clients": 1,
                       "picture_controls_supported": True, SCOPE: "ring_and_on_demand"},
        }


def _camera(api: _FakeApi) -> tuple[C300XDoorbellCamera, list[Any]]:
    camera = C300XDoorbellCamera(_FakeEntry(runtime_data=_FakeRuntimeData(api=api)))  # type: ignore[arg-type]
    scheduled: list[Any] = []

    def _create(_hass: Any, coro: Any, *, key: str | None = None) -> None:
        assert key == "picture_scope"
        scheduled.append(coro)

    camera.hass = SimpleNamespace()  # type: ignore[assignment]
    camera._background_tasks.create = _create  # type: ignore[method-assign]
    camera._state_writes = 0  # type: ignore[attr-defined]
    camera._async_write_ha_state_if_ready = lambda: setattr(  # type: ignore[method-assign]
        camera, "_state_writes", camera._state_writes + 1)  # type: ignore[attr-defined]
    camera._apply_status({"available": True, "window_available": False,
                          "bridge": {"picture_controls_supported": True, SCOPE: "ring"}})
    return camera, scheduled


def _event(camera: C300XDoorbellCamera, key: str, **data: Any) -> None:
    camera._handle_agent_event(SimpleNamespace(data={"entry_id": "entry-1", "event_key": key, **data}))


def _view_started(camera: C300XDoorbellCamera) -> None:
    _event(camera, "doorbell_view_requested", video_window_available=True, video_available=True,
           media_owner="agent", bridge={"media_owner": "agent", "media_active": True, "clients": 1})
    assert camera._last_media_state is MediaState.ON_DEMAND_ACTIVE


@pytest.fixture(autouse=True)
def _no_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(camera_picture_scope, "PICTURE_SCOPE_REFRESH_DELAY_SECONDS", 0)


def test_on_demand_start_asks_once_for_the_session_scope() -> None:
    async def _run() -> None:
        api = _OwnedMediaApi()
        camera, scheduled = _camera(api)
        assert scheduled == [] and camera.extra_state_attributes[SCOPE] == "ring"
        _view_started(camera)
        _view_started(camera)  # A second event of the same session asks nothing more.
        assert len(scheduled) == 1
        await scheduled.pop()
        assert api.status_calls == 1
        assert camera.extra_state_attributes[SCOPE] == "ring_and_on_demand"
        assert camera._state_writes >= 1  # type: ignore[attr-defined]
        assert scheduled == []  # The status it applied is the same session.

    asyncio.run(_run())


def test_the_scope_ends_with_its_media_and_the_next_session_asks_again() -> None:
    async def _run() -> None:
        api = _OwnedMediaApi()
        camera, scheduled = _camera(api)
        _view_started(camera)
        await scheduled.pop()
        _event(camera, "doorbell_media_closed")
        assert camera.extra_state_attributes[SCOPE] == "ring"
        _view_started(camera)
        assert camera.extra_state_attributes[SCOPE] == "ring"
        assert len(scheduled) == 1
        await scheduled.pop()
        assert api.status_calls == 2
        assert camera.extra_state_attributes[SCOPE] == "ring_and_on_demand"

    asyncio.run(_run())


def test_media_that_ends_before_the_refresh_is_not_asked_about() -> None:
    async def _run() -> None:
        api = _OwnedMediaApi()
        camera, scheduled = _camera(api)
        _view_started(camera)
        _event(camera, "doorbell_media_closed")
        await scheduled.pop()
        assert api.status_calls == 0
        assert camera.extra_state_attributes[SCOPE] == "ring"

    asyncio.run(_run())


def test_a_quick_restart_reads_only_for_the_new_session_at_its_full_delay(
        monkeypatch: pytest.MonkeyPatch) -> None:
    delay = 0.4
    monkeypatch.setattr(camera_picture_scope, "PICTURE_SCOPE_REFRESH_DELAY_SECONDS", delay)

    async def _run() -> None:
        loop = asyncio.get_running_loop()
        api = _OwnedMediaApi()
        reads: list[float] = []
        status = api.async_doorbell_video_status

        async def _timed_status() -> dict[str, Any]:
            reads.append(loop.time())
            return await status()

        api.async_doorbell_video_status = _timed_status  # type: ignore[method-assign]
        camera = C300XDoorbellCamera(_FakeEntry(runtime_data=_FakeRuntimeData(api=api)))  # type: ignore[arg-type]
        camera.hass = SimpleNamespace(async_create_task=loop.create_task)  # type: ignore[assignment]
        camera._async_write_ha_state_if_ready = lambda: None  # type: ignore[method-assign]
        camera._apply_status({"available": True, "window_available": False,
                              "bridge": {"picture_controls_supported": True, SCOPE: "ring"}})
        _view_started(camera)  # Session A.
        await asyncio.sleep(delay / 4)
        _event(camera, "doorbell_media_closed")
        await asyncio.sleep(delay / 2)
        started = loop.time()
        _view_started(camera)  # Session B, while A's refresh would still sleep.
        await asyncio.sleep(delay * 2)
        assert len(reads) == 1
        assert reads[0] - started >= delay - 0.02
        assert camera.extra_state_attributes[SCOPE] == "ring_and_on_demand"
        await camera._background_tasks.close()

    asyncio.run(_run())


def test_a_ring_keeps_the_scope_it_reported() -> None:
    camera, scheduled = _camera(_OwnedMediaApi())
    camera._apply_status({"available": True, "window_available": True, "media_owner": "ring",
                          "bridge": {"media_owner": "ring", "ring_call_active": True, "ring_media_active": True,
                                     "picture_controls_supported": True, SCOPE: "ring_and_on_demand"}})
    assert camera._last_media_state is MediaState.RING_PREVIEW_ACTIVE
    assert camera.extra_state_attributes[SCOPE] == "ring_and_on_demand" and scheduled == []


class _GatedStatusApi(_OwnedMediaApi):
    """Hold each status read until the test releases it."""

    def __init__(self, *, ends_session: bool = False) -> None:
        super().__init__()
        self.gate = asyncio.Event()
        self.ends_session = ends_session

    async def async_doorbell_video_status(self) -> dict[str, Any]:
        self.status_calls += 1
        await self.gate.wait()
        if self.ends_session:
            return {"available": True, "window_available": False, "media_owner": "idle",
                    "bridge": {"media_owner": "idle", "media_active": False, "clients": 0,
                               "picture_controls_supported": True, SCOPE: "ring"}}
        return {
            "available": True, "window_available": True, "media_owner": "agent",
            "bridge": {"media_owner": "agent", "media_active": True, "clients": 1,
                       "picture_controls_supported": True, SCOPE: "ring_and_on_demand"},
        }


def _live_camera(api: _FakeApi) -> C300XDoorbellCamera:
    """A camera whose refresh runs as a real task in its own background tasks."""

    camera, _ = _camera(api)
    del camera._background_tasks.create  # Back to the real scheduling.
    camera.hass = SimpleNamespace(  # type: ignore[assignment]
        async_create_task=asyncio.get_running_loop().create_task)
    return camera


async def _settle() -> None:
    await asyncio.sleep(0.02)


def _no_errors(caplog: pytest.LogCaptureFixture) -> None:
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


def test_a_refresh_cancelled_in_its_status_read_applies_nothing_and_the_next_session_asks(
        caplog: pytest.LogCaptureFixture) -> None:
    async def _run() -> None:
        api = _GatedStatusApi()
        camera = _live_camera(api)
        _view_started(camera)
        await _settle()
        assert api.status_calls == 1  # Waiting for the agent's answer.
        _event(camera, "doorbell_media_closed")
        api.gate.set()  # The answer arrives in the same loop turn as the end of the media.
        await _settle()
        assert camera._last_media_state is not MediaState.ON_DEMAND_ACTIVE
        assert camera.extra_state_attributes[SCOPE] == "ring"
        _view_started(camera)
        await _settle()
        assert api.status_calls == 2
        assert camera.extra_state_attributes[SCOPE] == "ring_and_on_demand"
        assert not camera._background_tasks._tasks
        await camera._background_tasks.close()

    with caplog.at_level(logging.ERROR):
        asyncio.run(_run())
    _no_errors(caplog)


def test_a_refresh_whose_own_status_ends_the_session_still_writes_the_state(
        caplog: pytest.LogCaptureFixture) -> None:
    async def _run() -> None:
        api = _GatedStatusApi(ends_session=True)
        camera = _live_camera(api)
        _view_started(camera)
        await _settle()
        assert api.status_calls == 1
        writes = camera._state_writes  # type: ignore[attr-defined]
        api.gate.set()
        await _settle()
        assert camera._last_media_state is not MediaState.ON_DEMAND_ACTIVE
        assert camera.extra_state_attributes[SCOPE] == "ring"
        assert camera._state_writes > writes  # type: ignore[attr-defined]
        assert not camera._background_tasks._tasks and not camera._background_tasks._named
        await camera._background_tasks.close()

    with caplog.at_level(logging.ERROR):
        asyncio.run(_run())
    _no_errors(caplog)


def test_unload_during_the_delay_reads_nothing_and_leaves_no_task(
        monkeypatch: pytest.MonkeyPatch) -> None:
    delay = 0.2
    monkeypatch.setattr(camera_picture_scope, "PICTURE_SCOPE_REFRESH_DELAY_SECONDS", delay)

    async def _run() -> None:
        api = _GatedStatusApi()
        api.gate.set()
        camera = _live_camera(api)
        _view_started(camera)
        await asyncio.sleep(delay / 10)
        await camera._background_tasks.close()
        _event(camera, "doorbell_media_closed")
        _view_started(camera)  # Unloaded: no new refresh is scheduled.
        await asyncio.sleep(delay * 1.5)
        assert api.status_calls == 0
        assert not camera._background_tasks._tasks and not camera._background_tasks._named

    asyncio.run(_run())
