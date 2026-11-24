"""Ring capture never cleans up a replacement runtime or an observed new call."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from test_on_demand_capture import _entry

from custom_components.bticino_c300x._api_normalize import normalize_doorbell_video
from custom_components.bticino_c300x.camera_media.session_lifecycle import (
    media_owner_stopping,
    media_stop_scope,
)
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


@pytest.mark.parametrize("during_prepare", [False, True])
@pytest.mark.parametrize("clients", [1, 2, "missing", None, "0", "invalid", False, True, 0.0, -1, [], {}])
def test_remaining_or_unknown_clients_skip_cleanup_preserving_result(
    capture, clients, during_prepare
):
    use_case, entry, bus, recording, status = capture
    runtime = entry.runtime_data

    async def change(*args, **kwargs):
        if clients == "missing":
            status["bridge"].pop("clients")
        else:
            status["bridge"]["clients"] = clients
        return {"capture_id": "test"}

    if during_prepare:
        runtime.resources.prepare_doorbell_video_stop.side_effect = change
    else:
        recording.side_effect = change

    assert asyncio.run(use_case.capture()) == {"capture_id": "test"}
    runtime.api.async_hangup_doorbell_call.assert_not_awaited()
    if during_prepare:
        runtime.resources.prepare_doorbell_video_stop.assert_awaited_once()
    else:
        runtime.resources.prepare_doorbell_video_stop.assert_not_awaited()
    assert runtime.resources.ring_capture_task is None
    assert not media_owner_stopping(runtime.resources, "doorbell")
    assert bus.listeners == []


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


@pytest.mark.parametrize("stage", ["fresh_status", "after_gain"])
@pytest.mark.parametrize("consumer", ["native", "local_offer"])
def test_new_client_before_answer_rejects_without_answer_or_cleanup(capture, monkeypatch, stage, consumer):
    use_case, entry, bus, recording, status = capture
    runtime = entry.runtime_data
    reads = 0
    local_sessions = 0
    runtime.resources.media_session_count = lambda: local_sessions

    def connect():
        nonlocal local_sessions
        if consumer == "native":
            status["bridge"]["clients"] = 1
        else:
            local_sessions = 1

    async def read():
        nonlocal reads
        reads += 1
        if stage == "fresh_status" and reads == 2:
            connect()
        return status

    async def gain(*args, **kwargs):
        assert media_owner_stopping(runtime.resources, "doorbell")
        if stage == "after_gain":
            connect()

    gain_sync = AsyncMock(side_effect=gain)
    monkeypatch.setattr(ring_capture, "async_ensure_doorstation_audio_gain", gain_sync)
    runtime.api.async_doorbell_video_status.side_effect = read
    with pytest.raises(ServiceValidationError) as err:
        asyncio.run(use_case.capture())
    assert err.value.translation_key == "ring_capture_busy"
    runtime.api.async_answer_doorbell_call.assert_not_awaited()
    runtime.api.async_hangup_doorbell_call.assert_not_awaited()
    runtime.resources.prepare_doorbell_video_stop.assert_not_awaited()
    recording.assert_not_awaited()
    assert gain_sync.await_count == (stage == "after_gain")
    assert runtime.resources.ring_capture_task is None
    assert runtime.resources.media_stop_counts == {}
    assert bus.listeners == []


def test_answer_admission_remains_reserved_through_recording_and_cleanup(capture):
    use_case, entry, _, recording, _ = capture
    runtime = entry.runtime_data
    original_answer = runtime.api.async_answer_doorbell_call.side_effect

    async def answer():
        assert media_owner_stopping(runtime.resources, "doorbell")
        await original_answer()

    async def record(*args, **kwargs):
        assert media_owner_stopping(runtime.resources, "doorbell")
        return {"capture_id": "test"}

    async def prepare():
        assert media_owner_stopping(runtime.resources, "doorbell")

    runtime.api.async_answer_doorbell_call.side_effect = answer
    recording.side_effect = record
    runtime.resources.prepare_doorbell_video_stop.side_effect = prepare
    assert asyncio.run(use_case.capture()) == {"capture_id": "test"}
    assert runtime.resources.media_stop_counts == {}


def test_existing_media_stop_rejects_capture_without_touching_call(capture):
    use_case, entry, _, recording, _ = capture
    runtime = entry.runtime_data
    with media_stop_scope(runtime.resources, "doorbell"):
        with pytest.raises(ServiceValidationError) as err:
            asyncio.run(use_case.capture())
        assert err.value.translation_key == "ring_capture_busy"
        assert runtime.resources.media_stop_counts == {"doorbell": 1}
    runtime.api.async_answer_doorbell_call.assert_not_awaited()
    runtime.api.async_hangup_doorbell_call.assert_not_awaited()
    runtime.resources.prepare_doorbell_video_stop.assert_not_awaited()
    recording.assert_not_awaited()


def test_answer_during_gain_sync_is_not_claimed_for_cleanup(capture, monkeypatch):
    use_case, entry, _, _, status = capture

    async def gain(*args, **kwargs):
        status["bridge"].update(ring_answered=True, ring_audio_active=True)

    monkeypatch.setattr(ring_capture, "async_ensure_doorstation_audio_gain", gain)
    assert asyncio.run(use_case.capture()) == {"capture_id": "test"}
    entry.runtime_data.api.async_answer_doorbell_call.assert_not_awaited()
    entry.runtime_data.api.async_hangup_doorbell_call.assert_not_awaited()
    entry.runtime_data.resources.prepare_doorbell_video_stop.assert_not_awaited()
    assert entry.runtime_data.resources.media_stop_counts == {}


def test_video_only_ring_capture_does_not_reserve_answer_admission(capture):
    use_case, entry, _, recording, _ = capture

    async def record(*args, **kwargs):
        assert not media_owner_stopping(entry.runtime_data.resources, "doorbell")
        return {"capture_id": "test"}

    recording.side_effect = record
    assert asyncio.run(use_case.capture(include_audio=False)) == {"capture_id": "test"}
    entry.runtime_data.api.async_answer_doorbell_call.assert_not_awaited()


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


def test_journal_attachment_cannot_cancel_a_finished_capture(capture, monkeypatch):
    use_case, entry, bus, recording, _ = capture

    async def attach(key, result):
        assert key == "visit"
        assert result == recording.return_value
        bus.fire(entry.entry_id, "doorbell_pressed")
        await asyncio.sleep(0)

    journal = SimpleNamespace(active="visit", attach_clip=AsyncMock(side_effect=attach))
    monkeypatch.setattr(ring_capture, "get_journal", lambda *args: journal)

    async def run():
        result = await use_case.capture()
        assert result == recording.return_value
        journal.attach_clip.assert_awaited_once()
        entry.runtime_data.api.async_hangup_doorbell_call.assert_not_awaited()

    asyncio.run(run())


def test_journal_does_not_claim_user_supplied_output_paths(capture, monkeypatch):
    use_case, _, _, recording, _ = capture
    journal = SimpleNamespace(active="visit", attach_clip=AsyncMock())
    monkeypatch.setattr(ring_capture, "get_journal", lambda *args: journal)
    assert asyncio.run(use_case.capture(output_path="/media/c300x/user.mp4", include_audio=False)) == recording.return_value
    journal.attach_clip.assert_not_awaited()


@pytest.mark.parametrize("failure", ["status_read", "ring_ended", "answer_timeout", "hangup"])
def test_agent_failures_are_not_reported_as_invalid_input(capture, monkeypatch, failure):
    """An unreachable agent or a call the device dropped is a device failure:
    HomeAssistantError, never ServiceValidationError (invalid service input)."""

    use_case, entry, _, recording, status = capture
    api = entry.runtime_data.api
    if failure == "status_read":
        api.async_doorbell_video_status.side_effect = RuntimeError("agent offline")
    elif failure == "hangup":
        api.async_hangup_doorbell_call.side_effect = RuntimeError("agent offline")
    else:
        monkeypatch.setattr(ring_capture, "_RING_CAPTURE_ANSWER_READY_TIMEOUT_SECONDS", 0.05)
        answered = False

        async def answer():
            nonlocal answered
            answered = True  # the media never becomes ready

        reads_after_answer = 0

        async def read():
            nonlocal reads_after_answer
            if answered:
                reads_after_answer += 1
                if failure == "ring_ended" and reads_after_answer > 1:
                    status["bridge"]["ring_call_active"] = False
            return status

        api.async_answer_doorbell_call.side_effect = answer
        api.async_doorbell_video_status.side_effect = read

    with pytest.raises(HomeAssistantError) as err:
        asyncio.run(use_case.capture())

    assert not isinstance(err.value, ServiceValidationError)
    assert err.value.translation_key == "agent_command_failed"
    if failure == "hangup":
        recording.assert_awaited_once()
        api.async_hangup_doorbell_call.assert_awaited_once()
