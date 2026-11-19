"""Doorbell video service use cases."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ..camera_media.session_lifecycle import media_stop_scope
from ..camera_media.state_machine import (
    MediaState,
    derive_media_state,
    media_state_input_from_video_status,
)
from ..doorstation_audio import async_ensure_doorstation_audio_gain
from .common import (
    ensure_current_runtime,
    ensure_doorbell_video_supported,
    raise_agent_command_failed,
)


class DoorbellVideoUseCase:
    """Control the C300X doorbell video session."""

    def __init__(self, entry: Any) -> None:
        self._entry = entry

    async def activate(
        self, *, audio: bool = True, status: Mapping[str, Any] | None = None,
        before_activate: Callable[[], None] | None = None,
    ) -> None:
        """Activate or renew the C300X doorbell video session."""

        ensure_doorbell_video_supported(self._entry)
        runtime = self._entry.runtime_data
        ensure_current_runtime(self._entry, runtime)
        if audio:
            await async_ensure_doorstation_audio_gain(self._entry, status=status)
            ensure_current_runtime(self._entry, runtime)
        if before_activate is not None:
            before_activate()
        await raise_agent_command_failed(
            runtime.api.async_activate_doorbell_video(audio=audio), entry=self._entry,
        )

    async def stop(self) -> None:
        """Stop the active C300X doorbell video session."""

        ensure_doorbell_video_supported(self._entry)
        runtime = self._entry.runtime_data
        ensure_current_runtime(self._entry, runtime)
        prepare_stop = getattr(
            runtime.resources,
            "prepare_doorbell_video_stop",
            None,
        )
        with media_stop_scope(runtime.resources, "doorbell"):
            was_idle = await _async_agent_already_reports_idle(runtime.api)
            ensure_current_runtime(self._entry, runtime)
            if prepare_stop is not None:
                await prepare_stop()
                ensure_current_runtime(self._entry, runtime)
            if was_idle:
                return
            await raise_agent_command_failed(
                runtime.api.async_stop_doorbell_video(), entry=self._entry,
            )


async def _async_agent_already_reports_idle(api: Any) -> bool:
    """Return true when the native media state is already idle."""

    try:
        status = await api.async_doorbell_video_status()
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(status, Mapping):
        return False
    facts = media_state_input_from_video_status(status)
    return derive_media_state(facts).state is MediaState.IDLE
