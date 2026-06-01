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
    "view_requeste",
    "pressed",
    "ring",
    "doorbell_pressed",
    "doorbell_view_requested",
    "doorbell_media_closed",
    "media_closed",
    "closed",
)
_DOORBELL_STATE_SET = frozenset(DOORBELL_STATES)


def normalize_doorbell_state(state: dict[str, Any]) -> str | None:
    """Return a supported raw doorbell state from an agent state payload."""

    raw = state.get("doorbell")
    if raw is None and isinstance(state.get("state"), dict):
        raw = state["state"].get("doorbell")
    return raw_doorbell_state_value(raw)


def raw_doorbell_state_value(value: Any) -> str | None:
    """Return a supported raw doorbell state without semantic remapping."""

    raw = str(value or "").strip().lower()
    return raw if raw in _DOORBELL_STATE_SET else None
