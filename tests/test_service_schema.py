from __future__ import annotations

import pytest
import voluptuous as vol

from custom_components.bticino_c300x.service_schema import (
    activation_id,
    boolean_service_value,
    capture_duration_seconds,
    home_call_duration_seconds,
    lock_id,
    stair_light_address,
    text_memo_text,
    wyoming_port,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        (" yes ", True),
        ("enabled", True),
        ("0", False),
        ("disable", False),
    ],
)
def test_boolean_service_value_accepts_documented_values(
    value: object,
    expected: bool,
) -> None:
    assert boolean_service_value(value) is expected


@pytest.mark.parametrize("value", ["maybe", 1, None])
def test_boolean_service_value_rejects_unknown_values(value: object) -> None:
    with pytest.raises(vol.Invalid, match="expected boolean"):
        boolean_service_value(value)


def test_openwebnet_and_activation_id_validators_strip_valid_values() -> None:
    assert stair_light_address(" 12#34 ") == "12#34"
    assert lock_id(" front-lock_1 ") == "front-lock_1"
    assert activation_id(" gate_1 ") == "gate_1"


@pytest.mark.parametrize(
    ("validator", "value", "message"),
    [
        (stair_light_address, "12*34", "invalid staircase light address"),
        (lock_id, "front lock", "invalid lock id"),
        (activation_id, "gate.1", "invalid activation id"),
    ],
)
def test_id_validators_reject_invalid_values(
    validator,
    value: str,
    message: str,
) -> None:
    with pytest.raises(vol.Invalid, match=message):
        validator(value)


def test_duration_and_port_validators_accept_boundaries() -> None:
    assert home_call_duration_seconds("0") == 0
    assert home_call_duration_seconds("3600") == 3600
    assert capture_duration_seconds("1") == 1
    assert capture_duration_seconds("15") == 15
    assert wyoming_port("1") == 1
    assert wyoming_port("65535") == 65535


@pytest.mark.parametrize("value", ["bad", -1, 3601])
def test_home_call_duration_rejects_invalid_values(value: object) -> None:
    with pytest.raises(vol.Invalid, match="invalid duration seconds"):
        home_call_duration_seconds(value)


@pytest.mark.parametrize("value", ["bad", 0, 16])
def test_capture_duration_rejects_invalid_values(value: object) -> None:
    with pytest.raises(vol.Invalid, match="invalid duration seconds"):
        capture_duration_seconds(value)


@pytest.mark.parametrize("value", ["bad", 0, 65536])
def test_wyoming_port_rejects_invalid_values(value: object) -> None:
    with pytest.raises(vol.Invalid, match="invalid Wyoming port"):
        wyoming_port(value)


def test_text_memo_text_normalizes_newlines() -> None:
    assert text_memo_text("Line 1\r\nLine 2\rLine 3") == "Line 1\nLine 2\nLine 3"


@pytest.mark.parametrize("value", [None, "", "   ", "bad\x00text"])
def test_text_memo_text_rejects_invalid_content(value: object) -> None:
    with pytest.raises(vol.Invalid):
        text_memo_text(value)
