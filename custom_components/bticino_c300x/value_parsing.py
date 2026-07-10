"""Small value parsing helpers shared across C300X modules."""

from __future__ import annotations

from collections.abc import Mapping
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


def optional_mapping(value: Any) -> dict[str, Any]:
    """Return a nested status Mapping as a plain dict, or an empty dict."""

    return dict(value) if isinstance(value, Mapping) else {}


def freeze_state_value(value: Any) -> Any:
    """Return a hashable, order-stable snapshot of an entity state value."""

    if isinstance(value, Mapping):
        return tuple(
            (str(key), freeze_state_value(item))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        )
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((freeze_state_value(item) for item in value), key=repr))
    if isinstance(value, (list, tuple)):
        return tuple(freeze_state_value(item) for item in value)
    return value
