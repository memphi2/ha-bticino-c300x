"""The camera quality area of the settings: bit rate and frame rate of the stream.

The two values live on the device, not in the entry: the area reads them when
it opens and saves both in one write, after which the device restarts once.
It lives here as a mixin so the flow module stays within its size budget.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .api import C300XAgentApiError
from .capabilities import entry_maintenance_action_is_advertised
from .schema_compat import vol

BITRATE = "bitrate_kbps"
FPS = "fps"


def camera_quality_offered(entry: Any) -> bool:
    """The agent offers the setting (not on firmware 3.0.x)."""

    return entry_maintenance_action_is_advertised(entry, "camera_quality")


def _number(minimum: int, maximum: int, step: int, unit: str) -> NumberSelector:
    return NumberSelector(NumberSelectorConfig(
        min=minimum, max=maximum, step=step, mode=NumberSelectorMode.BOX, unit_of_measurement=unit,
    ))


def _limit(status: Mapping[str, Any], key: str, fallback: int) -> int:
    value = status.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else fallback


def _schema(status: Mapping[str, Any], values: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema({
        vol.Required(BITRATE, default=values[BITRATE]): _number(
            _limit(status, "bitrate_min", 300), _limit(status, "bitrate_max", 3000), 50, "kbit/s"),
        vol.Required(FPS, default=values[FPS]): _number(
            _limit(status, "fps_min", 5), _limit(status, "fps_max", 25), 1, "fps"),
    })


def _placeholders(status: Mapping[str, Any]) -> dict[str, str]:
    running = (status.get("running_bitrate_kbps"), status.get("running_fps"))
    known = all(isinstance(value, int) and value > 0 for value in running)
    return {"running": f"{running[0]} kbit/s, {running[1]} fps" if known else "-"}


class CameraQualityOptionsStep:
    """The camera quality area of the options menu."""

    async def async_step_camera_quality(
        self: Any,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Show the saved values and save changed ones, restarting the device once."""

        runtime = getattr(self._config_entry, "runtime_data", None)
        api = getattr(runtime, "api", None)
        problem = ""
        try:
            if api is None:
                raise C300XAgentApiError("not connected")
            status = await api.async_camera_quality()
        except C300XAgentApiError:
            problem, status = "cannot_connect", {}
        if not problem and status.get("supported") is not True:
            problem = "camera_quality_unsupported"
        if problem:
            # Nothing to change: the form only says why, and submitting it
            # goes back to the menu.
            if user_input is not None:
                return cast(ConfigFlowResult, await self.async_step_init())
            return cast(ConfigFlowResult, self.async_show_form(
                step_id="camera_quality", data_schema=vol.Schema({}), errors={"base": problem},
                description_placeholders=_placeholders(status),
            ))
        saved = {BITRATE: status.get(BITRATE), FPS: status.get(FPS)}
        errors: dict[str, str] = {}
        if user_input is not None:
            wanted = {key: int(user_input[key]) for key in (BITRATE, FPS)}
            changes = {key: value for key, value in wanted.items() if value != saved[key]}
            if not changes:
                return cast(ConfigFlowResult, await self.async_step_init())
            try:
                await api.async_camera_quality(**changes)
            except C300XAgentApiError:
                errors["base"] = "camera_quality_failed"
            else:
                return cast(ConfigFlowResult, await self.async_step_init())
        return cast(ConfigFlowResult, self.async_show_form(
            step_id="camera_quality",
            data_schema=_schema(status, saved if user_input is None else user_input),
            errors=errors,
            description_placeholders=_placeholders(status),
        ))
