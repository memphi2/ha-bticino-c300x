from __future__ import annotations

from custom_components.bticino_c300x.media_status import (
    home_call_payload,
)


def test_home_call_payload_accepts_all_supported_wrapper_shapes() -> None:
    assert home_call_payload({"home_call": {"active": True}}) == {"active": True}
    assert home_call_payload({"data": {"home_call": {"active": False}}}) == {
        "active": False
    }
    assert home_call_payload({"data": {"active": True}}) == {"active": True}
    assert home_call_payload({"data": "invalid"}) == {}
