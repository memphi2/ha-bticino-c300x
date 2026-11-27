"""Home Assistant adds the same camera object again after an entity_id change.

HA 2026.10 removes the entity (async_will_remove_from_hass) and adds the very
same object again; 2026.11 still does that for custom integrations that do not
implement async_entity_id_changed. The camera must come back fully usable.
"""

import asyncio
from types import SimpleNamespace
from typing import Any

from test_camera import (
    C300XDoorbellCamera,
    _FakeEntry,
    _FakeWebRTCProvider,
    _install_fake_webrtc_provider,
    _stub_rtsp_ready,
    camera_ha_boundary,  # noqa: F401
)

OFFER = "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n"


def test_camera_removed_and_added_again_accepts_webrtc_offers(monkeypatch) -> None:
    async def run() -> None:
        entry = _FakeEntry(data={"agent_host": "127.0.0.1", "video_port": 6554})
        resources = entry.runtime_data.resources
        camera = C300XDoorbellCamera(entry)  # type: ignore[arg-type]
        captures: list[tuple[str, str]] = []
        manager = SimpleNamespace(
            enabled=True, latest=None, preview=None,
            capture_requested=lambda key: captures.append(("start", key)),
            capture_ended=lambda key: captures.append(("end", key)),
        )
        background: list[asyncio.Task[Any]] = []

        def create_task(coro: Any) -> asyncio.Task[Any]:
            task = asyncio.create_task(coro)
            background.append(task)
            return task

        camera.hass = SimpleNamespace(  # type: ignore[assignment]
            data={"bticino_c300x": {"stream_snapshots": {entry.entry_id: manager}}},
            bus=SimpleNamespace(async_listen=lambda *_args: lambda: None),
            async_create_task=create_task,
        )
        removers: list[Any] = []
        camera.async_on_remove = removers.append  # type: ignore[method-assign]
        provider = _FakeWebRTCProvider()
        _install_fake_webrtc_provider(monkeypatch, provider)
        _stub_rtsp_ready(camera)

        await camera.async_added_to_hass()
        await camera.async_handle_async_webrtc_offer(OFFER, "before", lambda _m: None)
        assert camera._webrtc_session_ids() == ["before"]
        first_capture = captures[0][1]
        old_tasks, old_sessions = camera._background_tasks, camera._webrtc_sessions

        # Removal as HA runs it: the on-remove callbacks, then the hook.
        for remove in removers:
            remove()
        removers.clear()
        await camera.async_will_remove_from_hass()
        assert provider.closed == ["before"]
        assert ("end", first_capture) in captures
        assert resources.prepare_doorbell_video_stop is None
        assert resources.media_session_count is None

        # Until it is added again the removed camera rejects late work.
        rejected: list[Any] = []
        await camera.async_handle_async_webrtc_offer(OFFER, "gap", rejected.append)
        assert [message.as_dict()["message"] for message in rejected] == ["Camera is unloading"]
        camera._apply_status({"window_available": True})
        assert captures == [("start", first_capture), ("end", first_capture)]

        await camera.async_added_to_hass()
        candidate = SimpleNamespace(candidate="candidate:1 1 udp 1 192.0.2.10 9 typ host")
        await camera.async_on_webrtc_candidate("after", candidate)
        messages: list[Any] = []
        await camera.async_handle_async_webrtc_offer(OFFER, "after", messages.append)
        assert [getattr(message, "as_dict", lambda m=message: m)() for message in messages] == [
            {"type": "answer", "sdp": "v=0\r\n"}
        ]
        assert [session_id for session_id, _sdp in provider.offers] == ["before", "after"]
        assert provider.candidates == [("after", candidate)]
        assert camera._webrtc_session_ids() == ["after"]
        assert resources.media_session_count() == 1
        assert resources.prepare_doorbell_video_stop == camera.async_prepare_doorbell_video_stop
        # The open window the agent reports starts a capture of its own again.
        assert captures[-1][0] == "start" and captures[-1][1] != first_capture
        # The previous lifecycle stays closed for anything that still holds it.
        assert old_tasks.closing is True
        assert camera._webrtc_sessions is not old_sessions

        # Background work runs again: a closed subscription closes its session.
        camera.close_webrtc_session("after")
        await asyncio.gather(*background)
        assert provider.closed == ["before", "after"]
        assert camera._webrtc_session_ids() == []
        assert resources.media_session_count() == 0

    asyncio.run(run())
