from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.bticino_c300x.camera_media import rtsp_orchestrator
from custom_components.bticino_c300x.camera_media.rtsp_orchestrator import (
    CameraRtspOrchestrator,
    CameraRtspOrchestratorSettings,
    media_decision_is_call_media,
    rtsp_consumer_for_doorbell_request,
    rtsp_consumer_for_media_decision,
)
from custom_components.bticino_c300x.camera_media.rtsp_policy import RtspConsumer
from custom_components.bticino_c300x.camera_media.state_machine import (
    MediaStateInput,
    derive_media_state,
    media_state_input_from_video_status,
)
from custom_components.bticino_c300x.const import CONF_DOORSTATION_AUDIO_GAIN_DB


def test_media_decision_maps_to_rtsp_consumers() -> None:
    assert media_decision_is_call_media(
        derive_media_state(MediaStateInput(video_owner="ring", unanswered_ring_call=True))
    )
    assert (
        rtsp_consumer_for_media_decision(
            derive_media_state(
                MediaStateInput(video_owner="ring", unanswered_ring_call=True)
            )
        )
        is RtspConsumer.RING_PREVIEW
    )
    assert (
        rtsp_consumer_for_media_decision(
            derive_media_state(MediaStateInput(video_owner="ring", ring_audio_active=True))
        )
        is RtspConsumer.RING_ANSWERED
    )
    assert (
        rtsp_consumer_for_media_decision(
            derive_media_state(MediaStateInput(video_owner="home_call", home_call_active=True))
        )
        is RtspConsumer.HOME_CALL
    )
    assert (
        rtsp_consumer_for_media_decision(
            derive_media_state(MediaStateInput(video_owner="idle"))
        )
        is RtspConsumer.DOORBELL_CARD
    )
    assert (
        rtsp_consumer_for_doorbell_request(
            derive_media_state(MediaStateInput(video_owner="home_call", home_call_active=True))
        )
        is RtspConsumer.DOORBELL_CARD
    )


def test_warmup_video_refreshes_after_activation_failure() -> None:
    api = _FakeApi(fail_activate=True)
    owner = _FakeOwner(api=api)
    orchestrator = _orchestrator(owner)

    with pytest.raises(RuntimeError, match="activate failed"):
        asyncio.run(orchestrator.async_warmup_video(audio=True))

    assert api.activate_audio == [True]
    assert owner.refresh_calls == [True]
    assert owner.state_writes == 1


def test_prepare_doorbell_rtsp_stream_sets_audio_gain_only_when_changed() -> None:
    owner = _FakeOwner(
        status_queue=[
            {
                "media_owner": "idle",
                "bridge": {"doorstation_audio_gain_db": 0.0},
            }
        ],
    )
    owner._entry.options[CONF_DOORSTATION_AUDIO_GAIN_DB] = 6.0
    orchestrator = _orchestrator(owner)
    ready_urls: list[str] = []
    orchestrator.async_wait_for_rtsp_ready = _record_ready(ready_urls)  # type: ignore[method-assign]

    result = asyncio.run(orchestrator.async_prepare_rtsp_stream(audio=True))

    assert result == "rtsp://agent.local:6554/doorbell-audio"
    assert owner.api.doorstation_audio_gain_calls == [6.0]
    assert owner.api.activate_audio == [True]
    assert ready_urls == ["rtsp://agent.local:6554/doorbell-audio"]


def test_prepare_doorbell_rtsp_stream_skips_audio_gain_when_current_matches() -> None:
    owner = _FakeOwner(
        status_queue=[
            {
                "media_owner": "idle",
                "bridge": {"doorstation_audio_gain_db": 6.0},
            }
        ],
    )
    owner._entry.options[CONF_DOORSTATION_AUDIO_GAIN_DB] = 6.0
    orchestrator = _orchestrator(owner)
    orchestrator.async_wait_for_rtsp_ready = _record_ready([])  # type: ignore[method-assign]

    asyncio.run(orchestrator.async_prepare_rtsp_stream(audio=True))

    assert owner.api.doorstation_audio_gain_calls == []
    assert owner.api.activate_audio == [True]


def test_prepare_doorbell_rtsp_stream_blocks_home_call_owner() -> None:
    owner = _FakeOwner(
        status_queue=[{"media_owner": "home_call", "bridge": {"media_owner": "home_call"}}],
    )
    orchestrator = _orchestrator(owner)

    with pytest.raises(HomeAssistantError, match="home_call_active"):
        asyncio.run(orchestrator.async_prepare_rtsp_stream(audio=True))

    assert owner.api.activate_audio == []
    assert owner._last_video_block_reason == "home_call_active"


def test_wait_for_call_media_after_external_event_returns_when_owner_clears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(rtsp_orchestrator.asyncio, "sleep", no_sleep)
    owner = _FakeOwner(
        status_queue=[
            None,
            {"media_owner": "idle", "external_media_active": False, "bridge": {}},
        ],
    )
    orchestrator = _orchestrator(owner)

    result = asyncio.run(
        orchestrator.async_wait_for_call_media_after_external_event(
            {"media_owner": "external_media", "external_media_active": True}
        )
    )

    assert result == {"media_owner": "idle", "external_media_active": False, "bridge": {}}


def test_prepare_home_call_rtsp_stream_uses_audio_url() -> None:
    api = _FakeApi(home_call_statuses=[{"target_audio_port": 40004}])
    owner = _FakeOwner(api=api)
    orchestrator = _orchestrator(owner)
    ready_urls: list[str] = []
    orchestrator.async_wait_for_rtsp_ready = _record_ready(ready_urls)  # type: ignore[method-assign]

    stream_url = asyncio.run(orchestrator.async_prepare_home_call_rtsp_stream())

    assert stream_url == "rtsp://agent.local:6554/doorbell-audio"
    assert ready_urls == ["rtsp://agent.local:6554/doorbell-audio"]
    assert owner.applied_home_call_statuses == [{"target_audio_port": 40004}]


def test_rtsp_probe_sends_describe_and_closes_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _FakeOwner()
    orchestrator = _orchestrator(owner)
    writer = _FakeWriter()

    async def open_connection(host: str, port: int) -> tuple[_FakeReader, _FakeWriter]:
        assert host == "agent.local"
        assert port == 6554
        return _FakeReader(b"RTSP/1.0 200 OK\r\n"), writer

    monkeypatch.setattr(rtsp_orchestrator.asyncio, "open_connection", open_connection)

    asyncio.run(orchestrator.async_probe_rtsp("rtsp://agent.local:6554/doorbell"))

    assert writer.closed is True
    assert writer.payload.startswith(b"DESCRIBE rtsp://agent.local:6554/doorbell RTSP/1.0")
    assert b"Accept: application/sdp\r\n" in writer.payload


def test_wait_for_rtsp_ready_retries_and_resets_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(rtsp_orchestrator.asyncio, "sleep", no_sleep)
    owner = _FakeOwner()
    owner._last_rtsp_error = "old"
    owner._rtsp_unavailable_until = 1.0
    orchestrator = _orchestrator(owner)
    attempts = 0

    async def probe(_stream_url: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("not ready")

    orchestrator.async_probe_rtsp = probe  # type: ignore[method-assign]

    asyncio.run(orchestrator.async_wait_for_rtsp_ready("rtsp://agent.local/doorbell"))

    assert attempts == 2
    assert owner._last_rtsp_error is None
    assert owner._rtsp_unavailable_until == 0.0
    assert owner._rtsp_cooldown_scope is None


def test_wait_for_rtsp_ready_waits_for_native_stop_to_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_sleep(_delay: float) -> None:
        raise AssertionError("native stop readiness should wait for media events")

    monkeypatch.setattr(rtsp_orchestrator.asyncio, "sleep", fail_sleep)
    owner = _FakeOwner(
        status_queue=[
            {"media_owner": "agent", "bridge": {"stop_in_progress": True}},
            {"media_owner": "idle", "bridge": {"stop_in_progress": False}},
        ],
    )
    orchestrator = _orchestrator(owner)
    ready_urls: list[str] = []
    orchestrator.async_probe_rtsp = _record_probe(ready_urls)  # type: ignore[method-assign]

    asyncio.run(orchestrator.async_wait_for_rtsp_ready("rtsp://agent.local/doorbell"))

    assert ready_urls == ["rtsp://agent.local/doorbell"]
    assert owner.rtsp_event_waits == [(0, pytest.approx(0.01, abs=0.001))]


def test_wait_for_rtsp_ready_waits_for_start_event_between_probes() -> None:
    owner = _FakeOwner()
    orchestrator = _orchestrator(owner, rtsp_ready_timeout_seconds=2.0)
    attempts = 0

    async def probe(_stream_url: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("not ready")

    orchestrator.async_probe_rtsp = probe  # type: ignore[method-assign]

    asyncio.run(orchestrator.async_wait_for_rtsp_ready("rtsp://agent.local/doorbell"))

    assert attempts == 2
    assert owner.rtsp_event_waits == [(0, pytest.approx(1.0))]


def test_wait_for_rtsp_ready_records_failure_without_retry_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(rtsp_orchestrator.asyncio, "sleep", no_sleep)
    owner = _FakeOwner()
    orchestrator = _orchestrator(owner, rtsp_ready_timeout_seconds=0.0)

    async def probe(_stream_url: str) -> None:
        raise RuntimeError("still down")

    orchestrator.async_probe_rtsp = probe  # type: ignore[method-assign]

    with pytest.raises(HomeAssistantError, match="still down"):
        asyncio.run(orchestrator.async_wait_for_rtsp_ready("rtsp://agent.local/doorbell"))

    assert owner._last_rtsp_error == "RuntimeError"
    assert owner._rtsp_unavailable_until == 0.0
    assert owner._rtsp_cooldown_scope is None


def test_rtsp_cooldown_marker_is_cleared_before_ready_wait() -> None:
    owner = _FakeOwner()
    orchestrator = _orchestrator(owner)
    ready_urls: list[str] = []
    orchestrator.async_probe_rtsp = _record_probe(ready_urls)  # type: ignore[method-assign]

    async def _run() -> None:
        owner._last_rtsp_error = "RuntimeError"
        owner._rtsp_unavailable_until = asyncio.get_running_loop().time() + 10.0
        await orchestrator.async_wait_for_rtsp_ready("rtsp://agent.local/doorbell")

    asyncio.run(_run())

    assert ready_urls == ["rtsp://agent.local/doorbell"]
    assert owner._rtsp_unavailable_until == 0.0
    assert owner._rtsp_cooldown_scope is None


def test_home_call_rtsp_cooldown_does_not_block_doorbell_wait() -> None:
    owner = _FakeOwner()
    orchestrator = _orchestrator(owner)
    ready_urls: list[str] = []
    orchestrator.async_probe_rtsp = _record_probe(ready_urls)  # type: ignore[method-assign]

    async def _run() -> None:
        owner._last_rtsp_error = "RuntimeError"
        owner._rtsp_unavailable_until = asyncio.get_running_loop().time() + 10.0
        owner._rtsp_cooldown_scope = "home_call"
        await orchestrator.async_wait_for_rtsp_ready(
            "rtsp://agent.local/doorbell",
            cooldown_scope="doorbell",
        )

    asyncio.run(_run())

    assert ready_urls == ["rtsp://agent.local/doorbell"]
    assert owner._rtsp_unavailable_until == 0.0
    assert owner._rtsp_cooldown_scope is None


def test_rtsp_probe_rejects_non_rtsp_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _FakeOwner()
    orchestrator = _orchestrator(owner)

    async def open_connection(host: str, port: int) -> tuple[_FakeReader, _FakeWriter]:
        return _FakeReader(b"HTTP/1.1 200 OK\r\n"), _FakeWriter()

    monkeypatch.setattr(rtsp_orchestrator.asyncio, "open_connection", open_connection)

    with pytest.raises(HomeAssistantError, match="non-RTSP"):
        asyncio.run(orchestrator.async_probe_rtsp("rtsp://agent.local:6554/doorbell"))


def test_rtsp_probe_rejects_error_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _FakeOwner()
    orchestrator = _orchestrator(owner)

    async def open_connection(host: str, port: int) -> tuple[_FakeReader, _FakeWriter]:
        return _FakeReader(b"RTSP/1.0 503 Service Unavailable\r\n"), _FakeWriter()

    monkeypatch.setattr(rtsp_orchestrator.asyncio, "open_connection", open_connection)

    with pytest.raises(HomeAssistantError, match="status 503"):
        asyncio.run(orchestrator.async_probe_rtsp("rtsp://agent.local:6554/doorbell"))


def test_rtsp_probe_rejects_invalid_status_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _FakeOwner()
    orchestrator = _orchestrator(owner)

    async def open_connection(host: str, port: int) -> tuple[_FakeReader, _FakeWriter]:
        return _FakeReader(b"RTSP/1.0 broken\r\n"), _FakeWriter()

    monkeypatch.setattr(rtsp_orchestrator.asyncio, "open_connection", open_connection)

    with pytest.raises(HomeAssistantError, match="invalid status line"):
        asyncio.run(orchestrator.async_probe_rtsp("rtsp://agent.local:6554/doorbell"))


def test_wait_for_external_call_media_returns_last_status_after_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(rtsp_orchestrator.asyncio, "sleep", no_sleep)
    original = {"media_owner": "external_media", "external_media_active": True}
    owner = _FakeOwner(status_queue=[None, None, None])
    orchestrator = _orchestrator(owner, ring_call_wait_timeout_seconds=0.0)

    result = asyncio.run(
        orchestrator.async_wait_for_call_media_after_external_event(original)
    )

    assert result == original


def test_rtsp_admission_denied_records_block_reason() -> None:
    owner = _FakeOwner(local_sessions=1)
    orchestrator = _orchestrator(owner)
    decision = derive_media_state(MediaStateInput(video_owner="agent", video_window_available=True))

    with pytest.raises(HomeAssistantError, match="rtsp_consumer_active"):
        orchestrator.raise_if_rtsp_admission_denied(
            {"media_owner": "agent", "bridge": {"clients": 1}},
            decision,
            consumer=RtspConsumer.DOORBELL_CARD,
        )

    assert owner._last_video_block_reason == "rtsp_consumer_active"
    assert owner.derived_state_refreshes == 1


@dataclass
class _FakeApi:
    fail_activate: bool = False
    home_call_statuses: list[dict[str, Any]] = field(default_factory=list)
    activate_audio: list[bool] = field(default_factory=list)
    doorstation_audio_gain_calls: list[float] = field(default_factory=list)
    stop_calls: int = 0

    async def async_activate_doorbell_video(self, *, audio: bool) -> None:
        self.activate_audio.append(audio)
        if self.fail_activate:
            raise RuntimeError("activate failed")

    async def async_set_doorstation_audio_gain_db(self, gain_db: float) -> None:
        self.doorstation_audio_gain_calls.append(gain_db)

    async def async_stop_doorbell_video(self) -> None:
        self.stop_calls += 1

    async def async_home_call_status(self) -> dict[str, Any]:
        return self.home_call_statuses.pop(0) if self.home_call_statuses else {}


class _FakeOwner:
    def __init__(
        self,
        *,
        api: _FakeApi | None = None,
        status_queue: list[dict[str, Any] | None] | None = None,
        local_sessions: int = 0,
    ) -> None:
        self.api = api or _FakeApi()
        self._entry = SimpleNamespace(
            data={"video_port": 6554},
            options={},
            runtime_data=SimpleNamespace(api=self.api),
        )
        self._rtsp_prepare_lock = asyncio.Lock()
        self._rtsp_ready_lock = asyncio.Lock()
        self._rtsp_unavailable_until = 0.0
        self._last_rtsp_error = None
        self._rtsp_cooldown_scope = None
        self._last_video_block_reason = None
        self._status_queue = list(status_queue or [])
        self._local_sessions = local_sessions
        self._rtsp_event_revision_value = 0
        self.rtsp_event_waits: list[tuple[int, float]] = []
        self.refresh_calls: list[bool] = []
        self.state_writes = 0
        self.applied_home_call_statuses: list[dict[str, Any]] = []
        self.derived_state_refreshes = 0

    def _build_stream_url(self, *, audio: bool = False) -> str:
        return f"rtsp://agent.local:6554/{'doorbell-audio' if audio else 'doorbell-video'}"

    def _agent_host_for_socket(self) -> str:
        return "agent.local"

    async def _async_refresh_video_status(self, *, apply_status: bool = True) -> dict[str, Any]:
        self.refresh_calls.append(apply_status)
        return {"media_owner": "idle", "bridge": {}}

    async def _async_refresh_video_status_or_none(
        self,
        *,
        apply_status: bool = True,
    ) -> dict[str, Any] | None:
        if self._status_queue:
            return self._status_queue.pop(0)
        return {"media_owner": "idle", "bridge": {}}

    def _derive_media_decision(
        self,
        status: dict[str, Any] | None = None,
    ) -> Any:
        return derive_media_state(media_state_input_from_video_status(status or {}))

    def _active_local_media_sessions(self) -> int:
        return self._local_sessions

    def _refresh_derived_media_state(self) -> None:
        self.derived_state_refreshes += 1

    def _apply_home_call_status(self, status: dict[str, Any]) -> None:
        self.applied_home_call_statuses.append(dict(status))

    def _async_write_ha_state_if_ready(self) -> None:
        self.state_writes += 1

    def _rtsp_event_revision(self) -> int:
        return self._rtsp_event_revision_value

    async def _async_wait_for_rtsp_event(
        self,
        *,
        revision: int,
        wait_seconds: float,
    ) -> None:
        self.rtsp_event_waits.append((revision, wait_seconds))


class _FakeReader:
    def __init__(self, response: bytes) -> None:
        self.response = response

    async def read(self, _size: int) -> bytes:
        return self.response


class _FakeWriter:
    def __init__(self) -> None:
        self.payload = b""
        self.closed = False

    def write(self, payload: bytes) -> None:
        self.payload += payload

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


def _orchestrator(
    owner: _FakeOwner,
    *,
    rtsp_ready_timeout_seconds: float = 0.01,
    ring_call_wait_timeout_seconds: float = 0.05,
) -> CameraRtspOrchestrator:
    return CameraRtspOrchestrator(
        owner,
        settings=CameraRtspOrchestratorSettings(
            rtsp_ready_connect_timeout_seconds=0.01,
            rtsp_ready_interval_seconds=0.01,
            rtsp_ready_timeout_seconds=rtsp_ready_timeout_seconds,
            rtsp_failure_cooldown_seconds=1.0,
            ring_call_wait_interval_seconds=0.01,
            ring_call_wait_timeout_seconds=ring_call_wait_timeout_seconds,
        ),
    )


def _record_ready(calls: list[str]) -> Any:
    async def wait(stream_url: str, **_kwargs: Any) -> None:
        calls.append(stream_url)

    return wait


def _record_probe(calls: list[str]) -> Any:
    async def probe(stream_url: str) -> None:
        calls.append(stream_url)

    return probe
