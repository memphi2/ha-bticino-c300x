"""Doorbell ring-call service use cases."""

from __future__ import annotations

from typing import Any

from .common import ensure_doorbell_call_supported, raise_agent_command_failed


class RingCallUseCase:
    """Control the active C300X doorbell ring call."""

    def __init__(self, entry: Any) -> None:
        self._entry = entry

    async def answer(self) -> None:
        """Answer the active C300X doorbell ring call through the agent."""

        ensure_doorbell_call_supported(self._entry)
        await raise_agent_command_failed(
            self._entry.runtime_data.api.async_answer_doorbell_call()
        )

    async def hangup(self) -> None:
        """Hang up the active C300X doorbell ring call through the agent."""

        ensure_doorbell_call_supported(self._entry)
        prepare_stop = getattr(
            self._entry.runtime_data,
            "prepare_doorbell_video_stop",
            None,
        )
        if prepare_stop is not None:
            await prepare_stop()
        await raise_agent_command_failed(
            self._entry.runtime_data.api.async_hangup_doorbell_call()
        )
