"""A restarted agent has lost its calls; the camera must not keep them."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from custom_components.bticino_c300x.camera import C300XDoorbellCamera
from custom_components.bticino_c300x.camera_media.state_machine import MediaState
from tests.test_camera import _FakeApi, _FakeEntry, _FakeRuntimeData, _record_task

HOME_CALL = {"available": True, "running": True, "active": True, "answered": True}


class _RestartedAgentApi(_FakeApi):
    """An agent that just started: no stream, no call."""

    fail_status = False
    fail_home_call = False

    async def async_doorbell_video_status(self) -> dict[str, Any]:
        if self.fail_status:
            raise RuntimeError("agent not reachable yet")
        return {"available": True, "window_available": False, "bridge": {"clients": 0}}

    async def async_home_call_status(self) -> dict[str, Any]:
        self.home_call_status_calls += 1
        if self.fail_home_call:
            raise RuntimeError("agent not reachable yet")
        return {"available": True, "running": False, "active": False, "answered": False}


def _camera_in_a_home_call(api: _FakeApi) -> tuple[C300XDoorbellCamera, list[Any]]:
    camera = C300XDoorbellCamera(_FakeEntry(runtime_data=_FakeRuntimeData(api=api)))  # type: ignore[arg-type]
    scheduled: list[Any] = []

    def _create(_hass: Any, coro: Any, **_kwargs: Any) -> Any:
        scheduled.append(coro)
        return SimpleNamespace()

    camera.hass = SimpleNamespace(async_create_task=lambda coro: _record_task([], coro))
    camera._background_tasks.create = _create
    camera._state_writes = 0
    camera._async_write_ha_state_if_ready = lambda: setattr(camera, "_state_writes", camera._state_writes + 1)
    camera._handle_system_metrics_changed("entry-1")
    camera._apply_home_call_status(HOME_CALL)
    assert camera._cached_home_call_state_needs_refresh()
    return camera, scheduled


def test_an_agent_restart_ends_the_call_the_camera_still_shows() -> None:
    async def _run() -> None:
        api = _RestartedAgentApi()
        camera, scheduled = _camera_in_a_home_call(api)
        # Without a restart and without a session the heartbeat asks nothing.
        camera._handle_system_metrics_changed("entry-1")
        assert scheduled == []

        camera._runtime_data.diagnostics.agent_restart_count += 1
        camera._handle_system_metrics_changed("entry-1")
        assert len(scheduled) == 1
        await scheduled.pop()

        assert not camera._cached_home_call_state_needs_refresh()
        assert not camera._bridge_status.get("home_call_active")
        assert camera._state_writes == 1  # the card is told
        # The restart is settled: the next heartbeat is quiet again.
        camera._handle_system_metrics_changed("entry-1")
        assert scheduled == []

    asyncio.run(_run())


def test_a_restart_is_retried_until_the_agent_answers() -> None:
    async def _run() -> None:
        api = _RestartedAgentApi()
        api.fail_status = True
        camera, scheduled = _camera_in_a_home_call(api)
        camera._runtime_data.diagnostics.agent_restart_count += 1
        camera._handle_system_metrics_changed("entry-1")
        await scheduled.pop()

        api.fail_status = False
        camera._handle_system_metrics_changed("entry-1")
        assert len(scheduled) == 1
        await scheduled.pop()
        camera._handle_system_metrics_changed("entry-1")
        assert scheduled == []

    asyncio.run(_run())


def test_a_failed_call_status_read_keeps_the_restart_open() -> None:
    async def _run() -> None:
        api = _RestartedAgentApi()
        api.fail_home_call = True
        camera, scheduled = _camera_in_a_home_call(api)
        # The stream status answers but says nothing about the call.
        camera._async_refresh_video_status_or_none = _status  # type: ignore[method-assign]
        camera._runtime_data.diagnostics.agent_restart_count += 1
        camera._handle_system_metrics_changed("entry-1")
        await scheduled.pop()
        assert camera._cached_home_call_state_needs_refresh()

        api.fail_home_call = False
        camera._handle_system_metrics_changed("entry-1")
        assert len(scheduled) == 1
        await scheduled.pop()
        assert not camera._cached_home_call_state_needs_refresh()
        camera._handle_system_metrics_changed("entry-1")
        assert scheduled == []

    asyncio.run(_run())


async def _status(**_kwargs: Any) -> dict[str, Any]:
    return {"bridge": {"clients": 0}}


class _DisplayCallApi(_FakeApi):
    """An agent whose display-call guard holds until ``external`` is cleared."""

    external = True
    status_reads = 0

    async def async_doorbell_video_status(self) -> dict[str, Any]:
        self.status_reads += 1
        owner = "external_media" if self.external else "idle"
        return {
            "available": True,
            "window_available": False,
            "media_owner": owner,
            "external_media_active": self.external,
            "bridge": {"clients": 0, "media_owner": owner, "external_media_active": self.external},
        }


def test_a_display_call_whose_end_frame_was_lost_is_reconciled() -> None:
    """A display-answered ring keeps external media after media.closed; when
    its bus end frame is lost no event ends it. The heartbeat asks the agent,
    which keeps it while its guard holds and reports idle once it expired."""

    async def _run() -> None:
        api = _DisplayCallApi()
        camera = C300XDoorbellCamera(_FakeEntry(runtime_data=_FakeRuntimeData(api=api)))  # type: ignore[arg-type]
        scheduled: list[Any] = []

        def _create(_hass: Any, coro: Any, **_kwargs: Any) -> Any:
            scheduled.append(coro)
            return SimpleNamespace()

        camera.hass = SimpleNamespace(async_create_task=lambda coro: _record_task([], coro))
        camera._background_tasks.create = _create
        camera._async_write_ha_state_if_ready = lambda: None
        camera._handle_system_metrics_changed("entry-1")  # baseline, idle: quiet
        assert scheduled == []
        # media.closed with external_media_active: the display holds the call.
        camera._apply_event_media_facts({"external_media_active": True, "media_owner": "external_media"})
        camera._refresh_derived_media_state()
        assert camera._last_media_state is MediaState.EXTERNAL_MEDIA_ACTIVE

        # The guard still holds: the read must not end a real display call.
        camera._handle_system_metrics_changed("entry-1")
        assert len(scheduled) == 1
        await scheduled.pop()
        assert api.status_reads == 1
        assert camera._last_media_state is MediaState.EXTERNAL_MEDIA_ACTIVE

        # The guard expired without an end frame: the next heartbeat frees it.
        api.external = False
        camera._handle_system_metrics_changed("entry-1")
        assert len(scheduled) == 1
        await scheduled.pop()
        assert camera._last_media_state is not MediaState.EXTERNAL_MEDIA_ACTIVE
        assert camera._webrtc_sessions.active == {}
        camera._handle_system_metrics_changed("entry-1")
        assert scheduled == []

    asyncio.run(_run())
