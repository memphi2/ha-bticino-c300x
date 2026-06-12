"""Media status helpers for the C300X camera and call entities."""

from __future__ import annotations

from typing import Any


def status_is_call_media_active(status: dict[str, Any]) -> bool:
    """Return true when the native bridge is already serving call media."""

    bridge = status.get("bridge") if isinstance(status.get("bridge"), dict) else {}
    owner = str(status.get("media_owner") or bridge.get("media_owner") or "").lower()
    return owner in {"ring", "home_call"} or bool(
        bridge.get("ring_call_active") or bridge.get("ring_media_active")
        or bridge.get("home_call_running") or bridge.get("home_call_active")
    )


def status_is_external_media_active(status: dict[str, Any]) -> bool:
    """Return true while the native agent sees a non-HA doorbell media window."""

    bridge = status.get("bridge") if isinstance(status.get("bridge"), dict) else {}
    return bool(status.get("external_media_active") or bridge.get("external_media_active"))


def status_is_home_call_media_active(status: dict[str, Any]) -> bool:
    """Return true when the native bridge is serving an audio-only home call."""

    bridge = status.get("bridge") if isinstance(status.get("bridge"), dict) else {}
    owner = str(status.get("media_owner") or bridge.get("media_owner") or "").lower()
    return owner == "home_call" or bool(
        bridge.get("home_call_running") or bridge.get("home_call_active")
    )


def status_is_unanswered_ring_call(status: dict[str, Any]) -> bool:
    """Return true for ring early media before HA has answered the call."""

    bridge = status.get("bridge") if isinstance(status.get("bridge"), dict) else {}
    owner = str(status.get("media_owner") or bridge.get("media_owner") or "").lower()
    return (
        (owner == "ring" or bool(bridge.get("ring_call_active") or bridge.get("ring_media_active")))
        and not bool(
            bridge.get("ring_answer_requested")
            or bridge.get("ring_answered")
            or bridge.get("ring_audio_active")
        )
    )


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
