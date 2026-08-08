"""Tests for the WebRTC ICE candidate filter."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from custom_components.bticino_c300x.camera_media.webrtc_ice_filter import (
    CATEGORY_IPV4,
    CATEGORY_IPV4_LINK_LOCAL,
    CATEGORY_IPV6_GLOBAL,
    CATEGORY_IPV6_LINK_LOCAL,
    CATEGORY_IPV6_ULA,
    CATEGORY_MDNS,
    CATEGORY_UNKNOWN,
    candidate_object_should_pass,
    classify_ice_address,
    extract_candidate_sdp,
    filter_sdp_candidate_lines,
    filter_webrtc_message,
    ice_candidate_should_pass,
    parse_ice_candidate,
)

_HOST_V4 = "candidate:1 1 udp 2130706431 192.0.2.5 54321 typ host"
_HOST_V4_LINK_LOCAL = "candidate:2 1 udp 2130706431 169.254.1.1 5000 typ host"
_HOST_ULA = "candidate:3 1 udp 2130706431 fddd:1234::5 5000 typ host"
_HOST_V6_GLOBAL = "candidate:4 1 udp 2130706431 2003:abcd::1 5000 typ host"
_HOST_V6_LINK_LOCAL = "candidate:5 1 udp 2130706431 fe80::1%eth0 5000 typ host"
_RELAY_V6_GLOBAL = (
    "candidate:6 1 udp 900 2003:abcd::1 5000 typ relay raddr 1.2.3.4 rport 9"
)
_HOST_MDNS = "candidate:7 1 udp 2130706431 abcd-ef.local 5000 typ host"
_ANSWER_SDP = (
    "v=0\r\n"
    "a=candidate:1 1 udp 1 192.0.2.5 9 typ host\r\n"
    "a=candidate:2 1 udp 1 2003:abcd::1 9 typ host\r\n"
    "a=candidate:3 1 udp 9 2003:abcd::1 9 typ relay raddr 1.2.3.4 rport 9\r\n"
)


@dataclass(frozen=True)
class _AnswerMessage:
    answer: str

    def as_dict(self) -> dict[str, str]:
        return {"type": "answer", "answer": self.answer}


def test_classify_covers_every_scope() -> None:
    assert classify_ice_address("192.0.2.5") == CATEGORY_IPV4
    assert classify_ice_address("169.254.1.1") == CATEGORY_IPV4_LINK_LOCAL
    assert classify_ice_address("fddd:1234::5") == CATEGORY_IPV6_ULA
    assert classify_ice_address("2003:abcd::1") == CATEGORY_IPV6_GLOBAL
    assert classify_ice_address("fe80::1%eth0") == CATEGORY_IPV6_LINK_LOCAL
    assert classify_ice_address("abcd.local") == CATEGORY_MDNS
    assert classify_ice_address("::ffff:192.0.2.9") == CATEGORY_IPV4
    assert classify_ice_address("not-an-address") == CATEGORY_UNKNOWN
    assert classify_ice_address("") == CATEGORY_UNKNOWN


def test_parse_rejects_non_candidate_lines() -> None:
    assert parse_ice_candidate("") is None
    assert parse_ice_candidate("v=0") is None
    assert parse_ice_candidate("candidate:1 1 udp") is None
    assert parse_ice_candidate("a=candidate:1 1 udp 1 198.51.100.1 9 typ srflx") == (
        "198.51.100.1",
        "srflx",
    )


def test_all_policy_passes_everything() -> None:
    for line in (_HOST_V4, _HOST_V6_GLOBAL, _HOST_V6_LINK_LOCAL, _HOST_V4_LINK_LOCAL):
        assert ice_candidate_should_pass(line, "all") is True
        assert ice_candidate_should_pass(line, None) is True
        assert ice_candidate_should_pass(line, "bogus_policy") is True


def test_prefer_ipv4_ula_keeps_v4_and_ula_drops_the_rest() -> None:
    policy = "prefer_ipv4_ula"
    assert ice_candidate_should_pass(_HOST_V4, policy) is True
    assert ice_candidate_should_pass(_HOST_ULA, policy) is True
    assert ice_candidate_should_pass(_HOST_V6_GLOBAL, policy) is False
    assert ice_candidate_should_pass(_HOST_V6_LINK_LOCAL, policy) is False
    assert ice_candidate_should_pass(_HOST_V4_LINK_LOCAL, policy) is False
    # TURN relay and mDNS/unparsed are always kept so cloud never breaks.
    assert ice_candidate_should_pass(_RELAY_V6_GLOBAL, policy) is True
    assert ice_candidate_should_pass(_HOST_MDNS, policy) is True
    assert ice_candidate_should_pass("", policy) is True


def test_drop_link_local_only_touches_link_local() -> None:
    policy = "drop_link_local"
    assert ice_candidate_should_pass(_HOST_V6_GLOBAL, policy) is True
    assert ice_candidate_should_pass(_HOST_ULA, policy) is True
    assert ice_candidate_should_pass(_HOST_V6_LINK_LOCAL, policy) is False
    assert ice_candidate_should_pass(_HOST_V4_LINK_LOCAL, policy) is False


def test_ipv4_only_drops_ula_too() -> None:
    policy = "ipv4_only"
    assert ice_candidate_should_pass(_HOST_V4, policy) is True
    assert ice_candidate_should_pass(_HOST_ULA, policy) is False
    assert ice_candidate_should_pass(_HOST_V6_GLOBAL, policy) is False


def test_extract_candidate_sdp_unwraps_objects_and_mappings() -> None:
    assert extract_candidate_sdp(_HOST_V4) == _HOST_V4
    assert extract_candidate_sdp({"candidate": _HOST_V4}) == _HOST_V4
    rtc = SimpleNamespace(candidate=_HOST_V4)
    message = SimpleNamespace(candidate=rtc)
    assert extract_candidate_sdp(message) == _HOST_V4
    assert extract_candidate_sdp(SimpleNamespace(answer="v=0")) is None
    assert extract_candidate_sdp(None) is None


def test_candidate_object_should_pass_fails_open_for_non_candidates() -> None:
    policy = "prefer_ipv4_ula"
    assert candidate_object_should_pass(SimpleNamespace(answer="v=0"), policy) is True
    assert candidate_object_should_pass({"type": "answer"}, policy) is True
    v6 = SimpleNamespace(candidate=SimpleNamespace(candidate=_HOST_V6_GLOBAL))
    v4 = SimpleNamespace(candidate=SimpleNamespace(candidate=_HOST_V4))
    assert candidate_object_should_pass(v6, policy) is False
    assert candidate_object_should_pass(v4, policy) is True
    # The "all" policy short-circuits before any parsing.
    assert candidate_object_should_pass(v6, "all") is True


def test_filter_sdp_candidate_lines_filters_answer_candidates() -> None:
    filtered = filter_sdp_candidate_lines(_ANSWER_SDP, "prefer_ipv4_ula")

    assert "192.0.2.5" in filtered
    assert "typ relay" in filtered
    assert "2003:abcd::1 9 typ host" not in filtered


def test_filter_webrtc_message_rewrites_answer_sdp_candidates() -> None:
    message = {"type": "answer", "answer": _ANSWER_SDP}

    filtered = filter_webrtc_message(message, "prefer_ipv4_ula")

    assert filtered is not message
    assert filtered["type"] == "answer"
    assert "192.0.2.5" in filtered["answer"]
    assert "2003:abcd::1 9 typ host" not in filtered["answer"]


def test_filter_webrtc_message_preserves_answer_message_type() -> None:
    message = _AnswerMessage(_ANSWER_SDP)

    filtered = filter_webrtc_message(message, "prefer_ipv4_ula")

    assert isinstance(filtered, _AnswerMessage)
    assert "192.0.2.5" in filtered.answer
    assert "2003:abcd::1 9 typ host" not in filtered.answer
