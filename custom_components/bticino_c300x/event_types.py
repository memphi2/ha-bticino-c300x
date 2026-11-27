"""Canonical C300X event type mappings and normalization helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DOORBELL_EVENTS = ("doorbell.pressed", "doorbell.view_requested")
DOORBELL_VIDEO_EVENTS = ("doorbell.media.closed",)
DOOR_UNLOCK_EVENTS = ("door_unlock.started", "door_unlock.ended")
STAIR_LIGHT_EVENTS = ("stair_light.activated", "stair_light.released")
ACTIVATION_EVENTS = ("activation.executed",)
# Calls owned by the agent (API 2), see docs/dev/multi-outdoor-units.md.
CALL_EVENTS = (
    "call.caller_identified", "call.answered", "call.view_started", "call.ended",
)
OUTDOOR_UNIT_EVENTS = ("outdoor_units.changed",)
HOME_CALL_EVENTS = ("home_call.started", "home_call.answered", "home_call.ended")
RINGER_EVENTS = ("ringer.muted", "ringer.unmuted", "ringer.volume_changed")
TOUCH_TONE_EVENTS = ("display.touch_tone_changed",)
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
    "call.caller_identified": "call_caller_identified",
    "call.answered": "call_answered",
    "call.view_started": "call_view_started",
    "call.ended": "call_ended",
    "outdoor_units.changed": "outdoor_units_changed",
    "home_call.started": "home_call_started",
    "home_call.answered": "home_call_answered",
    "home_call.ended": "home_call_ended",
    "ringer.muted": "ringer_muted",
    "display.touch_tone_changed": "display_touch_tone_changed",
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

# The fields the agent's push may name its event in (inbound only).
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
    """The key of a bticino_c300x_agent_event_received event: its event_type."""

    value = data.get("event_type")
    return value if isinstance(value, str) and value in SUPPORTED_HA_EVENT_TYPES else None


def payload_event_key(payload: Mapping[str, Any]) -> str | None:
    """The key of the agent's push, from its root or nested payload."""

    normalized = _payload_key(payload)
    if normalized is not None:
        return normalized
    nested = payload.get("data")
    if isinstance(nested, Mapping):
        return _payload_key(nested)
    return None


def _payload_key(data: Mapping[str, Any]) -> str | None:
    for key in _PAYLOAD_EVENT_KEYS:
        normalized = normalize_event_type(data.get(key))
        if normalized is not None:
            return normalized
    return None


def _normalize_event_key(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        return ""
    return normalized.replace(":", ".").replace(" ", "_")
