"""The camera quality area of the settings: size, bit rate and frame rate of the stream.

The values live on the device, not in the entry: the area reads them when it
opens and saves them in one write, after which the device restarts once.
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
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import C300XAgentApiError
from .capabilities import entry_maintenance_action_is_advertised
from .schema_compat import vol

BITRATE = "bitrate_kbps"
FPS = "fps"
SIZE = "size"


def camera_quality_offered(entry: Any) -> bool:
    """The agent offers the setting; on firmware 3.0.x it is the low stream."""

    return entry_maintenance_action_is_advertised(entry, "camera_quality")


def _number(minimum: int, maximum: int, step: int, unit: str) -> NumberSelector:
    return NumberSelector(NumberSelectorConfig(
        min=minimum, max=maximum, step=step, mode=NumberSelectorMode.BOX, unit_of_measurement=unit,
    ))


def _limit(status: Mapping[str, Any], key: str, fallback: int) -> int:
    value = status.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else fallback


_FALLBACK = {"bitrate": (300, 3000), "fps": (5, 24)}


def _within(status: Mapping[str, Any], key: str, value: int) -> bool:
    """A new value inside the agent's limits; only the saved one may be outside."""
    low, high = (_limit(status, f"{key}_{end}", _FALLBACK[key][i]) for i, end in enumerate(("min", "max")))
    return low <= value <= high


def _range(status: Mapping[str, Any], key: str, fallback: tuple[int, int]) -> tuple[int, int]:
    """The limits, widened to a value the file already has: the agent keeps it."""
    low, high = _limit(status, f"{key}_min", fallback[0]), _limit(status, f"{key}_max", fallback[1])
    saved = _limit(status, key if key == "fps" else f"{key}_kbps", low)
    return min(low, saved), max(high, saved)


def _sizes(status: Mapping[str, Any]) -> list[str]:
    offered = [size for size in status.get("sizes") or [] if isinstance(size, str) and size]
    # A size the file already has but that is not offered can stay as it is.
    current = status.get(SIZE)
    if isinstance(current, str) and current and current not in offered:
        offered.append(current)
    return offered


def _schema(status: Mapping[str, Any], values: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema({
        vol.Required(SIZE, default=values[SIZE]): SelectSelector(SelectSelectorConfig(
            options=_sizes(status), mode=SelectSelectorMode.DROPDOWN)),
        vol.Required(BITRATE, default=values[BITRATE]): _number(*_range(status, "bitrate", _FALLBACK["bitrate"]), 10, "kbit/s"),
        vol.Required(FPS, default=values[FPS]): _number(*_range(status, "fps", _FALLBACK["fps"]), 1, "fps"),
    })


def _placeholders(status: Mapping[str, Any]) -> dict[str, str]:
    running = (status.get("running_bitrate_kbps"), status.get("running_fps"))
    known = all(isinstance(value, int) and value > 0 for value in running) and status.get("running_size")
    return {"running": f"{status['running_size']}, {running[0]} kbit/s, {running[1]} fps" if known else "-"}


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
            # goes back to the menu. Values sent meanwhile get the reason too.
            if user_input is not None and not user_input:
                return cast(ConfigFlowResult, await self.async_step_init())
            return cast(ConfigFlowResult, self.async_show_form(
                step_id="camera_quality", data_schema=vol.Schema({}), errors={"base": problem},
                description_placeholders=_placeholders(status),
            ))
        saved = {BITRATE: status.get(BITRATE), FPS: status.get(FPS), SIZE: status.get(SIZE)}
        errors: dict[str, str] = {}
        if user_input is not None and not all(key in user_input for key in (SIZE, BITRATE, FPS)):
            # The explanation without fields was sent after the device came back.
            user_input = None
        if user_input is not None:
            wanted = {**{key: int(user_input[key]) for key in (BITRATE, FPS)}, SIZE: str(user_input[SIZE])}
            changes = {key: value for key, value in wanted.items() if value != saved[key]}
            errors = {key: "camera_quality_out_of_range" for key, name in ((BITRATE, "bitrate"), (FPS, "fps"))
                      if key in changes and not _within(status, name, changes[key])}
            if not errors and not changes:
                return cast(ConfigFlowResult, await self.async_step_init())
            if not errors:
                try:
                    result = await api.async_camera_quality(**changes)
                except C300XAgentApiError:
                    errors["base"] = "camera_quality_failed"
                else:
                    # Restarts turned off in the agent: saved, but waiting.
                    if result.get("restart_required") is not True or result.get("rebooting") is not False:
                        return cast(ConfigFlowResult, await self.async_step_init())
                    errors["base"] = "camera_quality_restart_pending"
        return cast(ConfigFlowResult, self.async_show_form(
            step_id="camera_quality",
            data_schema=_schema(status, saved if user_input is None else user_input),
            errors=errors,
            description_placeholders=_placeholders(status),
        ))
