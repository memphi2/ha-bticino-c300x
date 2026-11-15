"""Doorbell ring-call service use cases."""

from __future__ import annotations

from typing import Any

from ..camera_media.session_lifecycle import media_stop_scope
from ..doorstation_audio import async_ensure_doorstation_audio_gain
from .common import (
    ensure_current_runtime,
    ensure_doorbell_call_supported,
    raise_agent_command_failed,
)


class RingCallUseCase:
    """Control the active C300X doorbell ring call."""

    def __init__(self, entry: Any) -> None:
        self._entry = entry

    async def answer(self) -> None:
        """Answer the active C300X doorbell ring call through the agent."""

        ensure_doorbell_call_supported(self._entry)
        runtime = self._entry.runtime_data
        ensure_current_runtime(self._entry, runtime)
        status = await runtime.api.async_doorbell_video_status()
        ensure_current_runtime(self._entry, runtime)
        await async_ensure_doorstation_audio_gain(self._entry, status=status)
        ensure_current_runtime(self._entry, runtime)
        await raise_agent_command_failed(
            runtime.api.async_answer_doorbell_call()
        )

    async def hangup(self) -> None:
        """Hang up the active C300X doorbell ring call through the agent."""

        ensure_doorbell_call_supported(self._entry)
        runtime = self._entry.runtime_data
        ensure_current_runtime(self._entry, runtime)
        prepare_stop = getattr(
            runtime.resources,
            "prepare_doorbell_video_stop",
            None,
        )
        with media_stop_scope(runtime.resources, "doorbell"):
            if prepare_stop is not None:
                await prepare_stop()
                ensure_current_runtime(self._entry, runtime)
            await raise_agent_command_failed(
                runtime.api.async_hangup_doorbell_call()
            )
