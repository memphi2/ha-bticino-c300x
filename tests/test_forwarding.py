from __future__ import annotations

from custom_components.bticino_c300x.forwarding import (
    coerce_forwarding_mode_state,
    forwarding_mode_code_from_value,
    forwarding_state_from_value,
)


def test_forwarding_state_from_value_supports_bool_int_text() -> None:
    assert forwarding_state_from_value(True) == "enabled"
    assert forwarding_state_from_value(False) == "blocked"
    assert forwarding_state_from_value(1) == "homeassistant"
    assert forwarding_state_from_value("2") == "blocked"
    assert forwarding_state_from_value("enabled") == "enabled"
    assert forwarding_state_from_value("") is None
    assert forwarding_state_from_value("99") is None
    assert forwarding_state_from_value("invalid") is None


def test_forwarding_mode_code_from_value_supports_bool_int_text() -> None:
    assert forwarding_mode_code_from_value(True) == 0
    assert forwarding_mode_code_from_value(False) == 2
    assert forwarding_mode_code_from_value(1) == 1
    assert forwarding_mode_code_from_value("blocked") == 2
    assert forwarding_mode_code_from_value("0") == 0
    assert forwarding_mode_code_from_value("") is None
    assert forwarding_mode_code_from_value("invalid") is None


def test_coerce_forwarding_mode_state_supports_partial_payloads() -> None:
    assert coerce_forwarding_mode_state(0, "blocked") == {
        "mode": 0,
        "state": "blocked",
    }
    assert coerce_forwarding_mode_state(None, "blocked") == {
        "mode": 2,
        "state": "blocked",
    }
    assert coerce_forwarding_mode_state(1, None) == {
        "mode": 1,
        "state": "homeassistant",
    }
    assert coerce_forwarding_mode_state(99, None) == {
        "mode": 99,
        "state": "unknown",
    }
    assert coerce_forwarding_mode_state("homeassistant", None) == {
        "mode": 1,
        "state": "homeassistant",
    }
    assert coerce_forwarding_mode_state(None, None) == {
        "mode": None,
        "state": "unknown",
    }


def test_malformed_agent_values_are_no_reading_instead_of_an_exception() -> None:
    """A faulty agent must not get a non-client exception through an entity read."""

    from custom_components.bticino_c300x._api_core import _decode_text
    from custom_components.bticino_c300x.value_parsing import optional_int

    # JSON 1e999 is parsed as float infinity.
    assert optional_int(float("inf")) is None
    assert optional_int(float("inf"), 0) == 0
    # str.isdigit() accepts characters int() rejects.
    assert forwarding_state_from_value("²") is None
    assert forwarding_mode_code_from_value("²") is None
    # A charset Python does not know.
    assert _decode_text(b'{"ok": true}', "bogus-charset") == '{"ok": true}'
    assert _decode_text("ä".encode("latin-1"), "latin-1") == "ä"
