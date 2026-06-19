"""OpenWebNet activation address helpers."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from .const import (
    DEFAULT_STAIR_LIGHT_ADDRESS,
    DEFAULT_STAIR_LIGHT_N,
    DEFAULT_STAIR_LIGHT_P,
)
from .validation_patterns import STAIR_LIGHT_ADDRESS_RE


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


def stair_light_parts_from_where(where: Any) -> tuple[str, str]:
    """Return firmware P/N defaults for a simple OpenWebNet where segment."""

    raw = str(where or DEFAULT_STAIR_LIGHT_ADDRESS).strip()
    if not raw.isdigit():
        return DEFAULT_STAIR_LIGHT_P, DEFAULT_STAIR_LIGHT_N
    if len(raw) == 1:
        return f"0{raw}", DEFAULT_STAIR_LIGHT_N
    if len(raw) == 2:
        return f"0{raw[0]}", f"0{raw[1]}"
    if len(raw) == 3:
        return f"{int(raw[:2]):02d}", f"0{raw[2]}"
    return f"{int(raw[:2]):02d}", f"{int(raw[2:4]):02d}"


def stair_light_where_from_entry_values(
    p_value: Any,
    n_value: Any,
    legacy_where: Any = DEFAULT_STAIR_LIGHT_ADDRESS,
) -> str:
    """Return the configured OpenWebNet where segment with legacy fallback."""

    if p_value not in (None, "") or n_value not in (None, ""):
        return stair_light_where_from_parts(p_value, n_value)
    where = str(legacy_where or DEFAULT_STAIR_LIGHT_ADDRESS).strip()
    if not STAIR_LIGHT_ADDRESS_RE.fullmatch(where):
        return DEFAULT_STAIR_LIGHT_ADDRESS
    return where
