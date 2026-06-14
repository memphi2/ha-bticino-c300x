"""Doorbell ring-capture service use case."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from ..exceptions import service_validation_error
from ..ring_capture import (
    async_capture_doorbell_ring_call,
    raise_if_ring_capture_blocked,
)
from .common import ensure_doorbell_call_supported, raise_agent_command_failed

_LOGGER = logging.getLogger(__name__)


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
        await self._async_ensure_not_busy()
        answered_call = False
        if include_audio or announcement_path is not None:
            await raise_agent_command_failed(
                self._entry.runtime_data.api.async_answer_doorbell_call()
            )
            answered_call = True

        capture_error: Exception | None = None
        try:
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
                    await self._entry.runtime_data.api.async_hangup_doorbell_call()
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
