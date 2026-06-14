"""Device and Home Assistant action service use cases."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from ..action import ActionValidationError
from ..exceptions import service_validation_error
from ..executor import (
    async_execute_action,
    async_execute_alarm_command,
    async_trigger_stair_light,
    async_unlock_door,
)
from .common import raise_agent_command_failed


class DeviceActionsUseCase:
    """Run user-facing C300X and Home Assistant actions."""

    def __init__(self, hass: HomeAssistant, entry: Any) -> None:
        self._hass = hass
        self._entry = entry

    async def run_action(self, action_id: str) -> None:
        """Run one allowlisted Home Assistant action."""

        try:
            await async_execute_action(self._hass, self._entry, action_id)
        except ActionValidationError as err:
            raise service_validation_error("invalid_action_id") from err
        except KeyError as err:
            raise service_validation_error(
                "unknown_action",
                {"action_id": str(err.args[0])},
            ) from err

    async def run_device_activation(self, activation_id: str) -> None:
        """Run one configured C300X device activation."""

        await raise_agent_command_failed(
            self._entry.runtime_data.api.async_run_device_activation(activation_id)
        )

    async def alarm_command(
        self,
        command: str,
        code: str | None,
        *,
        force: bool = False,
    ) -> None:
        """Forward one alarm command to the configured HA alarm entity."""

        try:
            await async_execute_alarm_command(
                self._hass,
                self._entry,
                command,
                code,
                force=force,
            )
        except ActionValidationError as err:
            raise service_validation_error("invalid_alarm_command") from err
        except ValueError as err:
            raise service_validation_error("alarm_not_configured") from err

    async def stair_light(self, address: str | None) -> None:
        """Trigger the configured stair-light command."""

        await raise_agent_command_failed(
            async_trigger_stair_light(self._hass, self._entry, address)
        )

    async def unlock(self, lock_id: str = "default") -> None:
        """Trigger the configured door-unlock command."""

        await raise_agent_command_failed(
            async_unlock_door(self._hass, self._entry, lock_id)
        )
