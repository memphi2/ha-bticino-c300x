from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "c300x_pcap_fingerprints"


def _read_media_bridge() -> str:
    return (ROOT / "native_agent" / "src" / "media_bridge.c").read_text(
        encoding="utf-8"
    )


def _read_camera() -> str:
    return (ROOT / "custom_components" / "bticino_c300x" / "camera.py").read_text(
        encoding="utf-8"
    )


def _read_api() -> str:
    return (ROOT / "custom_components" / "bticino_c300x" / "api.py").read_text(
        encoding="utf-8"
    )


def _read_const() -> str:
    return (ROOT / "custom_components" / "bticino_c300x" / "const.py").read_text(
        encoding="utf-8"
    )


def _fingerprint(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _script_module() -> ModuleType:
    path = ROOT / "scripts" / "extract_pcap_fingerprint.py"
    spec = importlib.util.spec_from_file_location("extract_pcap_fingerprint", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _section(text: str, start: str, end: str) -> str:
    start_index = text.index(start)
    return text[start_index : text.index(end, start_index)]


def _assert_media_line(body: str, kind: str, payloads: list[str]) -> None:
    assert f'"m={kind} %d RTP/SAVP {" ".join(payloads)}\\r\\n"' in body


def _assert_codecs(body: str, codecs: list[str]) -> None:
    for codec in codecs:
        assert '"a=rtpmap:' in body
        assert f" {codec}\\r\\n" in body


def _assert_crypto_suites(body: str, suites: list[str]) -> None:
    for index, suite in enumerate(suites, start=1):
        assert f'"a=crypto:{index} {suite} inline:%s\\r\\n"' in body


def test_pcap_fixtures_are_anonymized() -> None:
    for fixture in FIXTURES.glob("*.json"):
        text = fixture.read_text(encoding="utf-8")
        payload = json.loads(text)
        assert payload["source"] == "synthetic_contract_fixture"
        assert not re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text)
        assert "inline:" not in text
        assert "token" not in text.lower()
        assert "call-id" not in text.lower()
        assert "branch=" not in text.lower()


def test_repository_does_not_expose_forbidden_reference_source_phrasing() -> None:
    paths = [
        *ROOT.glob("README.md"),
        *ROOT.glob("CHANGELOG.md"),
        *ROOT.glob(".github/release-notes/*.md"),
        *ROOT.glob("docs/**/*.md"),
        *ROOT.glob("custom_components/**/*.py"),
        *ROOT.glob("custom_components/**/*.js"),
        *ROOT.glob("scripts/**/*.py"),
        *ROOT.glob("tests/**/*.py"),
    ]

    offenders = [
        offender
        for path in paths
        for offender in _forbidden_reference_source_phrasing(path)
    ]

    assert offenders == []


def test_reference_source_phrasing_check_does_not_cross_word_boundaries(
    tmp_path: Path,
) -> None:
    document = tmp_path / "doc.md"
    document.write_text(
        "The reference appears only as a generic noun here.\n",
        encoding="utf-8",
    )

    assert _forbidden_reference_source_phrasing(document) == []


def test_reference_source_phrasing_reports_line_and_phrase(tmp_path: Path) -> None:
    document = tmp_path / "doc.md"
    app = "ap" + "p"
    document.write_text(f"Do not mention a reference {app} here.\n", encoding="utf-8")

    assert _forbidden_reference_source_phrasing(document) == [
        "doc.md:1: forbidden reference source phrase: reference application"
    ]


def _forbidden_reference_source_phrasing(path: Path) -> list[str]:
    patterns = _forbidden_reference_source_patterns()
    offenders: list[str] = []
    relative = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path.name
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        for label, pattern in patterns:
            if pattern.search(line):
                offenders.append(
                    f"{relative}:{line_number}: forbidden reference source phrase: {label}"
                )
    return offenders


def _forbidden_reference_source_patterns() -> tuple[tuple[str, re.Pattern[str]], ...]:
    app = "ap" + "p"
    official_mobile = "official " + "mobile"
    return (
        ("application reference", re.compile(rf"\b{app}\b\s*-?\s*reference\b", re.IGNORECASE)),
        ("reference application", re.compile(rf"\breference\s+{app}\b", re.IGNORECASE)),
        ("official application", re.compile(rf"\bofficial\s+{app}\b", re.IGNORECASE)),
        ("application pcap", re.compile(rf"\b{app}\b\s*-?\s*pcap\b", re.IGNORECASE)),
        ("application capture", re.compile(rf"\b{app}\b\s+capture\b", re.IGNORECASE)),
        (
            "mobile application capture",
            re.compile(rf"\bmobile\s+{app}\b\s+capture\b", re.IGNORECASE),
        ),
        (official_mobile, re.compile(r"\bofficial\s+mobile\b", re.IGNORECASE)),
    )


def test_pcap_fingerprint_extractor_redacts_keys_and_addresses() -> None:
    module = _script_module()
    sample = (
        "2030-01-01 IP 192.0.2.10.5060 > 198.51.100.20.5060: SIP\n"
        "INVITE sip:c300x@example.invalid SIP/2.0\r\n"
        "m=audio 1234 RTP/SAVP 96 98\r\n"
        "a=rtpmap:96 opus/48000/2\r\n"
        "a=rtpmap:98 speex/8000\r\n"
        "a=crypto:1 AES_CM_128_HMAC_SHA1_80 inline:secret-key\r\n"
        "m=video 5678 RTP/SAVP 96\r\n"
        "a=rtpmap:96 H264/90000\r\n"
        "a=crypto:1 AES_CM_128_HMAC_SHA1_80 inline:other-secret\r\n"
        '{"type":"doorbell.pressed","token":"do-not-keep"}'
    )

    fingerprint = module.parse_tcpdump_ascii(
        sample,
        mode="on_demand",
        source="unit",
    )
    dumped = json.dumps(fingerprint, sort_keys=True)

    assert "192.0.2.10" not in dumped
    assert "198.51.100.20" not in dumped
    assert "secret-key" not in dumped
    assert "other-secret" not in dumped
    assert fingerprint["offer"]["audio"]["crypto_suites"] == [
        "AES_CM_128_HMAC_SHA1_80"
    ]
    assert fingerprint["events"] == ["doorbell.pressed"]


def test_reference_on_demand_fingerprint_matches_native_invite_offer() -> None:
    fingerprint = _fingerprint("reference_on_demand.json")
    media_bridge = _read_media_bridge()
    setup_body = _section(
        media_bridge,
        "static bool send_sip_setup",
        "static bool send_bt_av_media_command",
    )
    offer = fingerprint["offer"]

    _assert_media_line(setup_body, "audio", offer["audio"]["payloads"])
    _assert_codecs(setup_body, offer["audio"]["codecs"])
    _assert_crypto_suites(setup_body, offer["audio"]["crypto_suites"])
    _assert_media_line(setup_body, "video", offer["video"]["payloads"])
    _assert_codecs(setup_body, offer["video"]["codecs"])
    _assert_crypto_suites(setup_body, offer["video"]["crypto_suites"])
    assert '"a=recvonly\\r\\n"' in setup_body
    assert "bridge_instance_uuid(bridge, bridge->ondemand_instance_uuid, \"ondemand\"" in (
        setup_body
    )


def test_on_demand_offer_does_not_reintroduce_static_pcmu_pcma_rtpmap() -> None:
    fingerprint = _fingerprint("reference_on_demand.json")
    media_bridge = _read_media_bridge()
    setup_body = _section(
        media_bridge,
        "static bool send_sip_setup",
        "static bool send_bt_av_media_command",
    )

    assert "known_code_differences" not in fingerprint
    assert "PCMU/8000" not in fingerprint["offer"]["audio"]["codecs"]
    assert "PCMA/8000" not in fingerprint["offer"]["audio"]["codecs"]
    assert '"a=rtpmap:0 PCMU/8000\\r\\n"' not in setup_body
    assert '"a=rtpmap:8 PCMA/8000\\r\\n"' not in setup_body


def test_reference_home_call_fingerprint_matches_native_invite_offer() -> None:
    fingerprint = _fingerprint("reference_home_call.json")
    media_bridge = _read_media_bridge()
    home_call_body = _section(
        media_bridge,
        "static bool build_home_call_sdp",
        "static bool send_home_call_register",
    )
    offer = fingerprint["offer"]

    _assert_media_line(home_call_body, "audio", offer["audio"]["payloads"])
    _assert_codecs(home_call_body, offer["audio"]["codecs"])
    _assert_crypto_suites(home_call_body, offer["audio"]["crypto_suites"])
    assert '"m=video' not in home_call_body
    assert "bridge_instance_uuid(bridge, bridge->home_call_instance_uuid" in (
        media_bridge
    )


def test_reference_ring_call_fingerprint_matches_native_ring_media_flow() -> None:
    fingerprint = _fingerprint("reference_ring_call.json")
    media_bridge = _read_media_bridge()
    camera = _read_camera()
    api = _read_api()
    const = _read_const()
    ring_sdp = _section(media_bridge, "static bool build_ring_sdp", "static void")
    ring_invite = _section(
        media_bridge,
        "static void handle_ring_invite",
        "static bool ring_sleep_seconds",
    )
    ring_loop = _section(
        media_bridge,
        "static void ring_media_loop",
        "static void handle_ring_invite",
    )
    native = fingerprint["native_ring_sdp"]
    ha_ref = fingerprint["ha_reference"]

    _assert_media_line(ring_sdp, "audio", native["audio"]["payloads"])
    _assert_codecs(ring_sdp, native["audio"]["codecs"])
    _assert_crypto_suites(ring_sdp, native["audio"]["crypto_suites"])
    _assert_media_line(ring_sdp, "video", native["video"]["payloads"])
    _assert_codecs(ring_sdp, native["video"]["codecs"])
    _assert_crypto_suites(ring_sdp, native["video"]["crypto_suites"])
    assert "#define RING_EARLY_MEDIA_DELAY_MS 300" in media_bridge
    assert "audio_active ? \"\" : \"a=inactive\\r\\n\"" in ring_sdp
    assert '"a=recvonly\\r\\n"' in ring_sdp
    assert '100, "Trying"' in ring_invite
    assert '180, "Ringing"' in ring_invite
    assert '183, "Session progress"' in ring_invite
    assert 'send_ring_response(bridge, sip_fd, invite, 200, "Ok"' in ring_loop
    assert "send_media_audio_silence_payload_type(" in ring_loop
    assert ha_ref["preview_rtsp_path"] in const
    assert "self._video_stream_path = str(status[\"stream_path\"])" in camera
    assert ha_ref["answered_rtsp_path"] in camera
    assert ha_ref["answer_action"] in api
    assert ha_ref["hangup_action"] in api
