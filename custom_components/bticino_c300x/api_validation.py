"""Validation helpers for C300X device-agent API inputs."""

from __future__ import annotations

from typing import Any

from .api_errors import C300XAgentApiResponseError
from .validation_patterns import (
    ACTIVATION_ID_RE,
    LOCK_ID_RE,
    MEMO_ID_RE,
    STAIR_LIGHT_ADDRESS_RE,
    VIDEO_MESSAGE_ID_RE,
)

MAX_TEXT_MEMO_BYTES = 512


def normalize_stair_light_address(address: Any) -> str:
    """Validate and normalize a staircase-light OpenWebNet address segment."""

    return _normalize_pattern_value(
        address,
        STAIR_LIGHT_ADDRESS_RE,
        error="invalid staircase light address",
    )


def normalize_lock_id(lock_id: Any) -> str:
    """Validate and normalize a configured C300X lock id."""

    return _normalize_pattern_value(lock_id, LOCK_ID_RE, default="default", error="invalid lock id")


def normalize_activation_id(activation_id: Any) -> str:
    """Validate and normalize a configured C300X activation id."""

    return _normalize_pattern_value(
        activation_id,
        ACTIVATION_ID_RE,
        error="invalid activation id",
    )


def normalize_memo_id(memo_id: Any) -> str:
    """Validate and normalize a manual memo id."""

    return _normalize_pattern_value(memo_id, MEMO_ID_RE, error="invalid memo id")


def normalize_text_memo_text(text: Any) -> str:
    """Normalize text-memo content before sending it to the device agent."""

    if not isinstance(text, str):
        raise C300XAgentApiResponseError("text memo content must be a string")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if "\x00" in normalized:
        raise C300XAgentApiResponseError("text memo content contains a NUL byte")
    if not normalized.strip():
        raise C300XAgentApiResponseError("text memo content must not be empty")
    if len(normalized.encode()) > MAX_TEXT_MEMO_BYTES:
        raise C300XAgentApiResponseError("text memo content is too long")
    return normalized


def normalize_video_message_id(message_id: Any) -> str:
    """Validate and normalize a stored answering-machine video message id."""

    return _normalize_pattern_value(
        message_id,
        VIDEO_MESSAGE_ID_RE,
        error="invalid video message id",
    )


def _normalize_pattern_value(
    value: Any,
    pattern: Any,
    *,
    error: str,
    default: str = "",
) -> str:
    """Normalize one string value and validate it against a compiled pattern."""

    normalized = str(value or default).strip()
    if not pattern.fullmatch(normalized):
        raise C300XAgentApiResponseError(error)
    return normalized
