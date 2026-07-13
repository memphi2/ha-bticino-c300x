from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def _script_module() -> ModuleType:
    path = ROOT / "scripts" / "verify_media_reference_flow.py"
    spec = importlib.util.spec_from_file_location("verify_media_reference_flow", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _ring_flow(*, view_delay: float = 0.12) -> str:
    view_second = 3 + view_delay
    closed_second = view_second + 6
    return (
        "2026-06-12 18:21:58.000000 IP 192.0.2.10.1 > 198.51.100.20.2: UDP, length 180\n"
        '{"type":"doorbell.pressed","data":{"doorbell":"ringing","available":true,'
        '"window_available":true,"stream_path":"/doorbell-video"}}\n'
        "2026-06-12 18:22:00.500000 IP 192.0.2.10.1 > 198.51.100.20.2: UDP, length 1200\n"
        "media\n"
        "2026-06-12 18:22:03.000000 IP 192.0.2.10.1 > 198.51.100.20.2: HTTP, length 220\n"
        "POST /api/v1/calls/doorbell/actions/answer HTTP/1.1\r\n"
        f"2026-06-12 18:22:{view_second:09.6f} IP 192.0.2.10.1 > 198.51.100.20.2: UDP, length 180\n"
        '{"type":"doorbell.view_requested","data":{"doorbell":"view_requested","available":true,'
        '"window_available":true,"stream_path":"/doorbell-video"}}\n'
        "2026-06-12 18:22:03.500000 IP 192.0.2.10.1 > 198.51.100.20.2: UDP, length 120\n"
        "control\n"
        f"2026-06-12 18:22:{closed_second:09.6f} IP 192.0.2.10.1 > 198.51.100.20.2: UDP, length 120\n"
        '{"type":"doorbell.media.closed"}\n'
    )


def _ring_dual_rtsp_flow(*, teardown_before_full_play: bool = False) -> str:
    teardown_second = "03.120000" if teardown_before_full_play else "03.420000"
    return (
        "2026-06-12 18:21:58.000000 IP 192.0.2.10.1 > 198.51.100.20.2: UDP, length 180\n"
        '{"type":"doorbell.pressed","data":{"doorbell":"ringing","available":true,'
        '"window_available":true,"stream_path":"/doorbell-video"}}\n'
        "2026-06-12 18:21:58.120000 IP 192.0.2.10.1 > 198.51.100.20.2: RTSP, length 180\n"
        "PLAY rtsp://192.0.2.60:6554/doorbell-video/ RTSP/1.0\r\n"
        "2026-06-12 18:22:00.500000 IP 192.0.2.10.1 > 198.51.100.20.2: UDP, length 1200\n"
        "media\n"
        "2026-06-12 18:22:03.080000 IP 192.0.2.10.1 > 198.51.100.20.2: HTTP, length 220\n"
        "POST /api/v1/calls/doorbell/actions/answer HTTP/1.1\r\n"
        "2026-06-12 18:22:03.100000 IP 192.0.2.10.1 > 198.51.100.20.2: UDP, length 180\n"
        '{"type":"doorbell.view_requested","data":{"doorbell":"view_requested","available":true,'
        '"window_available":true,"stream_path":"/doorbell-video"}}\n'
        f"2026-06-12 18:22:{teardown_second} IP 192.0.2.10.1 > 198.51.100.20.2: RTSP, length 180\n"
        "TEARDOWN rtsp://192.0.2.60:6554/doorbell-video/ RTSP/1.0\r\n"
        "2026-06-12 18:22:03.300000 IP 192.0.2.10.1 > 198.51.100.20.2: RTSP, length 180\n"
        "PLAY rtsp://192.0.2.60:6554/doorbell/ RTSP/1.0\r\n"
        "2026-06-12 18:22:03.500000 IP 192.0.2.10.1 > 198.51.100.20.2: UDP, length 120\n"
        "control\n"
        "2026-06-12 18:22:09.000000 IP 192.0.2.10.1 > 198.51.100.20.2: UDP, length 120\n"
        '{"type":"doorbell.media.closed"}\n'
    )


def _on_demand_flow(
    *,
    play_response: str = "200 OK",
    bt_av_reply: str = "*#*1##",
    media_closed_before_play_response: bool = False,
    rtp_before_play_response: bool = False,
) -> str:
    media_closed = (
        "2026-06-12 18:00:01.500000 IP 192.0.2.60.1 > 198.51.100.20.2: HTTP, length 200\n"
        '{"type":"doorbell.media.closed"}\n'
        if media_closed_before_play_response
        else ""
    )
    early_rtp = (
        "2026-06-12 18:00:01.520000 IP 192.0.2.60.6554 > 198.51.100.20.2: RTSP, length 176\n"
        "$\x00\x00\xa0rtp-before-play-response\n"
        if rtp_before_play_response
        else ""
    )
    return (
        "2026-06-12 18:00:00.000000 IP 192.0.2.10.1 > 198.51.100.20.2: SIP, length 200\n"
        "INVITE sip:c300x@example.invalid SIP/2.0\r\n"
        "m=audio 1234 RTP/SAVP 96 97 98 0 8 101 99 100\r\n"
        "a=rtpmap:96 opus/48000/2\r\n"
        "a=rtpmap:97 speex/16000\r\n"
        "a=rtpmap:98 speex/8000\r\n"
        "a=rtpmap:101 telephone-event/48000\r\n"
        "a=rtpmap:99 telephone-event/16000\r\n"
        "a=rtpmap:100 telephone-event/8000\r\n"
        "a=crypto:1 AEAD_AES_128_GCM inline:secret\r\n"
        "a=crypto:2 AES_CM_128_HMAC_SHA1_80 inline:secret\r\n"
        "a=crypto:3 AEAD_AES_256_GCM inline:secret\r\n"
        "a=crypto:4 AES_256_CM_HMAC_SHA1_80 inline:secret\r\n"
        "m=video 5678 RTP/SAVP 96 97 98 99\r\n"
        "a=rtpmap:96 AV1/90000\r\n"
        "a=rtpmap:97 VP8/90000\r\n"
        "a=rtpmap:98 H264/90000\r\n"
        "a=rtpmap:99 H265/90000\r\n"
        "a=crypto:1 AEAD_AES_128_GCM inline:secret\r\n"
        "a=crypto:2 AES_CM_128_HMAC_SHA1_80 inline:secret\r\n"
        "a=crypto:3 AEAD_AES_256_GCM inline:secret\r\n"
        "a=crypto:4 AES_256_CM_HMAC_SHA1_80 inline:secret\r\n"
        "2026-06-12 18:00:01.000000 IP 198.51.100.20.2 > 192.0.2.10.1: SIP, length 200\n"
        "SIP/2.0 200 Ok\r\n"
        "m=audio 1234 RTP/SAVP 98 100\r\n"
        "a=rtpmap:98 speex/8000\r\n"
        "a=rtpmap:100 telephone-event/8000\r\n"
        "a=crypto:1 AES_CM_128_HMAC_SHA1_80 inline:secret\r\n"
        "m=video 5678 RTP/SAVP 98\r\n"
        "a=rtpmap:98 H264/90000\r\n"
        "a=crypto:1 AES_CM_128_HMAC_SHA1_80 inline:secret\r\n"
        "2026-06-12 18:00:01.100000 IP 192.0.2.20.40000 > 192.0.2.60.30007: TCP, length 27\n"
        "*7*300#127#0#0#1#10002#0*##\n"
        "2026-06-12 18:00:01.120000 IP 192.0.2.60.30007 > 192.0.2.20.40000: TCP, length 6\n"
        f"{bt_av_reply}\n"
        "2026-06-12 18:00:01.300000 IP 198.51.100.20.2 > 192.0.2.60.6554: RTSP, length 80\n"
        "PLAY rtsp://192.0.2.60:6554/doorbell/ RTSP/1.0\r\n"
        + media_closed
        + early_rtp
        + "2026-06-12 18:00:01.600000 IP 192.0.2.60.6554 > 198.51.100.20.2: RTSP, length 80\n"
        f"RTSP/1.0 {play_response}\r\n"
    )


def test_code_reference_checks_cover_all_media_modes() -> None:
    module = _script_module()

    failed = [check for check in module.collect_code_checks("all") if not check.ok]

    assert failed == []


def test_fixture_gate_checks_cover_all_media_modes() -> None:
    module = _script_module()

    failed = [
        check
        for check in module.collect_fixture_gate_checks(mode="all")
        if not check.ok
    ]

    assert failed == []


def test_fixture_rtsp_contract_rejects_missing_teardown() -> None:
    module = _script_module()
    fixture = copy.deepcopy(module._fixture("on_demand"))
    fixture["rtsp_contract"]["methods"] = ["DESCRIBE", "SETUP", "PLAY"]

    failed = [
        check.name
        for check in module._collect_rtsp_contract_checks("on_demand", fixture)
        if not check.ok
    ]

    assert failed == ["fixture.on_demand.rtsp.methods"]


def test_ring_reference_pcap_comparison_accepts_matching_flow() -> None:
    module = _script_module()
    reference = module.parse_tcpdump_ascii(_ring_flow())
    candidate = module.parse_tcpdump_ascii(_ring_flow())

    failed = [
        check
        for check in module.collect_reference_pcap_checks(
            mode="ring_call",
            reference_packets=reference,
            candidate_packets=candidate,
        )
        if not check.ok
    ]

    assert failed == []


def test_ring_reference_pcap_comparison_rejects_timing_drift() -> None:
    module = _script_module()
    reference = module.parse_tcpdump_ascii(_ring_flow())
    candidate = module.parse_tcpdump_ascii(_ring_flow(view_delay=3.0))

    failed = [
        check.name
        for check in module.collect_reference_pcap_checks(
            mode="ring_call",
            reference_packets=reference,
            candidate_packets=candidate,
        )
        if not check.ok
    ]

    assert "pcap_compare.ring_call.timing.view_after_answer" in failed


def test_ring_reference_pcap_comparison_covers_dual_rtsp_transition() -> None:
    module = _script_module()
    reference = module.parse_tcpdump_ascii(_ring_dual_rtsp_flow())
    candidate = module.parse_tcpdump_ascii(
        _ring_dual_rtsp_flow(teardown_before_full_play=True)
    )

    failed = [
        check.name
        for check in module.collect_reference_pcap_checks(
            mode="ring_call",
            reference_packets=reference,
            candidate_packets=candidate,
        )
        if not check.ok
    ]

    assert "pcap_compare.ring_call.timing.preview_teardown_after_full_play" in failed


def test_single_on_demand_pcap_check_accepts_media_without_full_stop_sequence() -> None:
    module = _script_module()
    text = _on_demand_flow()

    failed = [
        check
        for check in module.collect_pcap_checks(
            module.parse_tcpdump_ascii(text),
            mode="on_demand",
        )
        if not check.ok
    ]

    assert failed == []


def test_on_demand_pcap_check_rejects_play_500_and_bt_av_nack() -> None:
    module = _script_module()
    text = _on_demand_flow(
        play_response="500 Error",
        bt_av_reply="*#*0##",
        media_closed_before_play_response=True,
    )

    failed = [
        check.name
        for check in module.collect_pcap_checks(
            module.parse_tcpdump_ascii(text),
            mode="on_demand",
        )
        if not check.ok
    ]

    assert "pcap.on_demand.rtsp_play_response_200" in failed
    assert "pcap.on_demand.no_media_closed_before_play_200" in failed
    assert "pcap.on_demand.bt_av_custom_start_ack" in failed


def test_on_demand_pcap_check_rejects_rtp_before_play_200() -> None:
    module = _script_module()
    text = _on_demand_flow(rtp_before_play_response=True)

    failed = [
        check.name
        for check in module.collect_pcap_checks(
            module.parse_tcpdump_ascii(text),
            mode="on_demand",
        )
        if not check.ok
    ]

    assert "pcap.on_demand.no_rtp_before_play_200" in failed


def test_on_demand_fingerprint_uses_200_ok_answer_after_proxy_invite() -> None:
    module = _script_module()
    text = (
        "2026-06-12 18:00:00.000000 IP 192.0.2.10.1 > 198.51.100.20.2: SIP, length 200\n"
        "INVITE sip:c300x@example.invalid SIP/2.0\r\n"
        "m=audio 1234 RTP/SAVP 96 97 98 0 8 101 99 100\r\n"
        "a=rtpmap:96 opus/48000/2\r\n"
        "a=rtpmap:97 speex/16000\r\n"
        "a=rtpmap:98 speex/8000\r\n"
        "a=crypto:1 AEAD_AES_128_GCM inline:secret\r\n"
        "a=crypto:2 AES_CM_128_HMAC_SHA1_80 inline:secret\r\n"
        "m=video 5678 RTP/SAVP 96 97 98 99\r\n"
        "a=rtpmap:98 H264/90000\r\n"
        "a=crypto:2 AES_CM_128_HMAC_SHA1_80 inline:secret\r\n"
        "2026-06-12 18:00:00.100000 IP 198.51.100.20.2 > 192.0.2.10.1: SIP, length 200\n"
        "INVITE sip:c300x@127.0.0.1 SIP/2.0\r\n"
        "m=audio 4321 RTP/SAVP 96 97 98 0 8 101 99 100\r\n"
        "a=rtpmap:96 opus/48000/2\r\n"
        "a=rtpmap:98 speex/8000\r\n"
        "a=crypto:2 AES_CM_128_HMAC_SHA1_80 inline:secret\r\n"
        "m=video 8765 RTP/SAVP 96 97 98 99\r\n"
        "a=rtpmap:98 H264/90000\r\n"
        "a=crypto:2 AES_CM_128_HMAC_SHA1_80 inline:secret\r\n"
        "2026-06-12 18:00:01.000000 IP 198.51.100.20.2 > 192.0.2.10.1: SIP, length 200\n"
        "SIP/2.0 200 Ok\r\n"
        "m=audio 7078 RTP/SAVP 98 100\r\n"
        "a=rtpmap:98 speex/8000\r\n"
        "a=rtpmap:100 telephone-event/8000\r\n"
        "a=crypto:2 AES_CM_128_HMAC_SHA1_80 inline:secret\r\n"
        "m=video 9078 RTP/SAVP 98\r\n"
        "a=rtpmap:98 H264/90000\r\n"
        "a=crypto:2 AES_CM_128_HMAC_SHA1_80 inline:secret\r\n"
    )

    fingerprint = module.fingerprint_from_text(text)

    assert fingerprint["answer"]["audio"]["payloads"] == ["98", "100"]
    assert fingerprint["answer"]["audio"]["codecs"] == [
        "speex/8000",
        "telephone-event/8000",
    ]
    assert fingerprint["answer"]["video"]["payloads"] == ["98"]
