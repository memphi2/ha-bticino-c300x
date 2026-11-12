"""An old idle reply must not close a newly started doorbell stream."""

import asyncio
from types import SimpleNamespace

import pytest
from test_camera import (
    C300XDoorbellCamera,
    _FakeApi,
    _FakeEntry,
    _FakeRuntimeData,
    _FakeWebRTCProvider,
    _ProviderWebRTCSession,
    _stub_rtsp_ready,
    camera_ha_boundary,  # noqa: F401
    camera_module,
)


@pytest.mark.parametrize("start_first", [False, True])
def test_idle_reconciliation_cannot_close_new_doorbell_stream(monkeypatch, start_first):
    async def run():
        status_started, release_status = asyncio.Event(), asyncio.Event()
        start_started, release_start = asyncio.Event(), asyncio.Event()
        lookup_started = asyncio.Event()

        class Api(_FakeApi):
            active = False
            delay_idle = False

            async def async_doorbell_video_status(self):
                status = await super().async_doorbell_video_status()
                status.update(
                    window_available=self.active,
                    media_owner="agent" if self.active else "idle",
                    bridge={
                        "clients": int(self.active),
                        "media_active": self.active,
                        "media_owner": "agent" if self.active else "idle",
                    },
                )
                if self.delay_idle and not self.active:
                    status_started.set()
                    await release_status.wait()
                return status

            async def async_activate_doorbell_video(self, audio=True):
                start_started.set()
                if start_first:
                    await release_start.wait()
                self.active = True
                return await super().async_activate_doorbell_video(audio)

        api = Api()
        entry = _FakeEntry(
            data={"agent_host": "192.0.2.1"},
            runtime_data=_FakeRuntimeData(api=api),
        )
        camera = C300XDoorbellCamera(entry)
        camera.hass = SimpleNamespace(async_create_task=asyncio.create_task)
        provider = _FakeWebRTCProvider()
        _stub_rtsp_ready(camera)

        async def lookup(*_args):
            lookup_started.set()
            return provider

        monkeypatch.setattr(camera_module, "_async_get_supported_webrtc_provider", lookup)
        camera._webrtc_sessions.active["old"] = _ProviderWebRTCSession(
            provider=provider, owner="doorbell", send_message=lambda _: None,
            wants_audio=True, wants_backchannel=False,
            resource_id="doorbell:entry-1:audio", ready=True,
        )
        messages = []
        tasks = []

        def start_offer():
            task = asyncio.create_task(camera.async_handle_async_webrtc_offer(
                "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 0\r\na=recvonly\r\n",
                "new", messages.append,
            ))
            tasks.append(task)
            return task

        try:
            if start_first:
                offer = start_offer()
                await asyncio.wait_for(start_started.wait(), 1)
                api.delay_idle = True
                reconcile = asyncio.create_task(camera._async_reconcile_local_sessions())
                tasks.append(reconcile)
                await asyncio.sleep(0)
                release_start.set()
                await asyncio.wait_for(offer, 1)
                release_status.set()
            else:
                api.delay_idle = True
                reconcile = asyncio.create_task(camera._async_reconcile_local_sessions())
                tasks.append(reconcile)
                await asyncio.wait_for(status_started.wait(), 1)
                # Only the reconciliation reply remains held. New requests see
                # current device state and can complete the browser's offer.
                api.delay_idle = False
                offer = start_offer()
                await asyncio.wait_for(lookup_started.wait(), 1)
                release_status.set()
            await asyncio.wait_for(asyncio.gather(*tasks), 1)
            assert "new" in camera._webrtc_sessions.active
            assert camera._webrtc_sessions.active["new"].ready
            assert "new" not in provider.closed
            assert not any(message.get("type") == "closed" for message in messages)
            assert api.stop_calls == 0
        finally:
            release_status.set()
            release_start.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await camera.async_will_remove_from_hass()

    asyncio.run(run())
