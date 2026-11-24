"""Runtime helpers for doorstation downstream audio gain."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from contextlib import suppress
from typing import Any

from .api_errors import C300XAgentApiError
from .config_audio import audio_gain_db_or_default
from .const import CONF_DOORSTATION_AUDIO_GAIN_DB, DEFAULT_DOORSTATION_AUDIO_GAIN_DB
from .entry_config import entry_config_value
from .use_cases.common import ensure_current_runtime
from .value_parsing import optional_mapping

_GAIN_EPSILON_DB = 0.05
_LOGGER = logging.getLogger(__name__)


def doorstation_audio_gain_db(entry: Any) -> float:
    """Return the configured live doorstation audio gain in dB."""

    return audio_gain_db_or_default(
        entry_config_value(
            entry,
            CONF_DOORSTATION_AUDIO_GAIN_DB,
            DEFAULT_DOORSTATION_AUDIO_GAIN_DB,
        ),
        DEFAULT_DOORSTATION_AUDIO_GAIN_DB,
    )


def agent_doorstation_audio_gain_db(status: Mapping[str, Any] | None) -> float | None:
    """Return the native agent's runtime doorstation audio gain when reported."""

    if not isinstance(status, Mapping):
        return None
    bridge = optional_mapping(status.get("bridge"))
    value = bridge.get(CONF_DOORSTATION_AUDIO_GAIN_DB)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def async_ensure_doorstation_audio_gain(
    entry: Any,
    *,
    status: Mapping[str, Any] | None = None,
) -> None:
    """Synchronize the native agent runtime gain only when the value is needed.

    Best effort: a failed gain write must not block answering or starting the
    stream. The command that follows reaches the same agent and reports an
    unreachable agent or a rejected key itself, including the reauth flow.
    """

    runtime = entry.runtime_data
    ensure_current_runtime(entry, runtime)
    desired = doorstation_audio_gain_db(entry)
    if abs(desired) < _GAIN_EPSILON_DB:
        desired = DEFAULT_DOORSTATION_AUDIO_GAIN_DB

    if status is None:
        with suppress(Exception):
            status = await runtime.api.async_doorbell_video_status()
        ensure_current_runtime(entry, runtime)

    current = agent_doorstation_audio_gain_db(status)
    if current is not None and abs(current - desired) < _GAIN_EPSILON_DB:
        return
    if current is None and abs(desired) < _GAIN_EPSILON_DB:
        return

    try:
        await runtime.api.async_set_doorstation_audio_gain_db(desired)
    except C300XAgentApiError as err:
        _LOGGER.warning("Setting the C300X doorstation audio gain failed: %s", err)
