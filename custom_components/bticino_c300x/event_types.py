"""Canonical C300X event type mappings and normalization helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DOORBELL_EVENTS = ("doorbell.pressed", "doorbell.view_requested")
DOORBELL_VIDEO_EVENTS = ("doorbell.media.closed",)
DOOR_UNLOCK_EVENTS = ("door_unlock.started", "door_unlock.ended")
STAIR_LIGHT_EVENTS = ("stair_light.activated", "stair_light.released")
ACTIVATION_EVENTS = ("activation.executed",)
CALL_EVENTS = ("call.started", "call.ended")
HOME_CALL_EVENTS = ("home_call.started", "home_call.answered", "home_call.ended")
RINGER_EVENTS = ("ringer.muted", "ringer.unmuted", "ringer.volume_changed")
SMARTPHONE_FORWARDING_EVENTS = ("smartphone_forwarding.changed",)
ANSWERING_MACHINE_EVENTS = ("answering_machine.messages_changed",)
MEMO_EVENTS = ("memos.changed",)
SYSTEM_METRICS_EVENTS = ("system.metrics_changed",)
DIAGNOSTICS_EVENTS = ("agent.diagnostics_changed",)
ALWAYS_REGISTERED_EVENTS = ("agent.restarted",)

HA_EVENT_TYPES: dict[str, str] = {
    "doorbell.pressed": "doorbell_pressed",
    "doorbell.view_requested": "doorbell_view_requested",
    "doorbell.media.closed": "doorbell_media_closed",
    "door_unlock.started": "door_unlock_started",
    "door_unlock.ended": "door_unlock_ended",
    "stair_light.activated": "stair_light_activated",
    "stair_light.released": "stair_light_released",
    "activation.executed": "activation_executed",
    "call.started": "call_started",
    "call.ended": "call_ended",
    "home_call.started": "home_call_started",
    "home_call.answered": "home_call_answered",
    "home_call.ended": "home_call_ended",
    "ringer.muted": "ringer_muted",
    "ringer.unmuted": "ringer_unmuted",
    "ringer.volume_changed": "ringer_volume_changed",
    "smartphone_forwarding.changed": "smartphone_forwarding_changed",
    "answering_machine.messages_changed": "answering_machine_messages_changed",
    "memos.changed": "memos_changed",
    "system.metrics_changed": "system_metrics_changed",
    "agent.diagnostics_changed": "agent_diagnostics_changed",
    "agent.restarted": "agent_restarted",
}
SUPPORTED_HA_EVENT_TYPES = frozenset(HA_EVENT_TYPES.values())

_PAYLOAD_EVENT_KEYS = (
    "event_key",
    "event_type_key",
    "type",
    "event_type",
    "event",
    "event_value",
)


def normalize_event_type(value: Any) -> str | None:
    """Normalize any raw callback event value into a canonical HA event key."""

    if value is None:
        return None
    key = _normalize_event_key(str(value))
    if not key:
        return None
    if key in SUPPORTED_HA_EVENT_TYPES:
        return key

    mapped = HA_EVENT_TYPES.get(key)
    if mapped is not None:
        return mapped

    if "_" in key:
        dotted = key.replace("_", ".")
        mapped = HA_EVENT_TYPES.get(dotted)
        if mapped is not None:
            return mapped

    return None


def agent_event_key(data: Mapping[str, Any]) -> str | None:
    """Extract and normalize a agent event key from an event payload mapping."""

    for key in _PAYLOAD_EVENT_KEYS:
        normalized = normalize_event_type(data.get(key))
        if normalized is not None:
            return normalized
    return None


def payload_event_key(payload: Mapping[str, Any]) -> str | None:
    """Extract and normalize a agent event key from root or nested payload keys."""

    normalized = agent_event_key(payload)
    if normalized is not None:
        return normalized
    nested = payload.get("data")
    if isinstance(nested, Mapping):
        return agent_event_key(nested)
    return None


def _normalize_event_key(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        return ""
    return normalized.replace(":", ".").replace(" ", "_")
