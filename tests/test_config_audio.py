from __future__ import annotations

import math

import pytest
import voluptuous as vol

from custom_components.bticino_c300x.config_audio import (
    audio_fine_gain_db,
    audio_fine_gain_db_or_default,
    door_audio_level_db,
    door_audio_level_db_or_default,
)


@pytest.mark.parametrize("value", [0, 3, "6", 9.0, "12"])
def test_door_level_accepts_the_five_steps(value: object) -> None:
    assert door_audio_level_db(value) == int(float(value))  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [None, "loud", object(), True, -3, 1, 4.5, 15, math.nan, math.inf])
def test_door_level_rejects_anything_else(value: object) -> None:
    with pytest.raises(vol.Invalid):
        door_audio_level_db(value)


def test_fine_adjustment_accepts_whole_db_in_range() -> None:
    assert audio_fine_gain_db(-10) == -10
    assert audio_fine_gain_db("10") == 10
    assert audio_fine_gain_db(3.0) == 3


@pytest.mark.parametrize("value", [None, "x", False, -11, 11, 0.5, math.nan])
def test_fine_adjustment_rejects_anything_else(value: object) -> None:
    with pytest.raises(vol.Invalid):
        audio_fine_gain_db(value)


def test_or_default_keeps_a_valid_value() -> None:
    assert door_audio_level_db_or_default("9", 6) == 9
    assert door_audio_level_db_or_default(7, 6) == 6
    assert audio_fine_gain_db_or_default("-4", 0) == -4
    assert audio_fine_gain_db_or_default(99, 0) == 0
