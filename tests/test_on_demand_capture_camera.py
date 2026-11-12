"""Capture admission includes opening and closing camera consumers."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from test_camera import (
    C300XDoorbellCamera,
    _FakeEntry,
    _FakeWebRTCProvider,
    _stub_rtsp_ready,
    _webrtc_message_value,
    camera_ha_boundary,  # noqa: F401
    camera_module,
)
from test_on_demand_capture import _idle

from custom_components.bticino_c300x.use_cases.ring_capture import RingCaptureUseCase


def _camera_entry():
    entry = _FakeEntry(data={"agent_host": "192.0.2.1", "video_enabled": True})
    entry.runtime_data.capabilities = {"doorbell_video": {"supported": True}}
    entry.runtime_data.api.async_doorbell_video_status = AsyncMock(return_value=_idle())
    camera = C300XDoorbellCamera(entry)
    camera.hass = SimpleNamespace(async_create_task=asyncio.create_task)
    entry.runtime_data.resources.media_session_count = camera._capture_media_session_count
    _stub_rtsp_ready(camera)
    return entry, camera


def test_capture_does_not_take_over_an_offer_waiting_for_provider(monkeypatch):
    async def run():
        entry, camera = _camera_entry()
        entered, release = asyncio.Event(), asyncio.Event()

        async def lookup(*args):
            entered.set()
            await release.wait()
            return _FakeWebRTCProvider()

        monkeypatch.setattr(camera_module, "_async_get_supported_webrtc_provider", lookup)
        offer = asyncio.create_task(camera.async_handle_async_webrtc_offer("v=0", "pending", lambda m: None))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            assert camera._capture_media_session_count() == 1
            with pytest.raises(ServiceValidationError) as err:
                await RingCaptureUseCase(SimpleNamespace(), entry).capture(capture_mode="on_demand")
            assert err.value.translation_key == "on_demand_capture_busy"
            assert entry.runtime_data.api.activate_calls == []
            assert not offer.done()
        finally:
            offer.cancel()
            release.set()
            await asyncio.gather(offer, return_exceptions=True)
            await camera.async_will_remove_from_hass()

    asyncio.run(run())


@pytest.mark.parametrize("owner", ["doorbell", "home_call"])
def test_capture_reservation_rejects_new_and_already_opening_offers(monkeypatch, owner):
    async def run():
        entry, camera = _camera_entry()
        entered, release = asyncio.Event(), asyncio.Event()
        messages = []

        async def lookup(*args):
            entered.set()
            await release.wait()
            return _FakeWebRTCProvider()

        monkeypatch.setattr(camera_module, "_async_get_supported_webrtc_provider", lookup)
        handler = camera.async_handle_home_call_webrtc_offer if owner == "home_call" else camera.async_handle_async_webrtc_offer
        offer = asyncio.create_task(handler(
            "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 0\r\na=recvonly\r\n", "pending", messages.append,
        ))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            entry.runtime_data.resources.on_demand_capture_active = True
            await handler("v=0", "new", messages.append)
            with pytest.raises(HomeAssistantError, match="capture is active"):
                await camera.stream_source()
            release.set()
            await offer
            assert not camera._webrtc_sessions.active
            assert entry.runtime_data.api.activate_calls == []
            assert entry.runtime_data.api.home_call_start_calls == []
            assert len(messages) == 2
            assert all(_webrtc_message_value(message, "type") == "error" for message in messages)
        finally:
            entry.runtime_data.resources.on_demand_capture_active = False
            release.set()
            offer.cancel()
            await asyncio.gather(offer, return_exceptions=True)
            await camera.async_will_remove_from_hass()

    asyncio.run(run())


@pytest.mark.parametrize("owner", ["doorbell", "home_call"])
def test_rtsp_prepare_rechecks_capture_after_waiting_for_lock(owner):
    async def run():
        entry, camera = _camera_entry()
        orchestrator = camera._rtsp_orchestrator
        prepare = orchestrator.async_prepare_home_call_rtsp_stream if owner == "home_call" else orchestrator.async_prepare_rtsp_stream
        await camera._rtsp_prepare_lock.acquire()
        task = asyncio.create_task(prepare())
        await asyncio.sleep(0)
        entry.runtime_data.resources.on_demand_capture_active = True
        camera._rtsp_prepare_lock.release()
        with pytest.raises(HomeAssistantError, match="capture is active"):
            await task
        assert entry.runtime_data.api.activate_calls == []
        assert entry.runtime_data.api.home_call_start_calls == []
        entry.runtime_data.resources.on_demand_capture_active = False
        await camera.async_will_remove_from_hass()

    asyncio.run(run())


def test_capture_waits_for_closing_provider_to_finish_its_stop(monkeypatch):
    async def run():
        entry, camera = _camera_entry()
        entered, release = asyncio.Event(), asyncio.Event()
        camera._webrtc_sessions.active["closing"] = camera_module._ProviderWebRTCSession(
            provider=_FakeWebRTCProvider(), owner="doorbell", send_message=lambda m: None,
            wants_audio=False, wants_backchannel=False, resource_id="doorbell:test", ready=True,
        )

        async def close(*args):
            entered.set()
            await release.wait()
            return "async"

        monkeypatch.setattr(camera_module, "async_close_provider_session", close)
        camera._async_wait_for_provider_rtsp_clients_to_drain = AsyncMock()
        closing = asyncio.create_task(camera._async_close_webrtc_session("closing", stop_media=True))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            assert not camera._webrtc_sessions.active
            assert camera._capture_media_session_count() == 1
            with pytest.raises(ServiceValidationError) as err:
                await RingCaptureUseCase(SimpleNamespace(), entry).capture(capture_mode="on_demand")
            assert err.value.translation_key == "on_demand_capture_busy"
            assert entry.runtime_data.api.activate_calls == []
            release.set()
            await closing
            assert camera._capture_media_session_count() == 0
        finally:
            release.set()
            await closing
            await camera.async_will_remove_from_hass()

    asyncio.run(run())
