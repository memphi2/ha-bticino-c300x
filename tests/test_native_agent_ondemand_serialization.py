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


def test_a_real_teardown_records_a_settle_timestamp() -> None:
    """A session that signalled the device to stop must arm the settle window."""

    stop_body = _function_body(MEDIA_BRIDGE, "static void stop_media_session(")
    assert "ondemand_teardown_done_ms = c300x_monotonic_ms()" in stop_body
    # Only when a real session actually ran, not on a no-op stop.
    assert "if (send_media_stop) {" in stop_body


def test_start_waits_out_the_settle_window() -> None:
    """A new on-demand start must hold off until the previous teardown settled,
    and must drop out of the wait on stop, the explicit-stop guard, or another
    start winning the race (issue #55)."""

    start_body = _function_body(MEDIA_BRIDGE, "static bool start_media_session(")
    assert "ONDEMAND_TEARDOWN_SETTLE_MS" in start_body
    assert "ondemand_teardown_done_ms != 0" in start_body
    assert "c300x_monotonic_ms() < settle_deadline" in start_body
    for breakout in (
        "!bridge->stop_in_progress",
        "c300x_media_session_guard_blocks_start",
        "!bridge->media_active",
        "!bridge->media_starting",
    ):
        assert breakout in start_body, breakout


def test_settle_window_is_a_named_constant() -> None:
    assert "#define ONDEMAND_TEARDOWN_SETTLE_MS" in MEDIA_BRIDGE


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
