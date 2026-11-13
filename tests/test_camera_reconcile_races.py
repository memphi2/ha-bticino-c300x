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


def _video_status(*, active=False):
    return {
        "available": True,
        "window_available": active,
        "media_owner": "agent" if active else "idle",
        "stream_path": "/doorbell-video",
        "audio_stream_path": "/doorbell",
        "bridge": {
            "running": True,
            "clients": int(active),
            "media_active": active,
            "media_owner": "agent" if active else "idle",
            "doorstation_audio_gain_db": 0,
        },
    }


@pytest.mark.parametrize("ready_before_status", [False, True])
def test_idle_reconciliation_preserves_offer_finishing_after_stream_source(
    monkeypatch, ready_before_status,
):
    async def run():
        prepared, finishing_candidates = asyncio.Event(), asyncio.Event()
        release_provider = asyncio.Event()
        status_started, release_status = asyncio.Event(), asyncio.Event()

        class Api(_FakeApi):
            active = False
            delay_idle = False

            async def async_doorbell_video_status(self):
                status = _video_status(active=self.active)
                if self.delay_idle and not self.active:
                    status_started.set()
                    await release_status.wait()
                return status

        class Provider(_FakeWebRTCProvider):
            async def async_handle_async_webrtc_offer(
                self, camera, offer_sdp, session_id, send_message,
            ):
                self.offer_sources.append(await camera.stream_source())
                prepared.set()
                if not ready_before_status:
                    await release_provider.wait()
                send_message({"type": "answer", "sdp": "v=0\r\n"})

            async def async_on_webrtc_candidate(self, session_id, candidate):
                finishing_candidates.set()
                await release_provider.wait()
                await super().async_on_webrtc_candidate(session_id, candidate)

        api, provider = Api(), Provider()
        entry = _FakeEntry(
            data={"agent_host": "192.0.2.1"},
            runtime_data=_FakeRuntimeData(api=api),
        )
        camera = C300XDoorbellCamera(entry)
        camera.hass = SimpleNamespace(async_create_task=asyncio.create_task)
        _stub_rtsp_ready(camera)

        async def lookup(*_args):
            return provider

        monkeypatch.setattr(camera_module, "_async_get_supported_webrtc_provider", lookup)
        if ready_before_status:
            await camera.async_on_webrtc_candidate("new", "initial-candidate")
        messages, tasks = [], []
        try:
            offer = asyncio.create_task(camera.async_handle_async_webrtc_offer(
                "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 0\r\na=recvonly\r\n",
                "new", messages.append,
            ))
            tasks.append(offer)
            await asyncio.wait_for(prepared.wait(), 1)
            if ready_before_status:
                await asyncio.wait_for(finishing_candidates.wait(), 1)
            assert camera._webrtc_sessions.active["new"].ready is ready_before_status
            assert "new" in camera._webrtc_sessions.offers
            assert not camera._rtsp_prepare_lock.locked()

            # Activation leaves an idle native device idle until go2rtc starts
            # RTSP, after stream_source() has returned and released its lock.
            api.delay_idle = True
            reconcile = asyncio.create_task(camera._async_reconcile_local_sessions())
            tasks.append(reconcile)
            await asyncio.wait_for(status_started.wait(), 1)
            api.active = True
            release_provider.set()
            await asyncio.wait_for(offer, 1)
            assert camera._webrtc_sessions.active["new"].ready
            release_status.set()
            await asyncio.wait_for(reconcile, 1)
            assert "new" in camera._webrtc_sessions.active
            assert provider.closed == []
            assert not any(message.get("type") == "closed" for message in messages)

            # Once the offer has finished, a later idle sample must still clean
            # it up; excluding opening offers must not latch the session forever.
            api.active = api.delay_idle = False
            await camera._async_reconcile_local_sessions()
            assert "new" not in camera._webrtc_sessions.active
            assert provider.closed == ["new"]
            assert messages[-1] == {"type": "closed", "reason": "agent_idle_reconcile"}
            assert api.stop_calls == 0
        finally:
            release_status.set()
            release_provider.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await camera.async_will_remove_from_hass()

    asyncio.run(run())


def test_idle_reconciliation_preserves_reused_session_candidates_during_close(monkeypatch):
    async def run():
        closing, release_close = asyncio.Event(), asyncio.Event()
        lookup_started, release_lookup = asyncio.Event(), asyncio.Event()

        class Api(_FakeApi):
            async def async_doorbell_video_status(self):
                return _video_status()

        class OldProvider(_FakeWebRTCProvider):
            async def async_close_session(self, session_id):
                if session_id == "first":
                    closing.set()
                    await release_close.wait()
                super().async_close_session(session_id)

        api, old_provider, replacement_provider = Api(), OldProvider(), _FakeWebRTCProvider()
        entry = _FakeEntry(
            data={"agent_host": "192.0.2.1"},
            runtime_data=_FakeRuntimeData(api=api),
        )
        camera = C300XDoorbellCamera(entry)
        camera.hass = SimpleNamespace(async_create_task=asyncio.create_task)
        _stub_rtsp_ready(camera)
        for session_id in ("first", "reused"):
            camera._webrtc_sessions.active[session_id] = _ProviderWebRTCSession(
                provider=old_provider, owner="doorbell", send_message=lambda _: None,
                wants_audio=True, wants_backchannel=False,
                resource_id="ring:entry-1", ready=True, ring_call=True,
            )

        async def lookup(*_args):
            lookup_started.set()
            await release_lookup.wait()
            return replacement_provider

        monkeypatch.setattr(camera_module, "_async_get_supported_webrtc_provider", lookup)
        tasks = []
        try:
            reconcile = asyncio.create_task(camera._async_reconcile_local_sessions())
            tasks.append(reconcile)
            await asyncio.wait_for(closing.wait(), 1)
            # Replacing another session can remove its old object while the
            # reconciler awaits this provider close. Admission of the new object
            # waits for the prepare lock, but its incoming ICE is already owned.
            offer = asyncio.create_task(camera.async_handle_async_webrtc_offer(
                "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 0\r\na=recvonly\r\n",
                "reused", lambda _: None,
            ))
            tasks.append(offer)
            await asyncio.wait_for(lookup_started.wait(), 1)
            await camera.async_on_webrtc_candidate("reused", "replacement-candidate")
            release_close.set()
            await asyncio.wait_for(reconcile, 1)
            assert camera._webrtc_sessions.candidates["reused"] == ["replacement-candidate"]
            release_lookup.set()
            await asyncio.wait_for(offer, 1)
            assert camera._webrtc_sessions.active["reused"].ready
            assert replacement_provider.candidates == [("reused", "replacement-candidate")]
            assert replacement_provider.closed == []
            assert old_provider.closed.count("reused") == 1
            assert api.stop_calls == 0
        finally:
            release_close.set()
            release_lookup.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await camera.async_will_remove_from_hass()

    asyncio.run(run())
