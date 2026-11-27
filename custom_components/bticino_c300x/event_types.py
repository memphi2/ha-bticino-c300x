"""The agent's event types and their stable Home Assistant keys."""

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
# The station's own call state (bt_answering_machine, *#8**35*<code>##).
STATION_CALL_STATE_EVENTS = ("station.call_state",)
OUTDOOR_UNIT_EVENTS = ("outdoor_units.changed",)
# A unit's door contact (bt_vct, *8*66/65*<where>##).
DOOR_CONTACT_EVENTS = ("door.opened", "door.closed")
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
    "station.call_state": "station_call_state",
    "outdoor_units.changed": "outdoor_units_changed",
    "door.opened": "door_opened",
    "door.closed": "door_closed",
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


def agent_event_key(data: Mapping[str, Any]) -> str | None:
    """The key of a bticino_c300x_agent_event_received event: its event_type."""

    value = data.get("event_type")
    return value if isinstance(value, str) and value in SUPPORTED_HA_EVENT_TYPES else None


def payload_event_key(payload: Mapping[str, Any]) -> str | None:
    """The key of the agent's push: its "type", in the agent's dotted form."""

    value = payload.get("type")
    return HA_EVENT_TYPES.get(value) if isinstance(value, str) else None
