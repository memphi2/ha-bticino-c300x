"""In-flight event requests must not cross an entry's unload/reload boundary."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.bticino_c300x import webhook
from custom_components.bticino_c300x.camera import C300XDoorbellCamera
from custom_components.bticino_c300x.camera_media.webrtc_session import (
    ProviderWebRTCSession,
)
from custom_components.bticino_c300x.const import (
    CONF_EVENT_WEBHOOK_TOKEN,
    HEADER_EVENT_TOKEN,
)
from custom_components.bticino_c300x.data import (
    BticinoC300XRuntimeData,
    C300XConnectionState,
    C300XEventState,
)


def runtime():
    return BticinoC300XRuntimeData(
        api=SimpleNamespace(),
        event_state=C300XEventState(video_available=True, video_window_available=True),
        connection_state=C300XConnectionState(), capabilities={}, agent_info={},
        loaded_platforms=(),
    )


def entry_for(current):
    return SimpleNamespace(
        entry_id="review", title="Review",
        data={CONF_EVENT_WEBHOOK_TOKEN: "secret"}, options={}, runtime_data=current,
    )


def delayed_request(payload, entered, release):
    class Content:
        async def iter_chunked(self, _size):
            entered.set()
            await release.wait()
            yield json.dumps(payload).encode()

    return SimpleNamespace(
        headers={HEADER_EVENT_TOKEN: "secret"}, method="POST",
        content=Content(), content_length=None,
    )


@pytest.mark.parametrize("transition", ["unchanged", "closed", "replaced", "reloaded", "removed"])
def test_delayed_media_closed_event_cannot_close_replacement_session(monkeypatch, transition):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        old = runtime()
        entry = entry_for(old)
        hass = SimpleNamespace(
            data={}, config=SimpleNamespace(language="en"),
            async_create_task=asyncio.create_task,
        )
        monkeypatch.setattr(webhook, "resolve_doorbell_camera_entity_id", lambda *_: "camera.review")
        request = delayed_request({"type": "doorbell.media.closed"}, entered, release)
        pending = asyncio.create_task(webhook._async_handle_agent_event(hass, entry, old.event_state, request))
        camera = None
        try:
            await asyncio.wait_for(entered.wait(), 1)
            if transition in {"closed", "reloaded"}:
                old.resources.close()
            if transition in {"replaced", "reloaded"}:
                entry.runtime_data = runtime()
            current = entry.runtime_data
            camera = C300XDoorbellCamera(entry)
            camera.hass = hass
            monkeypatch.setattr(camera, "async_write_ha_state", lambda: None)
            monkeypatch.setattr(camera, "_async_wait_for_provider_rtsp_clients_to_drain", AsyncMock())
            provider = SimpleNamespace(async_close_session=AsyncMock())
            messages = []
            camera._webrtc_sessions.active["new-session"] = ProviderWebRTCSession(
                provider=provider, owner="doorbell", send_message=messages.append,
                wants_audio=False, wants_backchannel=False,
                resource_id="doorbell:review", ready=True,
            )
            if transition == "removed":
                del entry.runtime_data
            fired = []

            def fire(_kind, data):
                fired.append(data["event_type"])
                camera._handle_agent_event(SimpleNamespace(data=data))

            hass.bus = SimpleNamespace(async_fire=fire)
            release.set()
            response = await asyncio.wait_for(pending, 1)
            await asyncio.gather(*tuple(camera._background_tasks._tasks))
            if transition == "unchanged":
                assert response.status == 200
                assert fired == ["doorbell_media_closed"]
                provider.async_close_session.assert_awaited_once_with("new-session")
                assert not camera._webrtc_sessions.active
                assert messages == [{"type": "closed", "reason": "doorbell_media_closed"}]
                assert not old.event_state.video_window_available
            else:
                assert response.status == 503
                assert json.loads(response.text) == {"ok": False, "error": "entry_unloaded"}
                assert fired == []
                provider.async_close_session.assert_not_awaited()
                assert "new-session" in camera._webrtc_sessions.active
                assert messages == []
                assert old.event_state.video_window_available
                assert current.event_state.video_window_available
                assert old.event_state.event_sequence == current.event_state.event_sequence == 0
        finally:
            release.set()
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            if camera is not None:
                await camera._background_tasks.close()
                camera._webrtc_sessions.active.clear()
    asyncio.run(run())


@pytest.mark.parametrize("event_type,handler", [
    ("system.metrics_changed", "_apply_system_metrics_event"),
    ("agent.diagnostics_changed", "apply_agent_diagnostics_event"),
])
def test_delayed_diagnostic_event_cannot_write_replacement_runtime(monkeypatch, event_type, handler):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        old = runtime()
        entry = entry_for(old)
        apply_event = Mock(return_value=True)
        monkeypatch.setattr(webhook, handler, apply_event)
        request = delayed_request({"type": event_type}, entered, release)
        pending = asyncio.create_task(webhook._async_handle_agent_event(None, entry, old.event_state, request))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            entry.runtime_data = runtime()
            release.set()
            response = await asyncio.wait_for(pending, 1)
            assert response.status == 503
            apply_event.assert_not_called()
        finally:
            release.set()
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
    asyncio.run(run())
