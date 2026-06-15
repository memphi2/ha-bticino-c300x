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
