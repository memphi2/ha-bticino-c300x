"""Media payload helpers for C300X camera and call entities."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .value_parsing import optional_mapping


def rtsp_client_count_from_status(status: Mapping[str, Any] | None) -> int | None:
    """Return the native RTSP client count if the agent reported it."""

    if status is None:
        return None
    bridge = optional_mapping(status.get("bridge"))
    clients = bridge.get("clients")
    if clients is None:
        return None
    try:
        return int(clients)
    except (TypeError, ValueError):
        return None


def home_call_payload(data: Mapping[str, Any]) -> dict[str, Any]:
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
