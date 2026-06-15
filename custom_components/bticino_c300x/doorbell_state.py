"""Doorbell state helpers."""

from __future__ import annotations

from typing import Any

DOORBELL_STATE_IDLE = "idle"
DOORBELL_STATE_RINGING = "ringing"
DOORBELL_STATE_VIEW_REQUESTED = "view_requested"
DOORBELL_STATES = (
    DOORBELL_STATE_IDLE,
    DOORBELL_STATE_RINGING,
    DOORBELL_STATE_VIEW_REQUESTED,
)
_DOORBELL_STATE_SET = frozenset(DOORBELL_STATES)


def normalize_doorbell_state(state: dict[str, Any]) -> str | None:
    """Return a supported raw doorbell state from an agent state payload."""

    return raw_doorbell_state_value(state.get("doorbell"))


def raw_doorbell_state_value(value: Any) -> str | None:
    """Return a supported raw doorbell state without semantic remapping."""

    raw = str(value or "").strip().lower()
    return raw if raw in _DOORBELL_STATE_SET else None
