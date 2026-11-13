"""On-demand recording owns one RTSP consumer without answering a ring call."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from test_ring_capture import _FakeHass

from custom_components.bticino_c300x import ring_capture
from custom_components.bticino_c300x.data import C300XRuntimeResources
from custom_components.bticino_c300x.use_cases.ring_capture import RingCaptureUseCase


def _idle(**bridge_changes):
    return {
        "media_owner": "idle",
        "window_available": False,
        "stream_path": "/doorbell-video",
        "audio_stream_path": "/doorbell",
        "recorder_stream_path": "/doorbell-recorder",
        "bridge": {
            "media_owner": "idle", "clients": 0, "doorstation_audio_gain_db": 0,
            **bridge_changes,
        },
    }


def _entry(status=None):
    api = SimpleNamespace(
        async_doorbell_video_status=AsyncMock(return_value=_idle() if status is None else status),
        async_activate_doorbell_video=AsyncMock(),
    )
    for name in (
        "async_answer_doorbell_call", "async_hangup_doorbell_call",
        "async_stop_doorbell_video", "async_doorbell_call_status",
        "async_audio_codec_status",
    ):
        setattr(api, name, AsyncMock(side_effect=AssertionError(f"unexpected {name}")))
    return SimpleNamespace(
        entry_id="on-demand-test", data={"video_enabled": True, "agent_host": "192.0.2.10"},
        options={},
        runtime_data=SimpleNamespace(
            api=api, resources=C300XRuntimeResources(),
            capabilities={"doorbell_video": {"supported": True}, "doorbell_call": {"supported": True}},
            event_state=SimpleNamespace(audio_codec=None),
        ),
    )


@pytest.fixture
def capture_boundary(monkeypatch):
    ready = AsyncMock()
    ffmpeg = AsyncMock()
    monkeypatch.setattr(ring_capture, "_async_wait_rtsp_ready", ready)
    monkeypatch.setattr(ring_capture, "_async_run_ffmpeg", ffmpeg)
    for name in ("_async_talkback_codec_is_pcmu", "_async_keep_talkback_alive_when_ready"):
        monkeypatch.setattr(ring_capture, name, AsyncMock(side_effect=AssertionError(name)))
    return ready, ffmpeg


@pytest.mark.parametrize("include_audio", [False, True])
def test_idle_capture_activates_normal_rtsp_path_without_ring_or_talkback(
    tmp_path, capture_boundary, include_audio,
):
    ready, ffmpeg = capture_boundary
    entry = _entry()
    # Ring capability is deliberately unavailable; on-demand needs only video.
    entry.runtime_data.capabilities["doorbell_call"] = {"supported": False}
    hass = _FakeHass(tmp_path)
    expected_path = "/doorbell" if include_audio else "/doorbell-video"

    async def record(url, target, **kwargs):
        assert entry.runtime_data.resources.on_demand_capture_active
        assert not entry.runtime_data.api.async_doorbell_video_status.return_value["window_available"]
        target.write_bytes(b"recorded mp4")
        assert kwargs["include_audio"] is include_audio

    ffmpeg.side_effect = record
    result = asyncio.run(RingCaptureUseCase(hass, entry).capture(
        capture_mode="on_demand", include_audio=include_audio, duration_seconds=4,
        output_path=str(tmp_path / "media/c300x/recording.mp4"),
    ))

    entry.runtime_data.api.async_activate_doorbell_video.assert_awaited_once_with(audio=include_audio)
    assert ready.await_args.args[0].endswith(expected_path)
    assert ffmpeg.await_args.args[0].endswith(expected_path)
    assert result["capture_mode"] == "on_demand"
    assert result["kind"] == "doorbell_ring_capture"
    assert result["include_audio"] is include_audio
    assert ("raw_wav_path" in result) is include_audio
    assert len(result["frames"]) == 3
    assert json.loads(Path(result["metadata_path"]).read_text())["capture_mode"] == "on_demand"
    assert not entry.runtime_data.resources.on_demand_capture_active


@pytest.mark.parametrize("status", [
    {},
    {"bridge": {"clients": 0}},
    {"media_owner": "unknown", "bridge": {"clients": 0}},
    {"media_owner": "idle", "bridge": {}},
    _idle(clients=1),
    _idle(clients=-1),
    {**_idle(), "media_owner": "ring"},
    {**_idle(), "media_owner": "home_call"},
    {**_idle(), "media_owner": "external_media"},
    _idle(ring_call_active=True),
    _idle(home_call_running=True),
    _idle(external_media_active=True),
    _idle(media_active=True),
    _idle(media_starting=True),
    _idle(stop_in_progress=True),
])
def test_on_demand_rejects_busy_or_unknown_media_before_activation(tmp_path, capture_boundary, status):
    entry = _entry(status)
    with pytest.raises(ServiceValidationError) as err:
        asyncio.run(RingCaptureUseCase(_FakeHass(tmp_path), entry).capture(capture_mode="on_demand"))
    assert err.value.translation_key == "on_demand_capture_busy"
    entry.runtime_data.api.async_activate_doorbell_video.assert_not_awaited()
    capture_boundary[1].assert_not_awaited()
    assert not entry.runtime_data.resources.on_demand_capture_active


@pytest.mark.parametrize("local_state", ["session_or_offer", "stopping"])
def test_on_demand_respects_local_admission(tmp_path, capture_boundary, local_state):
    entry = _entry()
    if local_state == "session_or_offer":
        entry.runtime_data.resources.media_session_count = lambda: 1
    else:
        entry.runtime_data.resources.media_stop_counts["doorbell"] = 1
    with pytest.raises(ServiceValidationError) as err:
        asyncio.run(RingCaptureUseCase(_FakeHass(tmp_path), entry).capture(capture_mode="on_demand"))
    assert err.value.translation_key == "on_demand_capture_busy"
    entry.runtime_data.api.async_activate_doorbell_video.assert_not_awaited()
    capture_boundary[1].assert_not_awaited()


@pytest.mark.parametrize("change_after", ["activate", "options"])
def test_on_demand_rechecks_status_before_play_without_stopping_replacement(
    tmp_path, capture_boundary, change_after,
):
    entry = _entry()
    ready, ffmpeg = capture_boundary

    async def replace(*args, **kwargs):
        entry.runtime_data.api.async_doorbell_video_status.return_value = {
            **_idle(clients=1), "media_owner": "agent",
        }

    if change_after == "activate":
        entry.runtime_data.api.async_activate_doorbell_video.side_effect = replace
    else:
        ready.side_effect = replace
    with pytest.raises(HomeAssistantError):
        asyncio.run(RingCaptureUseCase(_FakeHass(tmp_path), entry).capture(capture_mode="on_demand"))
    ffmpeg.assert_not_awaited()
    entry.runtime_data.api.async_stop_doorbell_video.assert_not_awaited()
    assert not entry.runtime_data.resources.on_demand_capture_active


@pytest.mark.parametrize("include_audio", [False, True])
def test_on_demand_announcement_is_rejected_before_touching_media(tmp_path, capture_boundary, include_audio):
    entry = _entry()
    with pytest.raises(ServiceValidationError) as err:
        asyncio.run(RingCaptureUseCase(_FakeHass(tmp_path), entry).capture(
            capture_mode="on_demand", include_audio=include_audio,
            announcement_path="/media/c300x/announcement.wav",
        ))
    assert err.value.translation_key == "capture_announcement_requires_ring"
    entry.runtime_data.api.async_doorbell_video_status.assert_not_awaited()
    entry.runtime_data.api.async_activate_doorbell_video.assert_not_awaited()


@pytest.mark.parametrize("failure_stage", ["status", "activate", "options", "ffmpeg"])
def test_on_demand_failure_releases_reservation_without_global_stop(tmp_path, capture_boundary, failure_stage):
    entry = _entry()
    ready, ffmpeg = capture_boundary
    failing = {
        "status": entry.runtime_data.api.async_doorbell_video_status,
        "activate": entry.runtime_data.api.async_activate_doorbell_video,
        "options": ready, "ffmpeg": ffmpeg,
    }[failure_stage]
    failing.side_effect = HomeAssistantError("synthetic capture failure")
    with pytest.raises(HomeAssistantError):
        asyncio.run(RingCaptureUseCase(_FakeHass(tmp_path), entry).capture(capture_mode="on_demand"))
    assert not entry.runtime_data.resources.on_demand_capture_active
    entry.runtime_data.api.async_hangup_doorbell_call.assert_not_awaited()
    entry.runtime_data.api.async_stop_doorbell_video.assert_not_awaited()


def test_on_demand_and_ring_capture_share_exclusive_lock(tmp_path, capture_boundary):
    async def run():
        entry = _entry()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def record(*args, **kwargs):
            entered.set()
            await release.wait()

        capture_boundary[1].side_effect = record
        use_case = RingCaptureUseCase(_FakeHass(tmp_path), entry)
        task = asyncio.create_task(use_case.capture(capture_mode="on_demand"))
        await entered.wait()
        with pytest.raises(ServiceValidationError) as err:
            await use_case.capture()
        assert err.value.translation_key == "ring_capture_busy"
        entry.runtime_data.api.async_answer_doorbell_call.assert_not_awaited()
        release.set()
        await task
        assert not entry.runtime_data.resources.on_demand_capture_active

    asyncio.run(run())


@pytest.mark.parametrize("replace_runtime", [False, True])
@pytest.mark.parametrize("cancel_kind", ["caller", "unload"])
def test_cancelled_capture_kills_only_its_process_and_releases_its_resources(
    monkeypatch, tmp_path, replace_runtime, cancel_kind,
):
    async def run():
        entry = _entry()
        original = entry.runtime_data
        started = asyncio.Event()

        class Process:
            returncode = None
            kills = 0
            waits = 0

            async def communicate(self):
                self.waits += 1
                if self.kills:
                    return b"", b""
                started.set()
                await asyncio.Event().wait()

            def kill(self):
                self.kills += 1
                self.returncode = -9

        process = Process()
        monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
        monkeypatch.setattr(ring_capture, "_async_wait_rtsp_ready", AsyncMock())
        task = asyncio.create_task(RingCaptureUseCase(_FakeHass(tmp_path), entry).capture(capture_mode="on_demand"))
        await started.wait()
        assert original.resources.on_demand_capture_active
        if replace_runtime:
            entry.runtime_data = _entry().runtime_data
            entry.runtime_data.resources.on_demand_capture_active = True
        if cancel_kind == "unload":
            original.resources.close()
        else:
            task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert process.kills == 1
        assert process.waits == 2
        assert not original.resources.on_demand_capture_active
        if replace_runtime:
            assert entry.runtime_data.resources.on_demand_capture_active
        original.api.async_stop_doorbell_video.assert_not_awaited()
        original.api.async_hangup_doorbell_call.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("replace_during", ["status", "gain", "options"])
def test_preparing_capture_cannot_continue_in_replacement_runtime(
    tmp_path, capture_boundary, replace_during,
):
    entry = _entry()
    original = entry.runtime_data
    successor = _entry().runtime_data
    successor.resources.on_demand_capture_active = True

    async def replace(*args, **kwargs):
        entry.runtime_data = successor
        return _idle()

    if replace_during == "status":
        original.api.async_doorbell_video_status.side_effect = replace
    elif replace_during == "gain":
        entry.options["doorstation_audio_gain_db"] = 6
        original.api.async_set_doorstation_audio_gain_db = AsyncMock(side_effect=replace)
    else:
        capture_boundary[0].side_effect = replace
    with pytest.raises(HomeAssistantError, match="cancelled or the integration reloaded"):
        asyncio.run(RingCaptureUseCase(_FakeHass(tmp_path), entry).capture(capture_mode="on_demand"))
    capture_boundary[1].assert_not_awaited()
    successor.api.async_activate_doorbell_video.assert_not_awaited()
    successor.api.async_doorbell_video_status.assert_not_awaited()
    assert successor.resources.on_demand_capture_active
    assert not original.resources.on_demand_capture_active
    assert original.resources.on_demand_capture_task is None


@pytest.mark.parametrize("include_audio", [False, True])
def test_on_demand_never_falls_back_to_ring_recorder(include_audio):
    with pytest.raises(HomeAssistantError, match="on-demand capture requires"):
        ring_capture._capture_stream_path(
            _entry(), {"recorder_stream_path": "/doorbell-recorder"},
            include_audio=include_audio, capture_mode="on_demand",
        )
