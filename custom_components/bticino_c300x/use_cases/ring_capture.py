"""Doorbell ring-capture service use case."""

from __future__ import annotations

import asyncio
import logging
from asyncio import Lock
from collections.abc import Mapping
from contextlib import ExitStack, suppress
from typing import Any, cast

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from ..camera_media.capture_lifecycle import RingCaptureCallGuard
from ..camera_media.session_lifecycle import media_owner_stopping, media_stop_scope
from ..doorstation_audio import async_ensure_doorstation_audio_gain
from ..entry_locks import entry_lock
from ..exceptions import service_validation_error
from ..ring_capture import (
    async_capture_doorbell_ring_call,
    ensure_on_demand_capture_runtime,
    raise_if_on_demand_capture_blocked,
    raise_if_ring_answer_would_block_capture,
    raise_if_ring_capture_blocked,
)
from ..visitor_journal import get_journal
from .common import (
    ensure_doorbell_call_supported,
    ensure_doorbell_video_supported,
    raise_agent_command_failed,
)
from .doorbell_video import DoorbellVideoUseCase

_LOGGER = logging.getLogger(__name__)
_RING_CAPTURE_ANSWER_READY_TIMEOUT_SECONDS = 5.0
_RING_CAPTURE_ANSWER_READY_INTERVAL_SECONDS = 0.1


def _capture_lock(entry_id: str) -> Lock:
    """Return the per-entry lock that rejects overlapping capture() calls."""

    return entry_lock(entry_id, "ring_capture")


class RingCaptureUseCase:
    """Record a short C300X doorbell ring-call clip on Home Assistant."""

    def __init__(self, hass: HomeAssistant, entry: Any) -> None:
        self._hass = hass
        self._entry = entry

    async def capture(
        self,
        *,
        capture_mode: str = "ring",
        output_path: str | None = None,
        wav_output_dir: str | None = None,
        duration_seconds: int = 5,
        include_audio: bool = True,
        announcement_path: str | None = None,
    ) -> dict[str, Any]:
        """Capture a short C300X doorbell ring-call clip on Home Assistant."""

        if capture_mode not in {"ring", "on_demand"}:
            raise ValueError("Invalid C300X capture mode")
        on_demand = capture_mode == "on_demand"
        journal = get_journal(self._hass, self._entry.entry_id)
        visitor_id = journal.active if journal is not None and not on_demand else None
        if on_demand:
            if announcement_path is not None:
                raise service_validation_error("capture_announcement_requires_ring")
            ensure_doorbell_video_supported(self._entry)
        else:
            ensure_doorbell_call_supported(self._entry)
        lock = _capture_lock(self._entry.entry_id)
        if lock.locked():
            # Reject immediately instead of queuing behind an in-flight
            # capture: a second concurrent call (e.g. two automations
            # reacting to the same doorbell event) should not silently start
            # its own capture once the first one finishes.
            raise service_validation_error("ring_capture_busy")
        async with lock:
            # Keep ownership on this runtime even if an entry reload replaces it.
            runtime = self._entry.runtime_data
            resources = runtime.resources
            capture_task = asyncio.current_task()
            if on_demand:
                resources.on_demand_capture_active = True
                resources.on_demand_capture_task = capture_task
            else:
                resources.ring_capture_task = capture_task
            answered_call = False
            call_guard = None
            admission = ExitStack()
            capture_error: BaseException | None = None
            try:
                if not on_demand:
                    call_guard = RingCaptureCallGuard(self._hass, self._entry.entry_id)
                    if include_audio or announcement_path is not None:
                        if media_owner_stopping(resources, "doorbell"):
                            raise service_validation_error("ring_capture_busy")
                        # Reserve HA admission through recording and cleanup;
                        # existing/opening consumers are checked separately.
                        admission.enter_context(media_stop_scope(resources, "doorbell"))
                status = await self._async_ensure_not_busy(capture_mode)
                if not on_demand:
                    self._ensure_ring_capture_runtime(runtime)
                if on_demand:
                    ensure_on_demand_capture_runtime(self._entry, runtime)
                    await DoorbellVideoUseCase(self._entry).activate(
                        audio=include_audio, status=status,
                        before_activate=lambda: ensure_on_demand_capture_runtime(self._entry, runtime),
                    )
                    ensure_on_demand_capture_runtime(self._entry, runtime)
                    # Activation can revive parked clients or race an incoming call.
                    await self._async_ensure_not_busy(capture_mode)
                    ensure_on_demand_capture_runtime(self._entry, runtime)
                elif include_audio or announcement_path is not None:
                    try:
                        raise_if_ring_answer_would_block_capture(status)
                    except HomeAssistantError as err:
                        raise service_validation_error("ring_capture_busy") from err
                    answered_call = await self._async_answer_ring(runtime)
                    self._ensure_ring_capture_runtime(runtime)
                    status = await self._async_wait_for_answered_ring(runtime)
                    assert call_guard is not None
                    call_guard.observe_answered(status)

                if not on_demand:
                    self._ensure_ring_capture_runtime(runtime)

                result = await async_capture_doorbell_ring_call(
                    self._hass,
                    self._entry,
                    output_path=output_path,
                    wav_output_dir=wav_output_dir,
                    duration_seconds=duration_seconds,
                    include_audio=include_audio,
                    announcement_path=announcement_path,
                    capture_mode=capture_mode,
                )
                if call_guard is not None:
                    call_guard.finished = True
                if journal is not None and output_path is None:
                    await journal.attach_clip(visitor_id, result)
                return result
            except (Exception, asyncio.CancelledError) as err:
                capture_error = err
                raise
            finally:
                if call_guard is not None and capture_error is None:
                    call_guard.finished = True
                if on_demand and resources.on_demand_capture_task is capture_task:
                    # RTSP disconnect cleans up our media; never globally stop
                    # a call or camera session which may have replaced it.
                    resources.on_demand_capture_active = False
                    resources.on_demand_capture_task = None
                try:
                    if answered_call and call_guard is not None and self._owns_ring_capture(runtime):
                        try:
                            await self._async_hangup_owned_ring(runtime, call_guard)
                        except Exception as err:
                            if capture_error is not None:
                                _LOGGER.warning(
                                    "C300X doorbell capture failed and hangup also failed",
                                    exc_info=err,
                                )
                            else:
                                raise service_validation_error("agent_command_failed") from err
                finally:
                    admission.close()
                    if call_guard is not None:
                        call_guard.close()
                    if not on_demand and resources.ring_capture_task is capture_task:
                        resources.ring_capture_task = None

    def _owns_ring_capture(self, runtime: Any) -> bool:
        if runtime is None:
            return False
        resources = runtime.resources
        return (
            getattr(self._entry, "runtime_data", None) is runtime
            and resources.ring_capture_task is asyncio.current_task()
        )

    def _ensure_ring_capture_runtime(self, runtime: Any) -> None:
        if not self._owns_ring_capture(runtime):
            raise HomeAssistantError("C300X ring capture was cancelled or the integration reloaded")

    async def _async_answer_ring(self, runtime: Any) -> bool:
        status = await runtime.api.async_doorbell_video_status()
        self._ensure_ring_capture_runtime(runtime)
        self._raise_if_ring_answer_blocked(runtime, status)
        if _ring_answer_media_ready(status) or _status_bridge(status).get("ring_answer_requested"):
            return False
        await async_ensure_doorstation_audio_gain(self._entry, status=status)
        self._ensure_ring_capture_runtime(runtime)
        # Gain synchronization can yield to a native client or another answer.
        status = await runtime.api.async_doorbell_video_status()
        self._ensure_ring_capture_runtime(runtime)
        self._raise_if_ring_answer_blocked(runtime, status)
        if _ring_answer_media_ready(status) or _status_bridge(status).get("ring_answer_requested"):
            return False
        ensure_doorbell_call_supported(self._entry)
        await raise_agent_command_failed(runtime.api.async_answer_doorbell_call())
        return True

    def _raise_if_ring_answer_blocked(self, runtime: Any, status: Mapping[str, Any]) -> None:
        session_count = getattr(runtime.resources, "media_session_count", None)
        try:
            raise_if_ring_capture_blocked(status)
            raise_if_ring_answer_would_block_capture(status)
            if callable(session_count) and session_count():
                raise HomeAssistantError("C300X camera consumer is already active or opening")
        except HomeAssistantError as err:
            raise service_validation_error("ring_capture_busy") from err

    async def _async_hangup_owned_ring(self, runtime: Any, guard: RingCaptureCallGuard) -> None:
        # Never dereference a replacement runtime after an awaited close.
        with media_stop_scope(runtime.resources, "doorbell"):
            if not await self._async_ring_cleanup_allowed(runtime, guard):
                return
            prepare_stop = runtime.resources.prepare_doorbell_video_stop
            if prepare_stop is not None:
                await prepare_stop()
                if not await self._async_ring_cleanup_allowed(runtime, guard):
                    return
            if self._owns_ring_capture(runtime):
                guard.close()
                await runtime.api.async_hangup_doorbell_call()

    async def _async_ring_cleanup_allowed(self, runtime: Any, guard: RingCaptureCallGuard) -> bool:
        if not self._owns_ring_capture(runtime) or guard.invalidated or guard.started_at is None:
            return False
        with suppress(Exception):
            status = await runtime.api.async_doorbell_video_status()
            return self._owns_ring_capture(runtime) and guard.matches(status)
        return False

    async def _async_ensure_not_busy(self, capture_mode: str = "ring") -> Mapping[str, Any]:
        try:
            status = await self._entry.runtime_data.api.async_doorbell_video_status()
        except Exception as err:
            raise service_validation_error("agent_command_failed") from err
        try:
            if capture_mode == "on_demand":
                raise_if_on_demand_capture_blocked(self._entry, status)
            else:
                raise_if_ring_capture_blocked(status)
        except HomeAssistantError as err:
            raise service_validation_error(
                "on_demand_capture_busy" if capture_mode == "on_demand" else "ring_capture_busy"
            ) from err
        return cast(Mapping[str, Any], status)

    async def _async_wait_for_answered_ring(self, runtime: Any) -> Mapping[str, Any]:
        """Wait until the native ring-call media path is really answered."""

        loop = asyncio.get_running_loop()
        deadline = loop.time() + _RING_CAPTURE_ANSWER_READY_TIMEOUT_SECONDS
        last_error: Exception | None = None
        saw_active_ring = False
        while True:
            try:
                status = await runtime.api.async_doorbell_video_status()
            except Exception as err:  # noqa: BLE001 - converted below for HA services
                last_error = err
            else:
                self._ensure_ring_capture_runtime(runtime)
                last_error = None
                if _ring_answer_media_ready(status):
                    return cast(Mapping[str, Any], status)
                if _ring_call_still_active(status):
                    saw_active_ring = True
                elif saw_active_ring:
                    raise service_validation_error("agent_command_failed")

            remaining = deadline - loop.time()
            if remaining <= 0:
                raise service_validation_error("agent_command_failed") from last_error
            await asyncio.sleep(
                min(_RING_CAPTURE_ANSWER_READY_INTERVAL_SECONDS, remaining)
            )


def _ring_answer_media_ready(status: Mapping[str, Any]) -> bool:
    bridge = _status_bridge(status)
    return bool(bridge.get("ring_answered") or bridge.get("ring_audio_active"))


def _ring_call_still_active(status: Mapping[str, Any]) -> bool:
    bridge = _status_bridge(status)
    return bool(
        bridge.get("ring_call_active")
        or bridge.get("ring_media_active")
        or bridge.get("ring_answer_requested")
        or bridge.get("ring_answered")
        or bridge.get("ring_audio_active")
    )


def _status_bridge(status: Mapping[str, Any]) -> Mapping[str, Any]:
    bridge = status.get("bridge")
    return bridge if isinstance(bridge, Mapping) else {}
