"""Home-call service use cases."""

from __future__ import annotations

from typing import Any

from .common import ensure_home_call_supported, raise_agent_command_failed


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
            )
        )

    async def stop(self) -> None:
        """Stop the local Home Call to the C300X."""

        ensure_home_call_supported(self._entry)
        await raise_agent_command_failed(
            self._entry.runtime_data.api.async_stop_home_call()
        )
