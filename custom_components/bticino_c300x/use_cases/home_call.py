"""Home-call service use cases."""

from __future__ import annotations

from typing import Any

from ..camera_media.session_lifecycle import media_stop_scope
from .common import (
    ensure_current_runtime,
    ensure_home_call_supported,
    raise_agent_command_failed,
)


class HomeCallUseCase:
    """Control local local Home Calls to the C300X."""

    def __init__(self, entry: Any) -> None:
        self._entry = entry

    async def start(self, *, duration_seconds: int | None = None) -> None:
        """Start a local Home Call to the C300X."""

        ensure_home_call_supported(self._entry)
        await raise_agent_command_failed(
            self._entry.runtime_data.api.async_start_home_call(
                duration_seconds=duration_seconds
            ),
            entry=self._entry,
        )

    async def stop(self) -> None:
        """Stop the local Home Call to the C300X."""

        ensure_home_call_supported(self._entry)
        runtime = self._entry.runtime_data
        ensure_current_runtime(self._entry, runtime)
        prepare_stop = getattr(
            runtime.resources,
            "prepare_home_call_stop",
            None,
        )
        with media_stop_scope(runtime.resources, "home_call"):
            if prepare_stop is not None:
                await prepare_stop()
                ensure_current_runtime(self._entry, runtime)
            await raise_agent_command_failed(
                runtime.api.async_stop_home_call(), entry=self._entry,
            )
