"""Doorbell video service use cases."""

from __future__ import annotations

from typing import Any

from .common import ensure_doorbell_video_supported, raise_agent_command_failed


class DoorbellVideoUseCase:
    """Control the C300X doorbell video session."""

    def __init__(self, entry: Any) -> None:
        self._entry = entry

    async def activate(self, *, audio: bool = True) -> None:
        """Activate or renew the C300X doorbell video session."""

        ensure_doorbell_video_supported(self._entry)
        await raise_agent_command_failed(
            self._entry.runtime_data.api.async_activate_doorbell_video(audio=audio)
        )

    async def stop(self) -> None:
        """Stop the active C300X doorbell video session."""

        ensure_doorbell_video_supported(self._entry)
        await raise_agent_command_failed(
            self._entry.runtime_data.api.async_stop_doorbell_video()
        )
