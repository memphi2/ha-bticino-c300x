"""Shared service field names and validators for BTicino C300X services."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from .api import C300XAgentApiResponseError, normalize_text_memo_text
from .const import MAX_HOME_CALL_DURATION_SECONDS
from .validation_patterns import ACTIVATION_ID_RE, LOCK_ID_RE, STAIR_LIGHT_ADDRESS_RE

ATTR_ACTION_ID = "action_id"
ATTR_ACTIVATION_ID = "activation_id"
ATTR_ADDRESS = "address"
ATTR_AUDIO = "audio"
ATTR_CODE = "code"
ATTR_COMMAND = "command"
ATTR_ENTRY_ID = "entry_id"
ATTR_FORCE = "force"
ATTR_DURATION_SECONDS = "duration_seconds"
ATTR_LOCK_ID = "lock_id"
ATTR_MEDIA_PLAYER_ENTITY_ID = "media_player_entity_id"
ATTR_OUTPUT_PATH = "output_path"
ATTR_INCLUDE_AUDIO = "include_audio"
ATTR_WAV_OUTPUT_DIR = "wav_output_dir"
ATTR_ANNOUNCEMENT_PATH = "announcement_path"
ATTR_CAPTURE_PATH = "capture_path"
ATTR_WAV_PATH = "wav_path"
ATTR_RESULT_PATH = "result_path"
ATTR_WYOMING_HOST = "wyoming_host"
ATTR_WYOMING_PORT = "wyoming_port"
ATTR_LANGUAGE = "language"
ATTR_EXPECTED_PHRASE = "expected_phrase"
ATTR_DECISION_PATH = "decision_path"
ATTR_UNLOCK_ON_MATCH = "unlock_on_match"
ATTR_READ = "read"
ATTR_TEXT = "text"


def boolean_service_value(value: Any) -> bool:
    """Validate service booleans without relying on HA-private helper names."""

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on", "enable", "enabled"}:
            return True
        if lowered in {"0", "false", "no", "off", "disable", "disabled"}:
            return False
    raise vol.Invalid("expected boolean")


def stair_light_address(value: str) -> str:
    """Validate service-level OpenWebNet stair-light address input."""

    address = _service_string(value).strip()
    if not STAIR_LIGHT_ADDRESS_RE.fullmatch(address):
        raise vol.Invalid("invalid staircase light address")
    return address


def lock_id(value: str) -> str:
    """Validate service-level C300X lock id input."""

    value = _service_string(value).strip()
    if not LOCK_ID_RE.fullmatch(value):
        raise vol.Invalid("invalid lock id")
    return value


def activation_id(value: str) -> str:
    """Validate service-level C300X activation id input."""

    value = _service_string(value).strip()
    if not ACTIVATION_ID_RE.fullmatch(value):
        raise vol.Invalid("invalid activation id")
    return value


def home_call_duration_seconds(value: Any) -> int:
    """Validate optional home-call duration."""

    try:
        duration_seconds = int(value)
    except (TypeError, ValueError) as err:
        raise vol.Invalid("invalid duration seconds") from err
    if duration_seconds < 0 or duration_seconds > MAX_HOME_CALL_DURATION_SECONDS:
        raise vol.Invalid("invalid duration seconds")
    return duration_seconds


def capture_duration_seconds(value: Any) -> int:
    """Validate service-level capture duration."""

    try:
        duration_seconds = int(value)
    except (TypeError, ValueError) as err:
        raise vol.Invalid("invalid duration seconds") from err
    if duration_seconds < 1 or duration_seconds > 15:
        raise vol.Invalid("invalid duration seconds")
    return duration_seconds


def wyoming_port(value: Any) -> int:
    """Validate Wyoming service port."""

    try:
        port = int(value)
    except (TypeError, ValueError) as err:
        raise vol.Invalid("invalid Wyoming port") from err
    if port < 1 or port > 65535:
        raise vol.Invalid("invalid Wyoming port")
    return port


def text_memo_text(value: Any) -> str:
    """Validate service-level text memo content."""

    try:
        return normalize_text_memo_text(value)
    except C300XAgentApiResponseError as err:
        raise vol.Invalid(str(err)) from err


def _service_string(value: Any) -> str:
    if value is None:
        raise vol.Invalid("string value is None")
    return str(value)
