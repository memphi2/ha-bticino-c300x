from __future__ import annotations

import pytest

from custom_components.bticino_c300x.media_status import (
    home_call_payload,
    home_call_status_has_media,
)


def test_home_call_payload_accepts_all_supported_wrapper_shapes() -> None:
    assert home_call_payload({"home_call": {"active": True}}) == {"active": True}
    assert home_call_payload({"data": {"home_call": {"active": False}}}) == {
        "active": False
    }
    assert home_call_payload({"data": {"active": True}}) == {"active": True}
    assert home_call_payload({"data": "invalid"}) == {}


@pytest.mark.parametrize("field", ["running", "active", "answered", "rtp_proxy", "target_audio_port"])
def test_home_call_status_recognizes_each_media_indicator(field) -> None:
    assert home_call_status_has_media({field: 1})
    assert not home_call_status_has_media({field: 0})


def test_home_call_status_without_media_indicators_is_idle() -> None:
    assert not home_call_status_has_media({})
    assert not home_call_status_has_media({"available": True})
