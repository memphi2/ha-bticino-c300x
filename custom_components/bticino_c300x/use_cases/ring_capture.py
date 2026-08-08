"""Doorbell ring-capture service use case."""

from __future__ import annotations

import asyncio
import logging
from asyncio import Lock
from collections.abc import Mapping
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from ..entry_locks import entry_lock
from ..exceptions import service_validation_error
from ..ring_capture import (
    async_capture_doorbell_ring_call,
    raise_if_ring_capture_blocked,
)
from .common import ensure_doorbell_call_supported
from .ring_call import RingCallUseCase

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
        output_path: str | None = None,
        wav_output_dir: str | None = None,
        duration_seconds: int = 5,
        include_audio: bool = True,
        announcement_path: str | None = None,
    ) -> None:
        """Capture a short C300X doorbell ring-call clip on Home Assistant."""

        ensure_doorbell_call_supported(self._entry)
        lock = _capture_lock(self._entry.entry_id)
        if lock.locked():
            # Reject immediately instead of queuing behind an in-flight
            # capture: a second concurrent call (e.g. two automations
            # reacting to the same doorbell event) should not silently start
            # its own capture once the first one finishes.
            raise service_validation_error("ring_capture_busy")
        async with lock:
            await self._async_ensure_not_busy()
            ring_call = RingCallUseCase(self._entry)
            answered_call = False
            capture_error: Exception | None = None
            try:
                if include_audio or announcement_path is not None:
                    await ring_call.answer()
                    answered_call = True
                    await self._async_wait_for_answered_ring()

                await async_capture_doorbell_ring_call(
                    self._hass,
                    self._entry,
                    output_path=output_path,
                    wav_output_dir=wav_output_dir,
                    duration_seconds=duration_seconds,
                    include_audio=include_audio,
                    announcement_path=announcement_path,
                )
            except Exception as err:
                capture_error = err
                raise
            finally:
                if answered_call:
                    try:
                        await ring_call.hangup()
                    except Exception as err:
                        if capture_error is not None:
                            _LOGGER.warning(
                                "C300X doorbell capture failed and hangup also failed",
                                exc_info=err,
                            )
                        else:
                            raise service_validation_error("agent_command_failed") from err

    async def _async_ensure_not_busy(self) -> None:
        try:
            status = await self._entry.runtime_data.api.async_doorbell_video_status()
        except Exception as err:
            raise service_validation_error("agent_command_failed") from err
        try:
            raise_if_ring_capture_blocked(status)
        except HomeAssistantError as err:
            raise service_validation_error("ring_capture_busy") from err

    async def _async_wait_for_answered_ring(self) -> None:
        """Wait until the native ring-call media path is really answered."""

        loop = asyncio.get_running_loop()
        deadline = loop.time() + _RING_CAPTURE_ANSWER_READY_TIMEOUT_SECONDS
        last_error: Exception | None = None
        saw_active_ring = False
        while True:
            try:
                status = await self._entry.runtime_data.api.async_doorbell_video_status()
            except Exception as err:  # noqa: BLE001 - converted below for HA services
                last_error = err
            else:
                last_error = None
                if _ring_answer_media_ready(status):
                    return
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
