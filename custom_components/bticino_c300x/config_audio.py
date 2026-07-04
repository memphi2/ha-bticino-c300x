"""Audio option validation helpers for C300X config flows."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

AUDIO_GAIN_DB_MIN = -20.0
AUDIO_GAIN_DB_MAX = 20.0


def audio_gain_db(value: Any) -> float:
    """Validate a configurable C300X audio gain in dB."""

    try:
        gain = float(value)
    except (TypeError, ValueError) as err:
        raise vol.Invalid("invalid audio gain") from err
    if gain < AUDIO_GAIN_DB_MIN or gain > AUDIO_GAIN_DB_MAX:
        raise vol.Invalid("invalid audio gain")
    return gain


def audio_gain_db_or_default(value: Any, default: float) -> float:
    """Return a valid audio gain default for persisted options."""

    try:
        return audio_gain_db(value)
    except vol.Invalid:
        return default
