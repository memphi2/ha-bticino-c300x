"""A failed on-demand start must not leave the card on "busy".

Replays the HA side of the device capture 2026-11-24 13:37:44-13:37:56: the
card's stream session is ready, go2rtc retries PLAY against a station that
answers 486, the metrics heartbeat reconciles in the middle of a retry
(clients 1, media_starting), and the user presses Stop while the agent is
already idle again (no stop request, only the drain reads).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from custom_components.bticino_c300x.camera import C300XDoorbellCamera
from custom_components.bticino_c300x.camera_media.state_machine import MediaState
from custom_components.bticino_c300x.use_cases.doorbell_video import (
    DoorbellVideoUseCase,
)
from tests.test_camera import (
    _FakeApi,
    _FakeEntry,
    _FakeGo2RtcWsClient,
    _FakeRuntimeData,
    _FakeWebRTCProvider,
    _ProviderWebRTCSession,
    camera_ha_boundary,  # noqa: F401
)

IDLE = {"clients": 0, "media_starting": False}
RETRYING = {"clients": 1, "media_starting": True}


class _ChurningAgentApi(_FakeApi):
    """Status reads follow a scripted list; the last one repeats."""

    def __init__(self, bridges: list[dict[str, Any]]) -> None:
        super().__init__()
        self.bridges = bridges

    async def async_doorbell_video_status(self) -> dict[str, Any]:
        bridge = self.bridges.pop(0) if len(self.bridges) > 1 else self.bridges[0]
        return {
            "available": True, "window_available": False, "stream_path": "/doorbell-video",
            "bridge": {
                "media_owner": "idle", "external_media_active": False, "media_active": False,
                "stop_in_progress": False, "call_active": False,
                "last_error": "ondemand_sip_setup_failed:answer_486", **bridge,
            },
        }


def _camera_with_stream_session(api: _ChurningAgentApi) -> C300XDoorbellCamera:
    entry = _FakeEntry(data={"video_enabled": True}, runtime_data=_FakeRuntimeData(api=api))
    camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
    camera.hass = SimpleNamespace(async_create_task=asyncio.create_task)
    entry.runtime_data.resources.prepare_doorbell_video_stop = camera.async_prepare_doorbell_video_stop
    provider = _FakeWebRTCProvider()
    provider._sessions = {"card": _FakeGo2RtcWsClient([])}  # type: ignore[attr-defined]
    camera._webrtc_sessions.active["card"] = _ProviderWebRTCSession(
        provider=provider, owner="doorbell", send_message=lambda _m: None,
        wants_audio=True, wants_backchannel=False, resource_id="doorbell:entry-1", ready=True,
    )
    return camera


async def _heartbeat_reconciles(camera: C300XDoorbellCamera) -> None:
    camera._handle_system_metrics_changed("entry-1")
    await asyncio.gather(*camera._background_tasks._tasks)


def test_stop_after_a_failed_start_returns_the_card_to_idle() -> None:
    async def run() -> None:
        # Heartbeat read mid-retry; Stop: idle check, drain reads 1 then 0.
        api = _ChurningAgentApi([RETRYING, IDLE, RETRYING, IDLE])
        camera = _camera_with_stream_session(api)
        await _heartbeat_reconciles(camera)
        assert camera._last_media_state is MediaState.RTSP_BUSY
        assert "card" in camera._webrtc_sessions.active

        await DoorbellVideoUseCase(camera._entry).stop()
        assert camera._webrtc_sessions.active == {}
        assert api.stop_calls == 0  # the agent was idle: no stop request
        assert camera._last_media_state is MediaState.IDLE

    asyncio.run(run())


def test_heartbeat_clears_busy_after_the_card_closed_its_session() -> None:
    """The card may close its peer without Stop; the heartbeat heals it."""

    async def run() -> None:
        api = _ChurningAgentApi([RETRYING, IDLE])
        camera = _camera_with_stream_session(api)
        await _heartbeat_reconciles(camera)
        assert camera._last_media_state is MediaState.RTSP_BUSY

        camera.close_webrtc_session("card")
        await asyncio.gather(*camera._background_tasks._tasks)
        assert camera._webrtc_sessions.active == {}
        await _heartbeat_reconciles(camera)
        assert camera._last_media_state is MediaState.IDLE

        # Idle and without sessions, the heartbeat asks nothing.
        reads = len(api.bridges)
        camera._handle_system_metrics_changed("entry-1")
        assert not camera._background_tasks._tasks or all(
            task.done() for task in camera._background_tasks._tasks
        )
        assert len(api.bridges) == reads

    asyncio.run(run())
