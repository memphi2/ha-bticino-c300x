from __future__ import annotations

import re
from pathlib import Path

from custom_components.bticino_c300x.event_types import (
    HA_EVENT_TYPES,
    agent_event_key,
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


def test_agent_event_key_reads_only_the_bus_event_type() -> None:
    assert agent_event_key({"event_type": "door_unlock_started"}) == "door_unlock_started"
    # No other field, no label, no agent notation: the 3.1 bus payload only.
    for data in (
        {"event_key": "door_unlock_started"}, {"event_type_key": "door_unlock_started"},
        {"event_value": "door_unlock_started"}, {"event": "door_unlock_started"},
        {"event_type": "Türöffner gestartet"}, {"event_type": "door_unlock.started"},
    ):
        assert agent_event_key(data) is None, data


def test_payload_event_key_reads_the_agents_type() -> None:
    for agent, key in HA_EVENT_TYPES.items():
        assert payload_event_key({"type": agent}) == key
    # Only the agent's dotted "type": no other field, spelling or nesting.
    for payload in (
        {"type": "stair_light_released"}, {"type": "Stair_Light.Released"},
        {"type": "stair_light:released"}, {"type": "stair light.released"},
        {"event": "stair_light.released"}, {"event_type": "stair_light.released"},
        {"event_key": "stair_light_released"}, {"data": {"type": "stair_light.released"}},
        {"type": None}, {},
    ):
        assert payload_event_key(payload) is None, payload


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
