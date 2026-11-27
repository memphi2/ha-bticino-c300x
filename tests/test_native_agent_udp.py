from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _function_body(text: str, name: str) -> str:
    marker = f" {name}("
    name_index = -1
    while True:
        name_index = text.index(marker, name_index + 1)
        open_brace = text.find("{", name_index)
        semicolon = text.find(";", name_index, open_brace)
        if open_brace != -1 and semicolon == -1:
            start = text.rfind("\n", 0, name_index)
            return text[start + 1 :].split("\n}\n", maxsplit=1)[0]


def test_udp_events_keep_bound_socket_when_multicast_join_fails() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    join_body = _function_body(text, "join_udp_event_multicast_group")
    create_body = _function_body(text, "create_udp_event_socket")

    assert "IP_ADD_MEMBERSHIP" in join_body
    assert "continuing with bound UDP socket" in join_body
    assert "close(fd)" not in join_body
    # The socket stays bound; whether door events arrive is only noted.
    assert "*joined = join_udp_event_multicast_group(fd, config);" in create_body
    assert create_body.index("join_udp_event_multicast_group") < create_body.rindex(
        "return fd;"
    )


def test_openwebnet_local_action_events_are_deduplicated_before_dispatch() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    header = (ROOT / "native_agent" / "src" / "local_action_events.h").read_text(
        encoding="utf-8"
    )
    source = (ROOT / "native_agent" / "src" / "local_action_events.c").read_text(
        encoding="utf-8"
    )
    dedupe_body = _function_body(source, "c300x_local_action_event_is_duplicate")
    map_body = _function_body(text, "map_openwebnet_event")

    assert '#include "local_action_events.h"' in text
    assert "#define C300X_LOCAL_ACTION_EVENT_DEDUPE_MS 1000" in header
    assert "#define C300X_LOCAL_ACTION_EVENT_HISTORY 8" in header
    assert "struct c300x_local_action_event_marker" in header
    assert "int next_index;" in header
    assert (
        "struct c300x_local_action_event_marker "
        "items[C300X_LOCAL_ACTION_EVENT_HISTORY];"
    ) in header
    assert "struct c300x_local_action_events local_action_events;" in text
    assert (
        "for (int index = 0; index < C300X_LOCAL_ACTION_EVENT_HISTORY; index++)"
        in dedupe_body
    )
    assert (
        "now_ms - marker->occurred_ms < C300X_LOCAL_ACTION_EVENT_DEDUPE_MS"
        in dedupe_body
    )
    assert "strcmp(marker->type, type) == 0" in dedupe_body
    assert "strcmp(marker->address, address) == 0" in dedupe_body
    assert "c300x_local_action_event_remember(events, type, address, now_ms);" in dedupe_body
    assert 'strcmp(type, "door_unlock.started") == 0' in source
    assert 'strcmp(type, "door_unlock.ended") == 0' in source
    assert 'strcmp(type, "stair_light.activated") == 0' in source
    assert 'strcmp(type, "stair_light.released") == 0' in source
    assert (
        'c300x_local_action_event_is_duplicate(\n'
        "            runtime != NULL ? &runtime->local_action_events : NULL,\n"
        '            "door_unlock.started",'
        in map_body
    )
    assert (
        'c300x_local_action_event_is_duplicate(\n'
        "            runtime != NULL ? &runtime->local_action_events : NULL,\n"
        '            "door_unlock.ended",'
        in map_body
    )
    assert (
        'c300x_local_action_event_is_duplicate(\n'
        "            runtime != NULL ? &runtime->local_action_events : NULL,\n"
        '            "stair_light.activated",'
        in map_body
    )
    assert (
        'c300x_local_action_event_is_duplicate(\n'
        "            runtime != NULL ? &runtime->local_action_events : NULL,\n"
        '            "stair_light.released",'
        in map_body
    )
    assert map_body.index(
        'c300x_local_action_event_is_duplicate(\n'
        "            runtime != NULL ? &runtime->local_action_events : NULL,\n"
        '            "door_unlock.started",'
    ) < map_body.index('c300x_copy_string(type, type_len, "door_unlock.started")')


def test_lock_activation_run_emits_unlock_events_and_dedupes_echoes() -> None:
    src = ROOT / "native_agent" / "src"
    routes = (src / "http_activations.c").read_text(encoding="utf-8")
    http = (src / "http.c").read_text(encoding="utf-8")
    activation_body = _function_body(routes, "activation_run")
    event_body = _function_body(routes, "lock_event")
    remember_body = _function_body(routes, "remember")
    wiring_body = _function_body(http, "activation_routes")
    emit_body = _function_body(http, "emit_activation_event")

    assert 'strcmp(activation->type, "lock") == 0' in activation_body
    assert 'lock_event(routes, activation, "door_unlock.started", press);' in activation_body
    assert 'lock_event(routes, activation, "door_unlock.ended", release);' in activation_body
    # The events follow a frame the bus took, never a failed send.
    assert activation_body.index("reply_bus_error(client_fd, error);") < activation_body.index(
        'lock_event(routes, activation, "door_unlock.started", press);'
    )
    assert '\\"source\\":\\"activation\\"' in event_body
    assert '\\"activation_id\\":%s' in event_body
    # The echo of the agent's own frame is remembered before the event goes out.
    assert event_body.index("remember(routes, type, activation->address);") < event_body.index(
        "emit(routes, type, data);"
    )
    assert "c300x_local_action_event_remember(routes->local_events, type, address," in remember_body
    assert "&runtime->local_action_events, emit_activation_event, runtime" in wiring_body
    assert "dispatch_event(runtime->config, runtime, type, data, 0);" in emit_body


def test_udp_event_socket_never_blocks_the_loop() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    create_body = _function_body(text, "create_udp_event_socket")
    assert create_body.index("set_fd_nonblocking(fd);") < create_body.index("bind(")
