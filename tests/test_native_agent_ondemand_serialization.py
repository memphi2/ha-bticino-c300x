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
    # Each reason names the step that failed: REGISTER first, then INVITE.
    register_io = setup_body.index('"register_io"')
    register_status = setup_body.index('"register_%d"')
    invite_built = setup_body.index('"INVITE sip:')
    invite_io = setup_body.index('"invite_io"')
    assert register_io < register_status < invite_built < invite_io
    assert '"ack_io"' not in setup_body
    assert '"invite_%d"' not in setup_body
    assert '"answer_%d"' in setup_body
    assert '"answer_timeout"' in setup_body


def test_home_call_receiver_report_takes_the_bridge_mutex() -> None:
    """The talkback proxy uses the same SRTP session under the mutex."""

    body = _function_body(MEDIA_BRIDGE, "static void *home_call_thread_func(")
    report = body.index("send_srtcp_receiver_report(audio_rtcp_fd")
    guard = body.rindex("bridge->home_call_srtp_state == &srtp", 0, report)
    lock = body.rindex("pthread_mutex_lock(&bridge->mutex);", 0, report)
    unlock = body.index("pthread_mutex_unlock(&bridge->mutex);", report)
    assert lock < guard < report < unlock
    assert body.count("pthread_mutex_unlock(&bridge->mutex);", lock, report) == 0
