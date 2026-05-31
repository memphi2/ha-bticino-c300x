"""Shared smartphone-forwarding normalization helpers."""

from __future__ import annotations

from typing import Any

from .const import (
    SMARTPHONE_FORWARDING_MODE_BLOCKED,
    SMARTPHONE_FORWARDING_MODE_ENABLED,
    SMARTPHONE_FORWARDING_MODE_IN_HOUSE_ONLY,
    SMARTPHONE_FORWARDING_MODES,
)

FORWARDING_STATE_BY_CODE: dict[int, str] = {
    0: SMARTPHONE_FORWARDING_MODE_ENABLED,
    1: SMARTPHONE_FORWARDING_MODE_IN_HOUSE_ONLY,
    2: SMARTPHONE_FORWARDING_MODE_BLOCKED,
}
FORWARDING_CODE_BY_STATE: dict[str, int] = {
    value: key for key, value in FORWARDING_STATE_BY_CODE.items()
}


def forwarding_state_from_value(value: Any) -> str | None:
    """Return normalized forwarding state text from bool/int/str payload values."""

    if isinstance(value, bool):
        return SMARTPHONE_FORWARDING_MODE_ENABLED if value else SMARTPHONE_FORWARDING_MODE_BLOCKED
    if isinstance(value, int):
        return FORWARDING_STATE_BY_CODE.get(value)
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text.isdigit():
        return FORWARDING_STATE_BY_CODE.get(int(text))
    if text in SMARTPHONE_FORWARDING_MODES:
        return text
    return None


def forwarding_mode_code_from_value(value: Any) -> int | None:
    """Return numeric forwarding mode code from bool/int/str payload values."""

    if isinstance(value, bool):
        return 0 if value else 2
    if isinstance(value, int):
        return value
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if text in FORWARDING_CODE_BY_STATE:
        return FORWARDING_CODE_BY_STATE[text]
    return None


def coerce_forwarding_mode_state(mode: Any, state: Any) -> dict[str, str | int | None]:
    """Return normalized forwarding mode/state pair for event and status payloads."""

    normalized_state = forwarding_state_from_value(state)
    normalized_mode = forwarding_mode_code_from_value(mode)

    if normalized_state is not None:
        if normalized_mode is None:
            normalized_mode = FORWARDING_CODE_BY_STATE.get(normalized_state)
        return {"mode": normalized_mode, "state": normalized_state}

    if normalized_mode is not None:
        return {
            "mode": normalized_mode,
            "state": FORWARDING_STATE_BY_CODE.get(normalized_mode, "unknown"),
        }

    fallback_state = forwarding_state_from_value(mode)
    if fallback_state is not None:
        return {
            "mode": FORWARDING_CODE_BY_STATE.get(fallback_state),
            "state": fallback_state,
        }

    return {"mode": None, "state": "unknown"}
