from __future__ import annotations

from custom_components.bticino_c300x.event_types import (
    agent_event_key,
    normalize_event_type,
    payload_event_key,
)


def test_normalize_event_type_handles_canonical_agent_events() -> None:
    assert normalize_event_type("doorbell.pressed") == "doorbell_pressed"
    assert normalize_event_type("doorbell_pressed") == "doorbell_pressed"
    assert normalize_event_type("agent.restarted") == "agent_restarted"
    assert normalize_event_type("doorbell.media.closed") == "doorbell_media_closed"
    assert normalize_event_type("activation.executed") == "activation_executed"
    assert normalize_event_type("home_call.ended") == "home_call_ended"
    assert normalize_event_type("memos.changed") == "memos_changed"
    assert normalize_event_type("system.metrics_changed") == "system_metrics_changed"
    assert normalize_event_type("agent.diagnostics_changed") == "agent_diagnostics_changed"
    assert (
        normalize_event_type("answering_machine.messages_changed")
        == "answering_machine_messages_changed"
    )


def test_agent_event_key_prefers_machine_fields() -> None:
    payload = {
        "event": "Türöffner gestartet",
        "event_type": "Türöffner gestartet",
        "event_key": "door_unlock_started",
    }
    assert agent_event_key(payload) == "door_unlock_started"


def test_payload_event_key_reads_nested_data() -> None:
    payload = {"data": {"event_type": "stair_light.activated"}}
    assert payload_event_key(payload) == "stair_light_activated"
