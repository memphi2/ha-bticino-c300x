"""Maintenance service use cases."""

from __future__ import annotations

from typing import Any

from .common import ensure_maintenance_action, raise_agent_command_failed


class MaintenanceUseCase:
    """Run explicit C300X maintenance actions."""

    def __init__(self, entry: Any) -> None:
        self._entry = entry

    async def reboot(self) -> None:
        """Reboot the C300X through the maintenance API."""

        ensure_maintenance_action(self._entry, "reboot")
        await raise_agent_command_failed(self._entry.runtime_data.api.async_reboot())

    async def reload_gui(self) -> None:
        """Reload the device GUI through the maintenance API."""

        ensure_maintenance_action(self._entry, "gui_reload")
        await raise_agent_command_failed(self._entry.runtime_data.api.async_reload_gui())
