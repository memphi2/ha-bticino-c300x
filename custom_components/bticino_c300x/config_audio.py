"""Audio level option validation helpers for C300X config flows."""

from __future__ import annotations

from typing import Any

from .const import AUDIO_FINE_GAIN_DB_MAX, AUDIO_FINE_GAIN_DB_MIN, DOOR_AUDIO_LEVELS_DB
from .schema_compat import vol


def _whole_db(value: Any) -> int:
    if isinstance(value, bool):
        raise vol.Invalid("invalid audio level")
    try:
        number = float(value)
    except (TypeError, ValueError) as err:
        raise vol.Invalid("invalid audio level") from err
    # NaN and infinities fail is_integer(); 6.0 from a slider counts as 6.
    if not number.is_integer():
        raise vol.Invalid("invalid audio level")
    return int(number)


def door_audio_level_db(value: Any) -> int:
    """Validate the door level: stock (0), +3, +6, +9 or +12 dB."""

    level = _whole_db(value)
    if level not in DOOR_AUDIO_LEVELS_DB:
        raise vol.Invalid("invalid audio level")
    return level


def audio_fine_gain_db(value: Any) -> int:
    """Validate the fine adjustment: whole dB from -10 to +10."""

    gain = _whole_db(value)
    if not AUDIO_FINE_GAIN_DB_MIN <= gain <= AUDIO_FINE_GAIN_DB_MAX:
        raise vol.Invalid("invalid audio level")
    return gain


def door_audio_level_db_or_default(value: Any, default: int) -> int:
    """Return a valid door level for persisted options."""

    try:
        return door_audio_level_db(value)
    except vol.Invalid:
        return default


def audio_fine_gain_db_or_default(value: Any, default: int) -> int:
    """Return a valid fine adjustment for persisted options."""

    try:
        return audio_fine_gain_db(value)
    except vol.Invalid:
        return default
