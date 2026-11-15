"""Exact UTF-8 wire encoding and body budget for the native display bridge."""

import json
from typing import Any

# Leave room for HTTP headers inside the native agent's 32 KiB buffer.
DASHBOARD_RESPONSE_MAX_BYTES = 30 * 1024


def display_json_dumps(value: Any) -> str:
    """Avoid ASCII escape expansion without changing JSON values."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def display_json_size(value: Any) -> int:
    return len(display_json_dumps(value).encode("utf-8"))


def dashboard_response_size(payload: dict[str, Any]) -> int:
    """Include the fixed-width revision appended by the webhook."""
    return display_json_size({**payload, "revision": "0" * 16})
