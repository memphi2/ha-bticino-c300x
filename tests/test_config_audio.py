from __future__ import annotations

import pytest
import voluptuous as vol

from custom_components.bticino_c300x.config_audio import (
    AUDIO_GAIN_DB_MAX,
    AUDIO_GAIN_DB_MIN,
    audio_gain_db,
    audio_gain_db_or_default,
)


def test_audio_gain_db_accepts_bounds_and_numeric_strings() -> None:
    assert audio_gain_db(AUDIO_GAIN_DB_MIN) == AUDIO_GAIN_DB_MIN
    assert audio_gain_db(AUDIO_GAIN_DB_MAX) == AUDIO_GAIN_DB_MAX
    assert audio_gain_db("3.5") == 3.5


@pytest.mark.parametrize("value", [None, "loud", object()])
def test_audio_gain_db_rejects_non_numeric_values(value: object) -> None:
    with pytest.raises(vol.Invalid):
        audio_gain_db(value)


@pytest.mark.parametrize(
    "value",
    [AUDIO_GAIN_DB_MIN - 0.1, AUDIO_GAIN_DB_MAX + 0.1],
)
def test_audio_gain_db_rejects_out_of_range_values(value: float) -> None:
    with pytest.raises(vol.Invalid):
        audio_gain_db(value)


def test_audio_gain_db_or_default_keeps_valid_value_or_default() -> None:
    assert audio_gain_db_or_default("6", 0.0) == 6.0
    assert audio_gain_db_or_default("too-high", 1.5) == 1.5
    assert audio_gain_db_or_default(99, -2.0) == -2.0
