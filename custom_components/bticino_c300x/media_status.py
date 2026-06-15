"""Media payload helpers for C300X camera and call entities."""

from __future__ import annotations

from typing import Any


def home_call_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Return the Home Call payload regardless of wrapper shape."""

    payload = data.get("home_call")
    if isinstance(payload, dict):
        return payload
    nested = data.get("data")
    if isinstance(nested, dict):
        payload = nested.get("home_call")
        if isinstance(payload, dict):
            return payload
        return nested
    return {}
