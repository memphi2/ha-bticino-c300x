from __future__ import annotations

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
    return (
        "2026-06-12 18:21:58.000000 IP 192.0.2.10.1 > 198.51.100.20.2: UDP, length 180\n"
        '{"type":"doorbell.pressed","data":{"doorbell":"ringing","available":true,'
        '"window_available":true,"stream_path":"/doorbell-video"}}\n'
        "2026-06-12 18:22:00.500000 IP 192.0.2.10.1 > 198.51.100.20.2: UDP, length 1200\n"
        "media\n"
        "2026-06-12 18:22:03.000000 IP 192.0.2.10.1 > 198.51.100.20.2: UDP, length 120\n"
        '{"type":"doorbell.media.closed"}\n'
        f"2026-06-12 18:22:{view_second:09.6f} IP 192.0.2.10.1 > 198.51.100.20.2: UDP, length 180\n"
        '{"type":"doorbell.view_requested","data":{"doorbell":"view_requested","available":true,'
        '"window_available":true,"stream_path":"/doorbell-video"}}\n'
        "2026-06-12 18:22:03.500000 IP 192.0.2.10.1 > 198.51.100.20.2: UDP, length 120\n"
        "control\n"
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
        "2026-06-12 18:22:03.000000 IP 192.0.2.10.1 > 198.51.100.20.2: UDP, length 120\n"
        '{"type":"doorbell.media.closed"}\n'
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

    assert "pcap_compare.ring_call.timing.view_after_close" in failed


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
    text = (
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
    )

    failed = [
        check
        for check in module.collect_pcap_checks(
            module.parse_tcpdump_ascii(text),
            mode="on_demand",
        )
        if not check.ok
    ]

    assert failed == []
