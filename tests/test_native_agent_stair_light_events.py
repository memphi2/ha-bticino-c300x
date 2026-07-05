from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _native_http_source() -> str:
    return (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")


def test_stair_light_endpoint_does_not_emit_synthetic_event() -> None:
    text = _native_http_source()
    body = text.split("static int activate_stair_light(", maxsplit=1)[1].split(
        "static void handle_stair_light(",
        maxsplit=1,
    )[0]

    assert 'snprintf(command, sizeof(command), "*8*21*%s##", address);' in body
    assert "c300x_openwebnet_send(config, command, reply, reply_len, error, error_len)" in body
    assert '"stair_light.activated"' not in body
    assert "dispatch_event(" not in body


def test_stair_light_event_source_is_openwebnet_echo() -> None:
    text = _native_http_source()
    body = text.split("static int map_openwebnet_event(", maxsplit=1)[1].split(
        "if (strncmp(msg, \"*8*1#5#4#\"",
        maxsplit=1,
    )[0]

    assert 'parse_openwebnet_address_event(msg, "*8*21*", address, sizeof(address))' in body
    assert 'c300x_copy_string(type, type_len, "stair_light.activated");' in body
    assert (
        'return c300x_appendf(data, data_len, &used, "{\\"raw\\":%s,\\"address\\":%s}", '
        "raw_json, address_json);"
    ) in body
