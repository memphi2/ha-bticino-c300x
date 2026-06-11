from __future__ import annotations

from custom_components.bticino_c300x.ring_decision import _phrase_match


def test_phrase_match_prefers_explicit_expected_phrase() -> None:
    assert (
        _phrase_match(
            {"transcript": "open the door", "phrase_match": True},
            expected_phrase="wrong phrase",
        )
        is False
    )


def test_phrase_match_uses_payload_only_without_expected_phrase() -> None:
    assert _phrase_match({"transcript": "wrong", "phrase_match": True}, expected_phrase=None)

