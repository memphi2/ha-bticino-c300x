"""Doorbell video service use cases."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..camera_media.state_machine import (
    MediaState,
    derive_media_state,
    media_state_input_from_video_status,
)
from ..doorstation_audio import async_ensure_doorstation_audio_gain
from .common import ensure_doorbell_video_supported, raise_agent_command_failed


class DoorbellVideoUseCase:
    """Control the C300X doorbell video session."""

    def __init__(self, entry: Any) -> None:
        self._entry = entry

    async def activate(self, *, audio: bool = True) -> None:
        """Activate or renew the C300X doorbell video session."""

        ensure_doorbell_video_supported(self._entry)
        if audio:
            await async_ensure_doorstation_audio_gain(self._entry)
        await raise_agent_command_failed(
            self._entry.runtime_data.api.async_activate_doorbell_video(audio=audio)
        )

    async def stop(self) -> None:
        """Stop the active C300X doorbell video session."""

        ensure_doorbell_video_supported(self._entry)
        prepare_stop = getattr(
            self._entry.runtime_data,
            "prepare_doorbell_video_stop",
            None,
        )
        if prepare_stop is not None:
            await prepare_stop()
        if await _async_agent_already_reports_idle(self._entry):
            return
        await raise_agent_command_failed(
            self._entry.runtime_data.api.async_stop_doorbell_video()
        )


async def _async_agent_already_reports_idle(entry: Any) -> bool:
    """Return true when the native media state is already idle."""

    try:
        status = await entry.runtime_data.api.async_doorbell_video_status()
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(status, Mapping):
        return False
    facts = media_state_input_from_video_status(status)
    return derive_media_state(facts).state is MediaState.IDLE
