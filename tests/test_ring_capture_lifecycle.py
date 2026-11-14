"""Ring capture never cleans up a replacement runtime or an observed new call."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_on_demand_capture import _entry

from custom_components.bticino_c300x._api_normalize import normalize_doorbell_video
from custom_components.bticino_c300x.const import EVENT_AGENT_EVENT_RECEIVED
from custom_components.bticino_c300x.use_cases import ring_capture


class _Bus:
    def __init__(self):
        self.listeners = []

    def async_listen(self, event_type, callback):
        assert event_type == EVENT_AGENT_EVENT_RECEIVED
        self.listeners.append(callback)
        return lambda: self.listeners.remove(callback)

    def fire(self, entry_id, event_type):
        for callback in tuple(self.listeners):
            callback(SimpleNamespace(data={"entry_id": entry_id, "event_type": event_type}))


@pytest.fixture
def capture(monkeypatch):
    status = {
        "media_owner": "ring", "last_media_started_at": "2026-11-14T12:00:00Z",
        "bridge": {"media_owner": "ring", "clients": 0, "ring_call_active": True},
    }
    entry = _entry(status)
    api = entry.runtime_data.api

    async def answer():
        status["bridge"].update(ring_answered=True, ring_audio_active=True)

    api.async_answer_doorbell_call = AsyncMock(side_effect=answer)
    api.async_hangup_doorbell_call = AsyncMock()
    entry.runtime_data.resources.prepare_doorbell_video_stop = AsyncMock()
    recording = AsyncMock(return_value={"capture_id": "test"})
    monkeypatch.setattr(ring_capture, "async_capture_doorbell_ring_call", recording)
    hass = SimpleNamespace(bus=_Bus())
    return ring_capture.RingCaptureUseCase(hass, entry), entry, hass.bus, recording, status


@pytest.mark.parametrize("unload", [False, True])
def test_replaced_runtime_is_never_cleaned_up(capture, unload):
    use_case, entry, bus, recording, _ = capture

    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        old = entry.runtime_data
        new = _entry().runtime_data
        new.resources.prepare_doorbell_video_stop = AsyncMock()

        async def record(*args, **kwargs):
            started.set()
            await release.wait()

        recording.side_effect = record
        task = asyncio.create_task(use_case.capture())
        await started.wait()
        assert old.resources.ring_capture_task is task
        if unload:
            old.resources.close()
        entry.runtime_data = new
        release.set()
        if unload:
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await task
        old.api.async_hangup_doorbell_call.assert_not_awaited()
        new.api.async_hangup_doorbell_call.assert_not_awaited()
        new.resources.prepare_doorbell_video_stop.assert_not_awaited()
        assert old.resources.ring_capture_task is None
        assert bus.listeners == []

    asyncio.run(run())


def test_replacement_during_prepare_does_not_hang_up_either_runtime(capture):
    use_case, entry, bus, _, _ = capture
    old = entry.runtime_data
    new = _entry().runtime_data

    async def replace():
        entry.runtime_data = new

    old.resources.prepare_doorbell_video_stop.side_effect = replace
    asyncio.run(use_case.capture())
    old.api.async_hangup_doorbell_call.assert_not_awaited()
    new.api.async_hangup_doorbell_call.assert_not_awaited()
    assert old.resources.ring_capture_task is None
    assert bus.listeners == []


def test_replacement_during_answer_status_does_not_answer_new_runtime(capture):
    use_case, entry, _, recording, status = capture
    old = entry.runtime_data
    new = _entry().runtime_data
    reads = 0

    async def read():
        nonlocal reads
        reads += 1
        if reads == 2:
            entry.runtime_data = new
        return status

    old.api.async_doorbell_video_status.side_effect = read
    with pytest.raises(HomeAssistantError, match="reloaded"):
        asyncio.run(use_case.capture())
    old.api.async_answer_doorbell_call.assert_not_awaited()
    new.api.async_answer_doorbell_call.assert_not_awaited()
    recording.assert_not_awaited()


@pytest.mark.parametrize("event", [
    "doorbell_pressed", "doorbell_media_closed", "call_ended",
    "home_call_started", "agent_restarted",
])
def test_call_transition_in_same_runtime_cancels_without_hangup(capture, event):
    use_case, entry, bus, recording, _ = capture
    runtime = entry.runtime_data

    async def record(*args, **kwargs):
        bus.fire(entry.entry_id, event)
        await asyncio.sleep(0)

    recording.side_effect = record
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(use_case.capture())
    runtime.api.async_hangup_doorbell_call.assert_not_awaited()
    runtime.resources.prepare_doorbell_video_stop.assert_not_awaited()
    assert runtime.resources.ring_capture_task is None
    assert bus.listeners == []


@pytest.mark.parametrize("during_prepare", [False, True])
@pytest.mark.parametrize("changed", ["timestamp", "idle", "unknown", "status_error"])
def test_ambiguous_or_replaced_call_status_prevents_hangup(capture, changed, during_prepare):
    use_case, entry, _, recording, status = capture
    runtime = entry.runtime_data

    async def change(*args, **kwargs):
        if changed == "timestamp":
            status["last_media_started_at"] = "2026-11-14T12:00:01Z"
        elif changed == "idle":
            status["media_owner"] = "idle"
        elif changed == "unknown":
            status.pop("last_media_started_at")
        else:
            runtime.api.async_doorbell_video_status.side_effect = RuntimeError("offline")

    if during_prepare:
        runtime.resources.prepare_doorbell_video_stop.side_effect = change
    else:
        recording.side_effect = change
    asyncio.run(use_case.capture())
    runtime.api.async_hangup_doorbell_call.assert_not_awaited()
    if not during_prepare:
        runtime.resources.prepare_doorbell_video_stop.assert_not_awaited()


@pytest.mark.parametrize("missing", ["timestamp", "event_bus"])
def test_missing_call_ownership_evidence_skips_automatic_hangup(capture, missing):
    use_case, entry, _, _, status = capture
    if missing == "timestamp":
        status.pop("last_media_started_at")
    else:
        use_case._hass = SimpleNamespace()
    asyncio.run(use_case.capture())
    entry.runtime_data.api.async_hangup_doorbell_call.assert_not_awaited()
    entry.runtime_data.resources.prepare_doorbell_video_stop.assert_not_awaited()


@pytest.mark.parametrize("answering", [False, True])
def test_capture_does_not_claim_previously_answered_call(capture, answering):
    use_case, entry, _, _, status = capture
    reads = 0

    async def read():
        nonlocal reads
        reads += 1
        if answering and reads < 3:
            status["bridge"]["ring_answer_requested"] = True
        else:
            status["bridge"]["ring_answered"] = True
        return status

    entry.runtime_data.api.async_doorbell_video_status.side_effect = read
    asyncio.run(use_case.capture())
    entry.runtime_data.api.async_answer_doorbell_call.assert_not_awaited()
    entry.runtime_data.api.async_hangup_doorbell_call.assert_not_awaited()


def test_caller_cancellation_cleans_up_only_owned_call(capture):
    use_case, entry, bus, recording, _ = capture
    runtime = entry.runtime_data

    async def run():
        started = asyncio.Event()

        async def record(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()

        recording.side_effect = record
        task = asyncio.create_task(use_case.capture())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        runtime.api.async_hangup_doorbell_call.assert_awaited_once()
        assert runtime.resources.ring_capture_task is None
        assert bus.listeners == []

    asyncio.run(run())


def test_other_entry_and_unrelated_events_preserve_owned_cleanup(capture):
    use_case, entry, bus, recording, _ = capture

    async def record(*args, **kwargs):
        bus.fire("other-entry", "doorbell_pressed")
        bus.fire(entry.entry_id, "system_metrics_changed")
        await asyncio.sleep(0)

    recording.side_effect = record
    asyncio.run(use_case.capture())
    entry.runtime_data.api.async_hangup_doorbell_call.assert_awaited_once()
    assert bus.listeners == []


def test_call_guard_uses_real_normalized_status_bridge_timestamp(capture):
    use_case, entry, _, _, status = capture
    status["bridge"]["last_media_started_at"] = status.pop("last_media_started_at")
    entry.runtime_data.api.async_doorbell_video_status.side_effect = (
        lambda: normalize_doorbell_video(status)
    )
    asyncio.run(use_case.capture())
    entry.runtime_data.api.async_hangup_doorbell_call.assert_awaited_once()


def test_own_hangup_end_event_does_not_cancel_successful_capture(capture):
    use_case, entry, bus, _, _ = capture

    async def hangup():
        bus.fire(entry.entry_id, "doorbell_media_closed")
        await asyncio.sleep(0)

    entry.runtime_data.api.async_hangup_doorbell_call.side_effect = hangup
    assert asyncio.run(use_case.capture()) == {"capture_id": "test"}
    assert bus.listeners == []


@pytest.mark.parametrize("stage", ["initial", "after_gain"])
def test_capture_answer_preserves_capability_check(capture, monkeypatch, stage):
    use_case, entry, _, recording, _ = capture

    def disable():
        entry.runtime_data.capabilities["doorbell_call"] = {"supported": False}

    if stage == "initial":
        disable()
    else:
        async def gain(*args, **kwargs):
            disable()
        monkeypatch.setattr(ring_capture, "async_ensure_doorstation_audio_gain", gain)
    with pytest.raises(HomeAssistantError):
        asyncio.run(use_case.capture())
    entry.runtime_data.api.async_answer_doorbell_call.assert_not_awaited()
    recording.assert_not_awaited()


@pytest.mark.parametrize("event", ["call_ended", "doorbell_media_closed", "doorbell_pressed"])
def test_call_event_during_cleanup_does_not_cancel_a_finished_capture(capture, event):
    """The clip exists; the call ending while the cleanup reads the status is no cancel."""

    use_case, entry, bus, _, status = capture
    api = entry.runtime_data.api
    original_status = api.async_doorbell_video_status
    recorded = False

    async def record(*args, **kwargs):
        nonlocal recorded
        recorded = True
        return {"capture_id": "test"}

    async def read_status(*args, **kwargs):
        if recorded:
            bus.fire(entry.entry_id, event)
            await asyncio.sleep(0)
        return await original_status(*args, **kwargs)

    capture[3].side_effect = record
    api.async_doorbell_video_status = read_status

    assert asyncio.run(use_case.capture()) == {"capture_id": "test"}
    # The call changed: no automatic hangup of what may be a new call.
    api.async_hangup_doorbell_call.assert_not_awaited()
    assert bus.listeners == []
