from __future__ import annotations

import re
from pathlib import Path

from custom_components.bticino_c300x.event_types import (
    HA_EVENT_TYPES,
    agent_event_key,
    normalize_event_type,
    payload_event_key,
)

ROOT = Path(__file__).resolve().parents[1]
EVENT_LITERAL_RE = re.compile(r'"([a-z_]+\.[a-z_]+)"')
EVENT_CALL_RE = re.compile(
    r"(?P<call>dispatch_event(?:_internal|_snapshot)?|"
    r"c300x_video_dispatch_event|dispatch_home_call_state_event|"
    r"c300x_copy_string)\s*\((?P<args>.*?)\);",
    re.DOTALL,
)


def test_normalize_event_type_handles_canonical_agent_events() -> None:
    assert normalize_event_type("doorbell.pressed") == "doorbell_pressed"
    assert normalize_event_type("doorbell_pressed") == "doorbell_pressed"
    assert normalize_event_type("agent.restarted") == "agent_restarted"
    assert normalize_event_type("doorbell.media.closed") == "doorbell_media_closed"
    assert normalize_event_type("stair_light.released") == "stair_light_released"
    assert normalize_event_type("activation.executed") == "activation_executed"
    assert normalize_event_type("home_call.ended") == "home_call_ended"
    assert normalize_event_type("ringer.volume_changed") == "ringer_volume_changed"
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
    payload = {"data": {"event_type": "stair_light.released"}}
    assert payload_event_key(payload) == "stair_light_released"


def test_native_agent_event_literals_are_mapped_to_ha_event_types() -> None:
    native_events: set[str] = set()

    for path in (ROOT / "native_agent" / "src").glob("*.c"):
        text = path.read_text(encoding="utf-8")
        for match in EVENT_CALL_RE.finditer(text):
            call = match.group("call")
            args = match.group("args").strip()
            if call == "c300x_copy_string" and not args.startswith("type, type_len"):
                continue
            native_events.update(EVENT_LITERAL_RE.findall(args))

    assert native_events
    assert native_events <= set(HA_EVENT_TYPES)
