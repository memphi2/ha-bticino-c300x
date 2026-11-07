"""Pending offers must not outlive explicit or device-reported media stops."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_camera import (
    C300XDoorbellCamera,
    _FakeEntry,
    _FakeWebRTCProvider,
    _stub_rtsp_ready,
    camera_ha_boundary,  # noqa: F401
    camera_module,
)


@pytest.mark.parametrize("owner", ["doorbell", "home_call"])
@pytest.mark.parametrize("stage", ["provider_lookup", "provider_before_source"])
@pytest.mark.parametrize("stop_kind", ["explicit", "event"])
def test_stop_cancels_pending_offer(monkeypatch, owner, stage, stop_kind):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        entry = _FakeEntry(data={"agent_host": "192.0.2.1", "video_port": 6554})
        api = entry.runtime_data.api
        camera = C300XDoorbellCamera(entry)
        background = []

        def create_task(coro):
            task = asyncio.create_task(coro)
            background.append(task)
            return task

        camera.hass = SimpleNamespace(async_create_task=create_task)
        _stub_rtsp_ready(camera)

        class Provider(_FakeWebRTCProvider):
            async def async_handle_async_webrtc_offer(self, camera, offer, session_id, send):
                if stage == "provider_before_source":
                    entered.set()
                    await release.wait()
                await super().async_handle_async_webrtc_offer(camera, offer, session_id, send)

        provider = Provider()

        async def lookup(*_):
            if stage == "provider_lookup":
                entered.set()
                await release.wait()
            return provider

        monkeypatch.setattr(camera_module, "_async_get_supported_webrtc_provider", lookup)
        handler = camera.async_handle_home_call_webrtc_offer if owner == "home_call" else camera.async_handle_async_webrtc_offer
        prepare = camera.async_prepare_home_call_stop if owner == "home_call" else camera.async_prepare_doorbell_video_stop
        stop = api.async_stop_home_call if owner == "home_call" else api.async_stop_doorbell_video
        messages = []
        offer = asyncio.create_task(handler(
            "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 0\r\na=recvonly\r\n", "pending", messages.append,
        ))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            if stop_kind == "explicit":
                await prepare()
                await stop()
            else:
                camera._close_webrtc_sessions_from_event(owner, "ended")
                await asyncio.gather(*background)
            before = (list(api.activate_calls), list(api.home_call_start_calls))
            release.set()
            await asyncio.gather(offer, return_exceptions=True)
            assert offer.cancelled()
            assert not camera._webrtc_sessions.active
            assert not camera._webrtc_sessions.offers
            assert before == (api.activate_calls, api.home_call_start_calls)
            assert [message["type"] for message in messages] == ["closed"]
        finally:
            release.set()
            offer.cancel()
            await asyncio.gather(offer, return_exceptions=True)
            await camera.async_will_remove_from_hass()

    asyncio.run(run())


@pytest.mark.parametrize("owner", ["doorbell", "home_call"])
@pytest.mark.parametrize("fails", [False, True])
def test_stop_scope_blocks_new_offer_until_device_reply(monkeypatch, owner, fails):
    from custom_components.bticino_c300x.use_cases.doorbell_video import (
        DoorbellVideoUseCase,
    )
    from custom_components.bticino_c300x.use_cases.home_call import HomeCallUseCase

    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        entry = _FakeEntry(data={"agent_host": "192.0.2.1", "video_enabled": True})
        entry.runtime_data.capabilities = {
            "doorbell_video": {"supported": True}, "home_call": {"supported": True},
        }
        api = entry.runtime_data.api
        api.async_doorbell_video_status = AsyncMock(side_effect=RuntimeError("unknown"))

        async def stop():
            entered.set()
            await release.wait()
            if fails:
                raise RuntimeError("stop failed")

        setattr(api, "async_stop_home_call" if owner == "home_call" else "async_stop_doorbell_video", stop)
        camera = C300XDoorbellCamera(entry)
        lookup = AsyncMock(return_value=None)
        monkeypatch.setattr(camera_module, "_async_get_supported_webrtc_provider", lookup)
        use_case = HomeCallUseCase(entry) if owner == "home_call" else DoorbellVideoUseCase(entry)
        pending = asyncio.create_task(use_case.stop())
        await entered.wait()
        messages = []
        await camera._async_handle_webrtc_offer("v=0", "new", messages.append, owner=owner)
        assert len(messages) == 1 and messages[0].as_dict()["type"] == "error"
        lookup.assert_not_called()
        release.set()
        result = await asyncio.gather(pending, return_exceptions=True)
        assert isinstance(result[0], Exception) == fails
        assert not entry.runtime_data.resources.media_stop_counts

    asyncio.run(run())


def test_late_provider_messages_and_stream_requests_cannot_reopen_session(monkeypatch):
    from contextvars import copy_context

    async def run():
        entry = _FakeEntry(data={"agent_host": "192.0.2.1"})
        camera = C300XDoorbellCamera(entry)
        camera.hass = SimpleNamespace(async_create_task=asyncio.create_task)
        _stub_rtsp_ready(camera)
        saved = {}

        class Provider(_FakeWebRTCProvider):
            async def async_handle_async_webrtc_offer(self, camera, offer, session_id, send):
                saved.update(send=send, context=copy_context())
                await super().async_handle_async_webrtc_offer(camera, offer, session_id, send)

        monkeypatch.setattr(camera_module, "_async_get_supported_webrtc_provider", AsyncMock(return_value=Provider()))
        messages = []
        await camera.async_handle_async_webrtc_offer("v=0", "one", messages.append)
        await camera.async_prepare_doorbell_video_stop()
        before = list(messages)
        saved["send"]({"type": "answer", "sdp": "late"})
        assert messages == before
        with pytest.raises(camera_module.HomeAssistantError, match="closed"):
            await asyncio.create_task(camera.stream_source(), context=saved["context"])
        await camera.async_will_remove_from_hass()

    asyncio.run(run())
