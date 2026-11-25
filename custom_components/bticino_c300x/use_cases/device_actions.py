"""Device and Home Assistant action service use cases."""

from __future__ import annotations

from typing import Any

from homeassistant.core import Context, HomeAssistant

from ..action import ActionValidationError
from ..exceptions import service_validation_error
from ..executor import (
    async_execute_action,
    async_execute_alarm_command,
    async_unlock_door,
)
from .common import raise_agent_command_failed


class DeviceActionsUseCase:
    """Run user-facing C300X and Home Assistant actions."""

    def __init__(self, hass: HomeAssistant, entry: Any) -> None:
        self._hass = hass
        self._entry = entry

    async def run_action(self, action_id: str, *, context: Context | None = None) -> None:
        """Run one allowlisted Home Assistant action."""

        try:
            await async_execute_action(
                self._hass, self._entry, action_id,
                blocking=True,
                context=context,
            )
        except ActionValidationError as err:
            raise service_validation_error("invalid_action_id") from err
        except KeyError as err:
            raise service_validation_error(
                "unknown_action",
                {"action_id": str(err.args[0])},
            ) from err

    async def alarm_command(
        self,
        command: str,
        code: str | None,
        *,
        force: bool = False,
        context: Context | None = None,
    ) -> None:
        """Forward one alarm command to the configured HA alarm entity."""

        try:
            result = await async_execute_alarm_command(
                self._hass,
                self._entry,
                command,
                code,
                force=force,
                context=context,
            )
        except ActionValidationError as err:
            raise service_validation_error("invalid_alarm_command") from err
        except ValueError as err:
            raise service_validation_error("alarm_not_configured") from err

        # The display bridge consumes structured errors. HA service callers need
        # an exception so rejected commands also stop dependent automation steps.
        if result.get("ok") is not True:
            error_key = {
                "not_ready_to_arm": "alarm_not_ready",
                "invalid_code": "alarm_invalid_code",
                "alarm_state_unchanged": "alarm_state_unconfirmed",
            }.get(str(result.get("error") or ""), "alarm_command_rejected")
            raise service_validation_error(error_key)

    async def unlock(self, unit_id: str = "current", call_id: str | None = None) -> None:
        """Open an outdoor unit's lock (``current``: the calling unit)."""

        await raise_agent_command_failed(
            async_unlock_door(self._hass, self._entry, unit_id, call_id),
            entry=self._entry,
        )
