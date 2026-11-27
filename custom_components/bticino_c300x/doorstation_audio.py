"""Keep the agent's door level and fine adjustment equal to the options."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from contextlib import suppress
from typing import Any

from .api_errors import C300XAgentApiError
from .config_audio import audio_fine_gain_db_or_default, door_audio_level_db_or_default
from .const import (
    CONF_AUDIO_FINE_GAIN_DB,
    CONF_DOOR_AUDIO_LEVEL_DB,
    DEFAULT_AUDIO_FINE_GAIN_DB,
    DEFAULT_DOOR_AUDIO_LEVEL_DB,
)
from .entry_config import entry_config_value
from .use_cases.common import ensure_current_runtime
from .value_parsing import optional_mapping

_LOGGER = logging.getLogger(__name__)


def door_audio_level_db(entry: Any) -> int:
    """Return the configured door level in dB (0 is stock)."""

    return door_audio_level_db_or_default(
        entry_config_value(entry, CONF_DOOR_AUDIO_LEVEL_DB, DEFAULT_DOOR_AUDIO_LEVEL_DB),
        DEFAULT_DOOR_AUDIO_LEVEL_DB,
    )


def audio_fine_gain_db(entry: Any) -> int:
    """Return the configured fine adjustment in dB."""

    return audio_fine_gain_db_or_default(
        entry_config_value(entry, CONF_AUDIO_FINE_GAIN_DB, DEFAULT_AUDIO_FINE_GAIN_DB),
        DEFAULT_AUDIO_FINE_GAIN_DB,
    )


def agent_audio_level(status: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return the agent's `bridge.audio_level` object, empty when not reported."""

    if not isinstance(status, Mapping):
        return {}
    return dict(optional_mapping(optional_mapping(status.get("bridge")).get("audio_level")))


def _agent_levels(status: Mapping[str, Any] | None) -> tuple[int, int] | None:
    level = agent_audio_level(status)
    door, fine = level.get("door_level_db"), level.get("fine_gain_db")
    if type(door) is not int or type(fine) is not int:
        return None
    return door, fine


async def async_ensure_doorstation_audio_level(
    entry: Any,
    *,
    status: Mapping[str, Any] | None = None,
) -> None:
    """Send the door level and fine adjustment when the agent has others.

    Best effort: a failed write must not block answering or starting the
    stream. The command that follows reaches the same agent and reports an
    unreachable agent or a rejected key itself, including the reauth flow.
    A failure is logged as a warning once per entry setup until a write or a
    matching agent level succeeds again; repeats go to the debug log.
    """

    runtime = entry.runtime_data
    ensure_current_runtime(entry, runtime)
    desired = (door_audio_level_db(entry), audio_fine_gain_db(entry))

    if status is None:
        with suppress(Exception):
            status = await runtime.api.async_doorbell_video_status()
        ensure_current_runtime(entry, runtime)

    if _agent_levels(status) == desired:
        _set_failed(runtime, False)
        return
    try:
        await runtime.api.async_set_doorstation_audio_level(*desired)
    except C300XAgentApiError as err:
        log = _LOGGER.debug if _failed(runtime) else _LOGGER.warning
        log("Setting the C300X door audio level failed: %s", err)
        _set_failed(runtime, True)
    else:
        _set_failed(runtime, False)


async def async_sync_doorstation_audio_level(entry: Any) -> None:
    """Send the levels once the entry is set up, without a stream waiting.

    Saving the options reloads the entry, so this also carries a lowered door
    level to the station right away instead of at the next stream or answer.
    Never raises but for cancellation: it runs in the startup background sync.
    """

    try:
        await async_ensure_doorstation_audio_level(entry)
    except asyncio.CancelledError:
        raise
    except Exception as err:  # noqa: BLE001 - a reload or a failed status read ends it
        _LOGGER.debug("C300X door audio level was not sent after setup: %s", err)


def _failed(runtime: Any) -> bool:
    return getattr(runtime, "doorstation_audio_level_failed", False) is True


def _set_failed(runtime: Any, failed: bool) -> None:
    with suppress(AttributeError):
        runtime.doorstation_audio_level_failed = failed
