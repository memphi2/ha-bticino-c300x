from __future__ import annotations

from custom_components.bticino_c300x.data import C300XConnectionState


def test_connection_state_keeps_last_error_and_next_reconnect_delay() -> None:
    state = C300XConnectionState()

    state.mark_reconnecting(
        "TimeoutError",
        30,
        "TimeoutError: device-agent request timed out",
    )

    assert state.available is True
    assert state.connection_state == "reconnecting"
    assert state.last_reconnect_reason == "TimeoutError"
    assert state.last_connection_error == "TimeoutError: device-agent request timed out"
    assert state.next_reconnect_delay_seconds == 30


def test_connection_state_preserves_last_error_after_reconnect() -> None:
    state = C300XConnectionState()
    state.mark_reconnecting("ClientConnectorError", 30, "ClientConnectorError")

    state.mark_connected()

    assert state.available is True
    assert state.connection_state == "connected"
    assert state.reconnect_count == 1
    assert state.last_connection_error == "ClientConnectorError"
    assert state.next_reconnect_delay_seconds is None


def test_connection_state_marks_unavailable_after_grace_without_losing_error() -> None:
    state = C300XConnectionState()
    state.mark_reconnecting("ClientConnectorError", 30, "ClientConnectorError")

    state.mark_unavailable()

    assert state.available is False
    assert state.connection_state == "disconnected"
    assert state.last_connection_error == "ClientConnectorError"


def test_connection_state_keeps_disconnected_label_during_later_failed_retries() -> None:
    state = C300XConnectionState()
    state.mark_reconnecting("ClientConnectorError", 30, "ClientConnectorError")
    state.mark_unavailable()

    state.mark_reconnecting("TimeoutError", 60, "TimeoutError")

    assert state.available is False
    assert state.connection_state == "disconnected"
    assert state.next_reconnect_delay_seconds == 60
