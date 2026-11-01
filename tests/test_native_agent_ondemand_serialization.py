from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA_BRIDGE = (ROOT / "native_agent" / "src" / "media_bridge.c").read_text(
    encoding="utf-8"
)


def _function_body(source: str, signature: str) -> str:
    # Skip forward declarations (signature followed by ';') and bind the real
    # definition (signature whose next non-space character after ')' is '{').
    search = 0
    while True:
        start = source.index(signature, search)
        brace = source.index("{", start)
        semicolon = source.find(";", start)
        if semicolon == -1 or brace < semicolon:
            break
        search = start + len(signature)
    depth = 0
    seen = False
    for i in range(start, len(source)):
        if source[i] == "{":
            depth += 1
            seen = True
        elif source[i] == "}":
            depth -= 1
            if seen and depth == 0:
                return source[start : i + 1]
    raise AssertionError(f"could not bound {signature!r}")


def test_teardown_settle_serialization_is_not_reintroduced() -> None:
    """The 1.9.7 teardown settle-wait did not stop the PCMU reboot on hardware
    (issue #55: even an isolated successful session was followed by a reboot)
    while costing up to 8 s of reconnect
    latency. It was removed in 1.9.8; do not bring it back without data."""

    assert "ONDEMAND_TEARDOWN_SETTLE_MS" not in MEDIA_BRIDGE
    assert "ondemand_teardown_done_ms" not in MEDIA_BRIDGE


def test_sip_setup_failure_carries_a_reason() -> None:
    """ondemand_sip_setup_failed must name why: the SIP reject code, an IO
    failure, or a timeout, so the reboot window can be diagnosed."""

    assert 'snprintf(sip_error, sizeof(sip_error), "ondemand_sip_setup_failed:%s"' in (
        MEDIA_BRIDGE
    )
    setup_body = _function_body(MEDIA_BRIDGE, "static bool send_sip_setup(")
    assert '"invite_%d"' in setup_body
    assert '"invite_io"' in setup_body
    assert '"answer_%d"' in setup_body
    assert '"answer_timeout"' in setup_body
