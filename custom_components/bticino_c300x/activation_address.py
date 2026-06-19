"""OpenWebNet activation address helpers."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from .const import (
    DEFAULT_STAIR_LIGHT_N,
    DEFAULT_STAIR_LIGHT_P,
)


def normalize_stair_light_part(value: Any, *, default: str) -> str:
    """Return a two-digit P/N value used by the firmware UI."""

    raw = str(default if value in (None, "") else value).strip()
    if not raw.isdigit() or len(raw) > 2:
        raise vol.Invalid("invalid staircase light address part")
    return f"{int(raw):02d}"


def stair_light_where_from_parts(p_value: Any, n_value: Any) -> str:
    """Return the OpenWebNet where segment for firmware P/N values."""

    p_part = normalize_stair_light_part(p_value, default=DEFAULT_STAIR_LIGHT_P)
    n_part = normalize_stair_light_part(n_value, default=DEFAULT_STAIR_LIGHT_N)
    return f"{int(p_part)}{int(n_part)}"


def stair_light_where_from_entry_values(
    p_value: Any,
    n_value: Any,
) -> str:
    """Return the configured OpenWebNet where segment from firmware P/N values."""

    return stair_light_where_from_parts(p_value, n_value)
