"""Small value parsing helpers shared across C300X modules."""

from __future__ import annotations

from typing import Any

DEFAULT_TRUE_VALUES = frozenset({"true", "1", "on", "enabled", "yes"})
DEFAULT_FALSE_VALUES = frozenset({"false", "0", "off", "disabled", "no"})


def optional_bool(
    value: Any,
    *,
    true_values: frozenset[str] = DEFAULT_TRUE_VALUES,
    false_values: frozenset[str] = DEFAULT_FALSE_VALUES,
) -> bool | None:
    """Return a normalized optional bool from loose device-agent values."""

    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in true_values:
        return True
    if text in false_values:
        return False
    return None


def optional_int(value: Any, default: int | None = None) -> int | None:
    """Return a normalized optional integer."""

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def optional_string(value: Any) -> str | None:
    """Return a stripped optional string."""

    if value is None:
        return None
    text = str(value).strip()
    return text or None
