from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _function_body(text: str, name: str) -> str:
    return text.split(f"static int {name}", maxsplit=1)[1].split("\n}\n", maxsplit=1)[
        0
    ]


def test_udp_events_keep_bound_socket_when_multicast_join_fails() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    join_body = _function_body(text, "join_udp_event_multicast_group")
    create_body = _function_body(text, "create_udp_event_socket")

    assert "IP_ADD_MEMBERSHIP" in join_body
    assert "continuing with bound UDP socket" in join_body
    assert "close(fd)" not in join_body
    assert "(void)join_udp_event_multicast_group(fd, config);" in create_body
    assert create_body.index("join_udp_event_multicast_group") < create_body.rindex(
        "return fd;"
    )


def test_openwebnet_local_action_events_are_deduplicated_before_dispatch() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    dedupe_body = _function_body(text, "local_action_event_is_duplicate")
    map_body = _function_body(text, "map_openwebnet_event")

    assert "#define C300X_LOCAL_ACTION_EVENT_DEDUPE_MS 1000" in text
    assert "long long last_local_action_event_ms;" in text
    assert "char last_local_action_event_type[64];" in text
    assert "char last_local_action_address[C300X_MAX_ADDRESS_LEN];" in text
    assert "now = c300x_monotonic_ms();" in dedupe_body
    assert "now - previous < C300X_LOCAL_ACTION_EVENT_DEDUPE_MS" in dedupe_body
    assert 'strcmp(runtime->last_local_action_event_type, type) == 0' in dedupe_body
    assert 'strcmp(runtime->last_local_action_address, address) == 0' in dedupe_body
    assert 'strcmp(type, "door_unlock.started") == 0' in text
    assert 'strcmp(type, "door_unlock.ended") == 0' in text
    assert 'strcmp(type, "stair_light.activated") == 0' in text
    assert (
        'local_action_event_is_duplicate(runtime, "door_unlock.started", address)'
        in map_body
    )
    assert (
        'local_action_event_is_duplicate(runtime, "door_unlock.ended", address)'
        in map_body
    )
    assert (
        'local_action_event_is_duplicate(runtime, "stair_light.activated", address)'
        in map_body
    )
    assert map_body.index(
        'local_action_event_is_duplicate(runtime, "door_unlock.started", address)'
    ) < map_body.index('c300x_copy_string(type, type_len, "door_unlock.started")')
