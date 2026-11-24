"""A ring answered on the station's display keeps HA on "external media".

Replays the agent events of the device capture 2026-11-24 13:37:27-13:38:35:
ring, display answer (*8*2#1#4*11##), the ring leg's close, and the display
call's end (*8*3#1#4*411##) at its 60 s limit.
"""

import asyncio
from types import SimpleNamespace

from test_camera import (
    C300XDoorbellCamera,
    _FakeEntry,
    _FakeGo2RtcWsClient,
    _FakeWebRTCProvider,
    _ProviderWebRTCSession,
    camera_ha_boundary,  # noqa: F401
)

from custom_components.bticino_c300x.camera_media.state_machine import MediaState


def _event(camera, event_key, *, owner, external, **bridge):
    return SimpleNamespace(data={
        "entry_id": camera._entry.entry_id,
        "event_key": event_key,
        "video_available": False,
        "video_window_available": False,
        "media_owner": owner,
        "external_media_active": external,
        "external_owner": "external_media" if external else "",
        "bridge": {"media_owner": owner, "external_media_active": external, **bridge},
    })


def test_display_answered_ring_keeps_external_media_until_the_display_call_ends() -> None:
    async def run():
        camera = C300XDoorbellCamera(_FakeEntry())
        tasks = []
        camera.hass = SimpleNamespace(async_create_task=lambda coro: tasks.append(
            asyncio.create_task(coro)) or tasks[-1])
        provider = _FakeWebRTCProvider()
        provider._sessions = {"ring-preview": _FakeGo2RtcWsClient([])}
        camera._webrtc_sessions.active["ring-preview"] = _ProviderWebRTCSession(
            provider=provider, owner="doorbell", send_message=lambda _m: None,
            wants_audio=False, wants_backchannel=False, resource_id="ring:entry-1",
            ready=True, ring_preview=True,
        )
        camera._handle_agent_event(_event(
            camera, "doorbell_pressed", owner="ring", external=False,
            ring_call_active=True, unanswered_ring_call=True, clients=1,
        ))
        assert camera._last_media_state is MediaState.RING_PENDING

        # The display answered: its view arrives while the ring leg drains ...
        camera._handle_agent_event(_event(
            camera, "doorbell_view_requested", owner="external_media", external=True,
            clients=1,
        ))
        assert camera._last_media_state is MediaState.EXTERNAL_MEDIA_ACTIVE

        # ... then the ring leg's close, which still reports the display's media.
        camera._handle_agent_event(_event(
            camera, "doorbell_media_closed", owner="external_media", external=True,
            clients=0,
        ))
        await asyncio.gather(*tasks)
        assert camera._webrtc_sessions.active == {}
        assert camera._last_media_state is MediaState.EXTERNAL_MEDIA_ACTIVE
        assert camera.extra_state_attributes["external_media_active"] is True
        assert camera.extra_state_attributes["video_owner"] == "external_media"

        # The display call ends (bus *8*3#1#4*411##): HA is idle again.
        camera._handle_agent_event(_event(
            camera, "doorbell_media_closed", owner="idle", external=False, clients=0,
        ))
        await asyncio.gather(*tasks)
        assert camera._last_media_state is MediaState.IDLE
        assert camera.extra_state_attributes["external_media_active"] is False
        assert camera._runtime_data.api.stop_calls == 0

    asyncio.run(run())


def test_ring_close_without_display_still_returns_to_idle() -> None:
    """The unanswered ring's close (no external media) keeps its old meaning."""

    async def run():
        camera = C300XDoorbellCamera(_FakeEntry())
        camera.hass = SimpleNamespace(async_create_task=asyncio.create_task)
        camera._handle_agent_event(_event(
            camera, "doorbell_pressed", owner="ring", external=False,
            ring_call_active=True, unanswered_ring_call=True,
        ))
        camera._handle_agent_event(SimpleNamespace(data={
            "entry_id": camera._entry.entry_id, "event_key": "doorbell_media_closed",
        }))
        assert camera._last_media_state is MediaState.IDLE
        assert camera._external_media_active is False

    asyncio.run(run())
