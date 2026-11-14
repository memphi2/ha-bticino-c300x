"""Concurrent audio/video offers share one native on-demand source."""

import asyncio
from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_camera import (
    C300XDoorbellCamera,
    _FakeApi,
    _FakeEntry,
    _FakeRuntimeData,
    _FakeWebRTCProvider,
    _install_fake_webrtc_provider,
    _stub_rtsp_ready,
    agent_diagnostics,
)


@pytest.mark.parametrize("failing_audio", [False, True])
@pytest.mark.parametrize("failure", ["exception", "cancel", "provider_error"])
def test_failed_offer_does_not_stop_shared_source(monkeypatch, failing_audio, failure):
    async def run():
        first_source, fail_first = asyncio.Event(), asyncio.Event()

        class Api(_FakeApi):
            clients = 0

            async def async_doorbell_video_status(self):
                status = await super().async_doorbell_video_status()
                owner = "agent" if self.activate_calls else "idle"
                status.update(media_owner=owner, window_available=bool(self.activate_calls))
                status["bridge"].update(media_owner=owner, clients=self.clients, max_clients=1)
                return status

        api = Api()

        class Provider(_FakeWebRTCProvider):
            async def async_handle_async_webrtc_offer(self, camera, offer, sid, send):
                self.offer_sources.append(await camera.stream_source())
                if sid == "failed":
                    first_source.set()
                    await fail_first.wait()
                    if failure == "exception":
                        raise HomeAssistantError("negotiation failed")
                    send({"type": "error", "code": "test", "message": "failed"})
                    return
                api.clients = 1
                send({"type": "answer", "sdp": "v=0\r\n"})

        provider = Provider()
        entry = _FakeEntry(data={"agent_host": "192.0.2.10"}, runtime_data=_FakeRuntimeData(api=api))
        camera = C300XDoorbellCamera(entry)
        camera.hass = SimpleNamespace()
        _stub_rtsp_ready(camera)
        _install_fake_webrtc_provider(monkeypatch, provider)
        monkeypatch.setattr(C300XDoorbellCamera, "async_write_ha_state", lambda _: None)
        monkeypatch.setattr(agent_diagnostics, "async_dispatcher_send", lambda *_: None)
        video = "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\na=recvonly\r\n"
        audio = "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=recvonly\r\n"
        first = asyncio.create_task(camera.async_handle_async_webrtc_offer(
            video + (audio if failing_audio else ""), "failed", lambda _: None,
        ))
        try:
            await asyncio.wait_for(first_source.wait(), 2)
            await camera.async_handle_async_webrtc_offer(
                video + ("" if failing_audio else audio), "survivor", lambda _: None,
            )
            if failure == "cancel":
                first.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await first
            else:
                fail_first.set()
                await first
            assert camera._webrtc_session_ids() == ["survivor"]
            assert camera._webrtc_sessions.active["survivor"].ready
            assert provider.offer_sources == ["rtsp://192.0.2.10:6554/doorbell"] * 2
            assert provider.closed == ["failed"]
            assert api.stop_calls == 0
            api.clients = 0
            await camera._async_close_webrtc_session("survivor", stop_media=True)
            assert api.stop_calls == 1
        finally:
            if not first.done():
                first.cancel()
            await asyncio.gather(first, return_exceptions=True)

    asyncio.run(run())
