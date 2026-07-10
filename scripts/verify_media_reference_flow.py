#!/usr/bin/env python3
"""Verify local media implementation and captured flows against reference data."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "c300x_pcap_fingerprints"
MODES = ("ring_call", "on_demand", "home_call")

TIMESTAMP_RE = re.compile(
    r"(?m)^(?P<ts>20\d\d-\d\d-\d\d \d\d:\d\d:\d\d\.\d+)\s"
)
EVENT_RE = re.compile(
    r'"(?:event|event_type|type)"\s*:\s*"(?P<event>doorbell(?:\.[a-z_]+)+)"'
)
LENGTH_RE = re.compile(r"\blength\s+(?P<length>\d+)\b")
MEDIA_RE = re.compile(r"m=(audio|video)\s+\d+\s+RTP/SAVP\s+([0-9 ]+)")
RTPMAP_RE = re.compile(r"a=rtpmap:(\d+)\s+([^\r\n]+)")
CRYPTO_RE = re.compile(r"a=crypto:\d+\s+([A-Z0-9_]+)\s+inline:[^\r\n]+")
SIP_REQUEST_RE = re.compile(r"\b(INVITE|ACK|BYE|CANCEL|REGISTER)\s+[^\r\n]+SIP/2\.0")
SIP_STATUS_RE = re.compile(r"\bSIP/2\.0\s+([0-9]{3})\b")
RTSP_PATH_RE = re.compile(
    r"\b(?:DESCRIBE|SETUP|PLAY|TEARDOWN|OPTIONS)\s+"
    r"(?:rtsp://[^/\s]+)?(/[A-Za-z0-9._~/-]+)"
)


@dataclass(frozen=True)
class Packet:
    timestamp: datetime | None
    text: str
    length: int | None


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str = ""


def tcpdump_ascii(pcap_path: Path) -> str:
    try:
        result = subprocess.run(
            ["tcpdump", "-tttt", "-nn", "-A", "-s", "0", "-r", str(pcap_path)],
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
        )
    except FileNotFoundError as err:
        raise SystemExit("tcpdump is required for reference flow verification") from err
    if result.returncode != 0 and not result.stdout:
        raise SystemExit(result.stderr.strip() or "tcpdump failed")
    return result.stdout


def parse_tcpdump_ascii(text: str) -> list[Packet]:
    matches = list(TIMESTAMP_RE.finditer(text))
    if not matches:
        return [
            Packet(
                timestamp=None,
                text=text,
                length=_packet_length(text),
            )
        ]

    packets: list[Packet] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end]
        timestamp = datetime.strptime(match.group("ts"), "%Y-%m-%d %H:%M:%S.%f")
        packets.append(Packet(timestamp=timestamp, text=body, length=_packet_length(body)))
    return packets


def collect_pcap_checks(packets: list[Packet], *, mode: str) -> list[Check]:
    if mode != "ring_call":
        expected = {
            key: value
            for key, value in _fixture(mode).items()
            if key in {"offer", "answer"}
        }
        return collect_fingerprint_checks(
            fingerprint_from_text("\n".join(packet.text for packet in packets)),
            expected,
            prefix=f"pcap.{mode}",
        )

    events = _event_packets(packets)
    pressed = events.get("doorbell.pressed")
    closed = events.get("doorbell.media.closed")
    view = events.get("doorbell.view_requested")
    checks = [
        Check("pcap.has_pressed_event", pressed is not None),
        Check("pcap.has_closed_event", closed is not None),
        Check("pcap.has_view_requested_event", view is not None),
    ]
    if pressed is None or closed is None or view is None:
        return checks

    checks.extend(
        [
            Check("pcap.event_order.pressed_before_closed", _before(pressed, closed)),
            Check("pcap.event_order.closed_before_view", _before(closed, view)),
            Check(
                "pcap.pressed_state.ringing",
                _has_json_value(pressed.text, "doorbell", "ringing"),
            ),
            Check(
                "pcap.pressed_video.available",
                _has_json_bool(pressed.text, "available", True),
            ),
            Check(
                "pcap.pressed_video.window_available",
                _has_json_bool(pressed.text, "window_available", True),
            ),
            Check(
                "pcap.pressed_video.preview_path",
                _has_json_value(pressed.text, "stream_path", "/doorbell-video"),
            ),
            Check(
                "pcap.view_state.view_requested",
                _has_json_value(view.text, "doorbell", "view_requested"),
            ),
            Check(
                "pcap.view_video.available",
                _has_json_bool(view.text, "available", True),
            ),
            Check(
                "pcap.view_video.window_available",
                _has_json_bool(view.text, "window_available", True),
            ),
            Check(
                "pcap.view_video.preview_path",
                _has_json_value(view.text, "stream_path", "/doorbell-video"),
            ),
            Check(
                "pcap.preview_media_after_pressed",
                _has_packet_between(packets, pressed, closed, min_length=900),
            ),
            Check(
                "pcap.answered_control_after_view",
                _has_packet_after(packets, view, max_length=350),
            ),
        ]
    )
    checks.extend(_timing_checks(packets, pressed, closed, view))
    return checks


def collect_reference_pcap_checks(
    *,
    mode: str,
    reference_packets: list[Packet],
    candidate_packets: list[Packet],
) -> list[Check]:
    reference_text = "\n".join(packet.text for packet in reference_packets)
    candidate_text = "\n".join(packet.text for packet in candidate_packets)
    checks = collect_fingerprint_checks(
        fingerprint_from_text(candidate_text),
        fingerprint_from_text(reference_text),
        prefix=f"pcap_compare.{mode}",
    )
    if mode == "ring_call":
        checks.extend(
            _compare_ring_timing(
                reference_packets=reference_packets,
                candidate_packets=candidate_packets,
            )
        )
    return checks


def collect_fixture_gate_checks(
    *,
    mode: str,
    root: Path = ROOT,
) -> list[Check]:
    """Verify anonymized reference fingerprints and code invariants as one gate."""

    checks: list[Check] = []
    modes = MODES if mode == "all" else (mode,)
    for item in modes:
        checks.extend(_collect_fixture_integrity_checks(item))
    checks.extend(collect_code_checks(mode, root=root))
    return checks


def collect_fingerprint_checks(
    observed: dict[str, Any],
    expected: dict[str, Any],
    *,
    prefix: str,
) -> list[Check]:
    checks: list[Check] = []
    for key in ("sip_sequence", "rtsp_paths", "events"):
        if key in expected:
            checks.append(
                Check(
                    f"{prefix}.{key}",
                    observed.get(key, []) == expected[key],
                    detail=_diff_detail(observed.get(key, []), expected[key]),
                )
            )
    for section in ("offer", "answer"):
        if section in expected:
            checks.extend(
                _collect_media_fingerprint_checks(
                    observed.get(section, {}),
                    expected[section],
                    prefix=f"{prefix}.{section}",
                )
            )
    return checks


def fingerprint_from_text(text: str) -> dict[str, Any]:
    medias = _extract_media_sections(text)
    offer, answer = _offer_answer_from_media(medias)
    fingerprint: dict[str, Any] = {
        "sip_sequence": _extract_sip_sequence(text),
        "rtsp_paths": _extract_rtsp_paths(text),
        "events": _extract_events(text),
    }
    if offer:
        fingerprint["offer"] = offer
    if answer:
        fingerprint["answer"] = answer
    return {key: value for key, value in fingerprint.items() if value}


def collect_code_checks(mode: str, root: Path = ROOT) -> list[Check]:
    media_bridge = _read(root / "native_agent" / "src" / "media_bridge.c")
    event_payload = _read(root / "native_agent" / "src" / "event_payload.c")
    http = _read(root / "native_agent" / "src" / "http.c")
    webhook = _read(root / "custom_components" / "bticino_c300x" / "webhook.py")
    camera = _read(root / "custom_components" / "bticino_c300x" / "camera.py")
    api = _read_api_sources(root)
    const = _read(root / "custom_components" / "bticino_c300x" / "const.py")
    state_model = _read(
        root
        / "custom_components"
        / "bticino_c300x"
        / "frontend"
        / "c300x-state-model.js"
    )
    card_actions = _read(
        root
        / "custom_components"
        / "bticino_c300x"
        / "frontend"
        / "c300x-card-actions.js"
    )

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
    rtsp_body = _section(
        media_bridge,
        "static void handle_rtsp_client",
        "static int create_rtsp_listener",
    )
    ring_sdp = _section(media_bridge, "static bool build_ring_sdp", "static void")
    answer_bridge = _section(
        media_bridge,
        "bool c300x_media_ring_call_answer",
        "void c300x_media_ring_call_hangup",
    )

    checks: list[Check] = []
    if mode in ("all", "on_demand"):
        checks.extend(_collect_on_demand_code_checks(media_bridge, root))
    if mode in ("all", "home_call"):
        checks.extend(_collect_home_call_code_checks(media_bridge, root))
    if mode not in ("all", "ring_call"):
        return checks

    checks.extend([
        Check("code.native.early_media_delay", "#define RING_EARLY_MEDIA_DELAY_MS 300" in media_bridge),
        Check("code.native.preview_audio_inactive", 'audio_active ? "" : "a=inactive\\r\\n"' in ring_sdp),
        Check("code.native.answer_recvonly", '"a=recvonly\\r\\n"' in ring_sdp),
        Check("code.native.trying_before_ringing", _ordered(ring_invite, '100, "Trying"', '180, "Ringing"')),
        Check("code.native.ringing_before_progress", _ordered(ring_invite, '180, "Ringing"', '183, "Session progress"')),
        Check("code.native.answer_response_in_ring_loop", 'send_ring_response(bridge, sip_fd, invite, 200, "Ok"' in ring_loop),
        Check("code.native.preview_not_closed_before_answer", "shutdown_ring_preview_clients_locked(bridge);" not in ring_loop),
        Check("code.native.answer_stream_sharing_allowed", "ring_answer_stream_sharing_allowed_locked(&g_bridge)" in rtsp_body),
        Check(
            "code.native.preview_not_closed_after_answer_stream_play",
            "shutdown_ring_preview_clients_except_locked" not in rtsp_body
            and "close_preview_after_play" not in rtsp_body,
        ),
        Check(
            "code.native.teardown_waits_for_client_close",
            "RTSP_TEARDOWN_CLOSE_WAIT_SECONDS" in rtsp_body
            and "teardown_seen = true;" in rtsp_body
            and "slot_index = -1;" in rtsp_body,
        ),
        Check("code.native.answer_uses_ring_request", "request_ring_answer_if_active(&g_bridge)" in answer_bridge),
        Check("code.native.silence_uses_answer_payload", "send_media_audio_silence_payload_type(" in ring_loop),
        Check(
            "code.native.ring_event_payload_module_used",
            "c300x_event_payload_build_doorbell_state" in event_payload
            and "c300x_event_payload_build_data_json(" in http,
        ),
        Check("code.event_payload.pressed_supported", 'strcmp(event_type, "doorbell.pressed") == 0' in event_payload),
        Check("code.event_payload.closed_supported", 'strcmp(event_type, "doorbell.media.closed") == 0' in event_payload),
        Check("code.event_payload.view_supported", 'strcmp(event_type, "doorbell.view_requested") == 0' in event_payload),
        Check("code.event_payload.ring_event_pending", "ring_event_pending" in event_payload),
        Check("code.event_payload.exposes_ring_media_active", '\\"ring_media_active\\":%s' in event_payload),
        Check("code.event_payload.exposes_preview_sharing", '\\"ring_preview_sharing\\":%s' in event_payload),
        Check("code.webhook.forwards_video_bridge", 'event_data["bridge"] = dict(bridge)' in webhook),
        Check("code.webhook.forwards_media_owner", '"media_owner",' in webhook),
        Check("code.camera.preview_path_available", 'DEFAULT_VIDEO_STREAM_PATH = "/doorbell-video"' in const),
        Check("code.camera.answered_path_available", '"/doorbell"' in camera),
        Check("code.api.answer_action", "/api/v1/calls/doorbell/actions/answer" in api),
        Check("code.api.hangup_action", "/api/v1/calls/doorbell/actions/hangup" in api),
        Check("code.state_model.ring_pending_answerable", 'mediaState === "ring_pending"' in state_model),
        Check("code.state_model.preview_answerable", 'mediaState === "ring_preview_active"' in state_model),
        Check("code.card.answer_service", '"answer_doorbell_call"' in card_actions),
        Check("code.card.hangup_service", '"hangup_doorbell_call"' in card_actions),
    ])
    return checks


def report_checks(checks: list[Check], *, verbose: bool = False) -> None:
    failed = [check for check in checks if not check.ok]
    for check in checks:
        if verbose or not check.ok:
            suffix = f" {check.detail}" if check.detail else ""
            sys.stdout.write(f"{'ok' if check.ok else 'FAIL'} {check.name}{suffix}\n")
    sys.stdout.write(f"checks={len(checks)} failed={len(failed)}\n")


def _packet_length(text: str) -> int | None:
    matches = list(LENGTH_RE.finditer(text))
    if not matches:
        return None
    return int(matches[-1].group("length"))


def _event_packets(packets: list[Packet]) -> dict[str, Packet]:
    events: dict[str, Packet] = {}
    for packet in packets:
        for match in EVENT_RE.finditer(packet.text):
            events.setdefault(match.group("event"), packet)
    return events


def _json_object(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _fixture(mode: str) -> dict[str, Any]:
    fixture = FIXTURES / f"reference_{mode}.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"reference fixture is not an object: {fixture}")
    return cast(dict[str, Any], data)


def _collect_fixture_integrity_checks(mode: str) -> list[Check]:
    fixture = _fixture(mode)
    checks = [
        Check(f"fixture.{mode}.schema_version", fixture.get("schema_version") == 1),
        Check(f"fixture.{mode}.mode", fixture.get("mode") == mode),
        Check(
            f"fixture.{mode}.source_is_synthetic_contract",
            fixture.get("source") == "synthetic_contract_fixture",
        ),
    ]
    if mode in {"on_demand", "home_call"}:
        checks.extend(_collect_session_fixture_checks(mode, fixture))
    elif mode == "ring_call":
        checks.extend(_collect_ring_fixture_checks(fixture))
    return checks


def _collect_session_fixture_checks(mode: str, fixture: dict[str, Any]) -> list[Check]:
    expected_sequence = ["INVITE", "100", "180", "200", "ACK", "BYE", "200"]
    offer = _json_object(fixture.get("offer"))
    answer = _json_object(fixture.get("answer"))
    ha_reference = _json_object(fixture.get("ha_reference"))
    checks = [
        Check(
            f"fixture.{mode}.sip_sequence",
            fixture.get("sip_sequence") == expected_sequence,
            detail=_diff_detail(fixture.get("sip_sequence"), expected_sequence),
        ),
        Check(f"fixture.{mode}.offer_present", bool(offer)),
        Check(f"fixture.{mode}.answer_present", bool(answer)),
    ]
    if offer:
        checks.extend(
            _collect_media_fingerprint_checks(
                offer,
                {"audio": offer.get("audio", {})} if mode == "home_call" else offer,
                prefix=f"fixture.{mode}.offer",
            )
        )
    if answer:
        checks.extend(
            _collect_media_fingerprint_checks(
                answer,
                {"audio": answer.get("audio", {})} if mode == "home_call" else answer,
                prefix=f"fixture.{mode}.answer",
            )
        )
    checks.append(
        Check(
            f"fixture.{mode}.home_call_audio_only",
            mode != "home_call" or "video" not in offer,
        )
    )
    checks.extend(_collect_rtsp_contract_checks(mode, fixture))
    if mode == "on_demand":
        checks.extend(
            [
                Check(
                    "fixture.on_demand.audio_video_path",
                    ha_reference.get("audio_video_rtsp_path") == "/doorbell",
                ),
                Check(
                    "fixture.on_demand.video_path",
                    ha_reference.get("video_rtsp_path") == "/doorbell-video",
                ),
                Check(
                    "fixture.on_demand.activate_action",
                    ha_reference.get("activate_action")
                    == "/api/v1/video/doorbell/actions/activate",
                ),
                Check(
                    "fixture.on_demand.stop_action",
                    ha_reference.get("stop_action")
                    == "/api/v1/video/doorbell/actions/stop",
                ),
            ]
        )
    elif mode == "home_call":
        checks.extend(
            [
                Check(
                    "fixture.home_call.audio_path",
                    ha_reference.get("audio_rtsp_path") == "/doorbell",
                ),
                Check(
                    "fixture.home_call.start_action",
                    ha_reference.get("start_action")
                    == "/api/v1/calls/home/actions/start",
                ),
                Check(
                    "fixture.home_call.stop_action",
                    ha_reference.get("stop_action")
                    == "/api/v1/calls/home/actions/stop",
                ),
            ]
        )
    return checks


def _collect_ring_fixture_checks(fixture: dict[str, Any]) -> list[Check]:
    expected_sequence = ["INVITE", "100", "180", "183", "200", "ACK", "BYE", "200"]
    expected_phases = [
        {
            "direction": "device_to_client",
            "name": "preview_video",
            "payload_type": 96,
            "size": "large",
        },
        {
            "direction": "bidirectional",
            "name": "answered_audio_talkback",
            "payload_type": 96,
            "size": "small",
        },
    ]
    native = fixture.get("native_ring_sdp")
    ha_reference = fixture.get("ha_reference")
    phases = fixture.get("media_phases")
    native_dict = native if isinstance(native, dict) else {}
    ha_reference_dict = ha_reference if isinstance(ha_reference, dict) else {}
    checks = [
        Check(
            "fixture.ring_call.sip_sequence",
            fixture.get("sip_sequence") == expected_sequence,
            detail=_diff_detail(fixture.get("sip_sequence"), expected_sequence),
        ),
        Check("fixture.ring_call.native_sdp_present", bool(native_dict)),
        Check(
            "fixture.ring_call.early_audio_inactive",
            native_dict.get("early_audio_active") is False,
        ),
        Check(
            "fixture.ring_call.answer_audio_active",
            native_dict.get("answer_audio_active") is True,
        ),
        Check(
            "fixture.ring_call.preview_path",
            ha_reference_dict.get("preview_rtsp_path") == "/doorbell-video",
        ),
        Check(
            "fixture.ring_call.answered_path",
            ha_reference_dict.get("answered_rtsp_path") == "/doorbell",
        ),
        Check(
            "fixture.ring_call.answer_action",
            ha_reference_dict.get("answer_action")
            == "/api/v1/calls/doorbell/actions/answer",
        ),
        Check(
            "fixture.ring_call.hangup_action",
            ha_reference_dict.get("hangup_action")
            == "/api/v1/calls/doorbell/actions/hangup",
        ),
        Check(
            "fixture.ring_call.media_phases",
            phases == expected_phases,
            detail=_diff_detail(phases, expected_phases),
        ),
    ]
    checks.extend(_collect_rtsp_contract_checks("ring_call", fixture))
    if native_dict:
        checks.extend(
            _collect_media_fingerprint_checks(
                {
                    "audio": native_dict.get("audio", {}),
                    "video": native_dict.get("video", {}),
                },
                {
                    "audio": native_dict.get("audio", {}),
                    "video": native_dict.get("video", {}),
                },
                prefix="fixture.ring_call.native_sdp",
            )
        )
    return checks


def _collect_rtsp_contract_checks(mode: str, fixture: dict[str, Any]) -> list[Check]:
    expected = {
        "ring_call": {
            "methods": ["PLAY", "TEARDOWN"],
            "paths": ["/doorbell-video", "/doorbell"],
            "teardown_required": True,
        },
        "on_demand": {
            "methods": ["DESCRIBE", "SETUP", "PLAY", "TEARDOWN"],
            "paths": ["/doorbell", "/doorbell-video"],
            "teardown_required": True,
        },
        "home_call": {
            "methods": ["DESCRIBE", "SETUP", "PLAY", "TEARDOWN"],
            "paths": ["/doorbell"],
            "teardown_required": True,
        },
    }[mode]
    contract = _json_object(fixture.get("rtsp_contract"))
    return [
        Check(
            f"fixture.{mode}.rtsp.methods",
            contract.get("methods") == expected["methods"],
            detail=_diff_detail(contract.get("methods"), expected["methods"]),
        ),
        Check(
            f"fixture.{mode}.rtsp.paths",
            contract.get("paths") == expected["paths"],
            detail=_diff_detail(contract.get("paths"), expected["paths"]),
        ),
        Check(
            f"fixture.{mode}.rtsp.teardown_required",
            contract.get("teardown_required") is expected["teardown_required"],
        ),
    ]


def _collect_on_demand_code_checks(media_bridge: str, root: Path) -> list[Check]:
    setup_body = _section(
        media_bridge,
        "static bool send_sip_setup",
        "static bool send_bt_av_media_command",
    )
    rtsp_body = _section(
        media_bridge,
        "static void handle_rtsp_client",
        "static int create_rtsp_listener",
    )
    api = _read_api_sources(root)
    camera = _read(root / "custom_components" / "bticino_c300x" / "camera.py")
    const = _read(root / "custom_components" / "bticino_c300x" / "const.py")
    offer = _fixture("on_demand")["offer"]
    checks = _collect_media_code_checks(
        setup_body,
        offer,
        prefix="code.on_demand.offer",
    )
    checks.extend(
        [
            Check("code.on_demand.recvonly", '"a=recvonly\\r\\n"' in setup_body),
            Check(
                "code.on_demand.instance_uuid_scope",
                'bridge_instance_uuid(bridge, bridge->ondemand_instance_uuid, "ondemand"'
                in setup_body,
            ),
            Check(
                "code.on_demand.default_preview_path",
                'DEFAULT_VIDEO_STREAM_PATH = "/doorbell-video"' in const,
            ),
            Check("code.on_demand.audio_rtsp_path", 'path = self._audio_stream_path' in camera),
            Check("code.on_demand.activate_action", "/api/v1/video/doorbell/actions/activate" in api),
            Check("code.on_demand.stop_action", "/api/v1/video/doorbell/actions/stop" in api),
            Check("code.on_demand.rtsp_teardown", 'strcmp(method, "TEARDOWN") == 0' in rtsp_body),
            Check("code.on_demand.teardown_stops_last_client", "remaining_clients == 0" in rtsp_body),
            Check(
                "code.on_demand.no_static_pcmu_rtpmap",
                '"a=rtpmap:0 PCMU/8000\\r\\n"' not in setup_body,
            ),
            Check(
                "code.on_demand.no_static_pcma_rtpmap",
                '"a=rtpmap:8 PCMA/8000\\r\\n"' not in setup_body,
            ),
        ]
    )
    return checks


def _collect_home_call_code_checks(media_bridge: str, root: Path) -> list[Check]:
    home_call_body = _section(
        media_bridge,
        "static bool build_home_call_sdp",
        "static bool send_home_call_register",
    )
    rtsp_body = _section(
        media_bridge,
        "static void handle_rtsp_client",
        "static int create_rtsp_listener",
    )
    api = _read_api_sources(root)
    camera = _read(root / "custom_components" / "bticino_c300x" / "camera.py")
    offer = _fixture("home_call")["offer"]
    checks = _collect_media_code_checks(
        home_call_body,
        offer,
        prefix="code.home_call.offer",
    )
    checks.extend(
        [
            Check("code.home_call.audio_only", '"m=video' not in home_call_body),
            Check(
                "code.home_call.instance_uuid_scope",
                "bridge_instance_uuid(bridge, bridge->home_call_instance_uuid"
                in media_bridge,
            ),
            Check(
                "code.home_call.state_events",
                "dispatch_home_call_state_event" in media_bridge
                and "home_call.started" in media_bridge
                and "home_call.answered" in media_bridge
                and "home_call.ended" in media_bridge,
            ),
            Check("code.home_call.start_action", "/api/v1/calls/home/actions/start" in api),
            Check("code.home_call.stop_action", "/api/v1/calls/home/actions/stop" in api),
            Check("code.home_call.audio_rtsp_path", "async_prepare_home_call_rtsp_stream" in camera),
            Check("code.home_call.rtsp_media_request", "request_home_call_media_if_active" in rtsp_body),
            Check("code.home_call.rtsp_teardown", 'strcmp(method, "TEARDOWN") == 0' in rtsp_body),
        ]
    )
    return checks


def _collect_media_code_checks(
    body: str,
    expected: dict[str, Any],
    *,
    prefix: str,
) -> list[Check]:
    checks: list[Check] = []
    for kind, expected_media in expected.items():
        payloads = " ".join(expected_media["payloads"])
        checks.append(
            Check(
                f"{prefix}.{kind}.media_line",
                f'"m={kind} %d RTP/SAVP {payloads}\\r\\n"' in body,
            )
        )
        for codec in expected_media["codecs"]:
            checks.append(
                Check(
                    f"{prefix}.{kind}.codec.{codec}",
                    '"a=rtpmap:' in body and f" {codec}\\r\\n" in body,
                )
            )
        for index, suite in enumerate(expected_media["crypto_suites"], start=1):
            checks.append(
                Check(
                    f"{prefix}.{kind}.crypto.{suite}",
                    f'"a=crypto:{index} {suite} inline:%s\\r\\n"' in body,
                )
            )
    return checks


def _collect_media_fingerprint_checks(
    observed: Any,
    expected: dict[str, Any],
    *,
    prefix: str,
) -> list[Check]:
    observed_dict = observed if isinstance(observed, dict) else {}
    checks: list[Check] = []
    for kind, expected_media in expected.items():
        observed_media = observed_dict.get(kind, {})
        if not isinstance(observed_media, dict):
            observed_media = {}
        for key in ("payloads", "codecs", "crypto_suites"):
            checks.append(
                Check(
                    f"{prefix}.{kind}.{key}",
                    observed_media.get(key, []) == expected_media.get(key, []),
                    detail=_diff_detail(
                        observed_media.get(key, []),
                        expected_media.get(key, []),
                    ),
                )
            )
    return checks


def _extract_sip_sequence(text: str) -> list[str]:
    sequence: list[tuple[int, str]] = []
    sequence.extend((match.start(), match.group(1)) for match in SIP_REQUEST_RE.finditer(text))
    sequence.extend((match.start(), match.group(1)) for match in SIP_STATUS_RE.finditer(text))
    return _compact_adjacent([item for _, item in sorted(sequence)])


def _extract_rtsp_paths(text: str) -> list[str]:
    paths: list[str] = []
    for match in RTSP_PATH_RE.finditer(text):
        _append_unique(paths, match.group(1))
    return paths


def _extract_events(text: str) -> list[str]:
    events: list[str] = []
    for match in EVENT_RE.finditer(text):
        _append_unique(events, match.group("event"))
    return events


def _extract_media_sections(text: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    matches = list(MEDIA_RE.finditer(text))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end]
        codecs: list[str] = []
        crypto_suites: list[str] = []
        for codec in RTPMAP_RE.finditer(body):
            _append_unique(codecs, codec.group(2).strip())
        for crypto in CRYPTO_RE.finditer(body):
            _append_unique(crypto_suites, crypto.group(1))
        sections.append(
            {
                "kind": match.group(1),
                "role": _media_role(text, match.start()),
                "payloads": match.group(2).split(),
                "codecs": codecs,
                "crypto_suites": crypto_suites,
            }
        )
    return sections


def _media_role(text: str, position: int) -> str | None:
    role: str | None = None
    role_start = -1
    for match in SIP_REQUEST_RE.finditer(text, 0, position):
        if match.start() > role_start:
            role_start = match.start()
            role = "offer" if match.group(1) == "INVITE" else None
    for match in SIP_STATUS_RE.finditer(text, 0, position):
        if match.start() > role_start:
            role_start = match.start()
            role = "answer" if match.group(1) == "200" else None
    return role


def _offer_answer_from_media(
    medias: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    offer: dict[str, Any] = {}
    answer: dict[str, Any] = {}
    if any(media.get("role") is not None for media in medias):
        for media in medias:
            role = media.get("role")
            kind = str(media["kind"])
            if role == "offer" and kind not in offer:
                offer[kind] = {
                    key: value
                    for key, value in media.items()
                    if key not in {"kind", "role"}
                }
            elif role == "answer" and kind not in answer:
                answer[kind] = {
                    key: value
                    for key, value in media.items()
                    if key not in {"kind", "role"}
                }
        return offer, answer

    seen: dict[str, int] = {"audio": 0, "video": 0}
    for media in medias:
        kind = str(media["kind"])
        target = offer if seen[kind] == 0 else answer if seen[kind] == 1 else None
        seen[kind] += 1
        if target is not None:
            target[kind] = {
                key: value
                for key, value in media.items()
                if key not in {"kind", "role"}
            }
    return offer, answer


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _compact_adjacent(items: list[str]) -> list[str]:
    compacted: list[str] = []
    for item in items:
        if not compacted or compacted[-1] != item:
            compacted.append(item)
    return compacted


def _diff_detail(observed: Any, expected: Any) -> str:
    if observed == expected:
        return ""
    return f"observed={observed!r} expected={expected!r}"


def _has_json_value(text: str, key: str, value: str) -> bool:
    return re.search(rf'"{re.escape(key)}"\s*:\s*"{re.escape(value)}"', text) is not None


def _has_json_bool(text: str, key: str, value: bool) -> bool:
    return re.search(rf'"{re.escape(key)}"\s*:\s*{str(value).lower()}', text) is not None


def _before(left: Packet, right: Packet) -> bool:
    if left.timestamp is None or right.timestamp is None:
        return False
    return left.timestamp < right.timestamp


def _has_packet_between(
    packets: list[Packet],
    start: Packet,
    end: Packet,
    *,
    min_length: int,
) -> bool:
    if start.timestamp is None or end.timestamp is None:
        return False
    return any(
        packet.timestamp is not None
        and start.timestamp < packet.timestamp < end.timestamp
        and packet.length is not None
        and packet.length >= min_length
        for packet in packets
    )


def _has_packet_after(
    packets: list[Packet],
    start: Packet,
    *,
    max_length: int,
) -> bool:
    if start.timestamp is None:
        return False
    return any(
        packet.timestamp is not None
        and start.timestamp < packet.timestamp
        and packet.length is not None
        and 0 < packet.length <= max_length
        for packet in packets
    )


def _timing_checks(
    packets: list[Packet],
    pressed: Packet,
    closed: Packet,
    view: Packet,
) -> list[Check]:
    if pressed.timestamp is None or closed.timestamp is None or view.timestamp is None:
        return [
            Check("pcap.timing.timestamps_present", False),
        ]
    first_large = _first_packet_between(packets, pressed, closed, min_length=900)
    first_small = _first_packet_after(packets, view, max_length=350)
    checks = [
        Check("pcap.timing.timestamps_present", True),
        Check(
            "pcap.timing.view_follows_close_quickly",
            0 <= (view.timestamp - closed.timestamp).total_seconds() <= 1.0,
        ),
        Check(
            "pcap.timing.preview_window_reasonable",
            1.0 <= (closed.timestamp - pressed.timestamp).total_seconds() <= 30.0,
        ),
    ]
    if first_large is None or first_large.timestamp is None:
        checks.append(Check("pcap.timing.large_media_delay", False))
    else:
        checks.append(
            Check(
                "pcap.timing.large_media_delay",
                0 <= (first_large.timestamp - pressed.timestamp).total_seconds() <= 5.0,
            )
        )
    if first_small is None or first_small.timestamp is None:
        checks.append(Check("pcap.timing.answered_control_delay", False))
    else:
        checks.append(
            Check(
                "pcap.timing.answered_control_delay",
                0 <= (first_small.timestamp - view.timestamp).total_seconds() <= 2.0,
            )
        )
    return checks


def _compare_ring_timing(
    *,
    reference_packets: list[Packet],
    candidate_packets: list[Packet],
) -> list[Check]:
    reference = _ring_timing(reference_packets)
    candidate = _ring_timing(candidate_packets)
    checks: list[Check] = []
    for key, expected in reference.items():
        observed = candidate.get(key)
        checks.append(
            Check(
                f"pcap_compare.ring_call.timing.{key}",
                observed is not None and abs(observed - expected) <= _timing_tolerance(key),
                detail=_diff_detail(observed, expected),
            )
        )
    return checks


def _ring_timing(packets: list[Packet]) -> dict[str, float]:
    events = _event_packets(packets)
    pressed = events.get("doorbell.pressed")
    closed = events.get("doorbell.media.closed")
    view = events.get("doorbell.view_requested")
    if (
        pressed is None
        or closed is None
        or view is None
        or pressed.timestamp is None
        or closed.timestamp is None
        or view.timestamp is None
    ):
        return {}
    first_large = _first_packet_between(packets, pressed, closed, min_length=900)
    first_small = _first_packet_after(packets, view, max_length=350)
    timings = {
        "preview_duration": (closed.timestamp - pressed.timestamp).total_seconds(),
        "view_after_close": (view.timestamp - closed.timestamp).total_seconds(),
    }
    if first_large is not None and first_large.timestamp is not None:
        timings["large_media_after_pressed"] = (
            first_large.timestamp - pressed.timestamp
        ).total_seconds()
    if first_small is not None and first_small.timestamp is not None:
        timings["small_media_after_view"] = (
            first_small.timestamp - view.timestamp
        ).total_seconds()
    answer_post = _first_packet_containing(
        packets,
        "POST /api/v1/calls/doorbell/actions/answer",
    )
    preview_play = _first_packet_containing(
        packets,
        "PLAY rtsp://",
        "/doorbell-video",
    )
    full_play = _first_packet_containing(
        packets,
        "PLAY rtsp://",
        "/doorbell/",
    )
    preview_teardown = _first_packet_containing(
        packets,
        "TEARDOWN rtsp://",
        "/doorbell-video",
    )
    if (
        pressed.timestamp is not None
        and preview_play is not None
        and preview_play.timestamp is not None
    ):
        timings["preview_play_after_pressed"] = (
            preview_play.timestamp - pressed.timestamp
        ).total_seconds()
    if (
        answer_post is not None
        and answer_post.timestamp is not None
        and full_play is not None
        and full_play.timestamp is not None
    ):
        timings["full_play_after_answer"] = (
            full_play.timestamp - answer_post.timestamp
        ).total_seconds()
    if (
        full_play is not None
        and full_play.timestamp is not None
        and preview_teardown is not None
        and preview_teardown.timestamp is not None
    ):
        timings["preview_teardown_after_full_play"] = (
            preview_teardown.timestamp - full_play.timestamp
        ).total_seconds()
    return timings


def _timing_tolerance(key: str) -> float:
    if key == "preview_duration":
        return 3.0
    if key == "large_media_after_pressed":
        return 2.0
    if key == "preview_teardown_after_full_play":
        return 0.05
    return 1.0


def _first_packet_between(
    packets: list[Packet],
    start: Packet,
    end: Packet,
    *,
    min_length: int,
) -> Packet | None:
    if start.timestamp is None or end.timestamp is None:
        return None
    for packet in packets:
        if (
            packet.timestamp is not None
            and start.timestamp < packet.timestamp < end.timestamp
            and packet.length is not None
            and packet.length >= min_length
        ):
            return packet
    return None


def _first_packet_after(
    packets: list[Packet],
    start: Packet,
    *,
    max_length: int,
) -> Packet | None:
    if start.timestamp is None:
        return None
    for packet in packets:
        if (
            packet.timestamp is not None
            and start.timestamp < packet.timestamp
            and packet.length is not None
            and 0 < packet.length <= max_length
        ):
            return packet
    return None


def _first_packet_containing(packets: list[Packet], *needles: str) -> Packet | None:
    for packet in packets:
        if all(needle in packet.text for needle in needles):
            return packet
    return None


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_api_sources(root: Path) -> str:
    # The client class is split across api.py + its domain mixin modules; scan
    # them together so endpoint checks find methods wherever they now live.
    api_dir = root / "custom_components" / "bticino_c300x"
    parts = ["api.py", "_api_media.py", "_api_maintenance.py", "_api_device.py", "_api_content.py"]
    return "".join(_read(api_dir / name) for name in parts)


def _section(text: str, start: str, end: str) -> str:
    start_index = text.index(start)
    return text[start_index : text.index(end, start_index)]


def _ordered(text: str, first: str, second: str) -> bool:
    return first in text and second in text and text.index(first) < text.index(second)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("all", *MODES),
        default="all",
        help="media mode to verify; PCAP comparison requires one concrete mode",
    )
    parser.add_argument("--pcap", type=Path)
    parser.add_argument("--reference-pcap", type=Path)
    parser.add_argument("--code-only", action="store_true")
    parser.add_argument(
        "--fixtures",
        action="store_true",
        help="verify anonymized fixture fingerprints plus code invariants",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if (args.pcap is not None or args.reference_pcap is not None) and args.mode == "all":
        raise SystemExit("--mode must be ring_call, on_demand, or home_call for PCAP checks")
    if args.reference_pcap is not None and args.pcap is None:
        raise SystemExit("--reference-pcap requires --pcap")

    checks = (
        collect_fixture_gate_checks(mode=args.mode)
        if args.fixtures
        else collect_code_checks(args.mode)
    )
    if args.pcap is not None and not args.code_only:
        candidate_packets = parse_tcpdump_ascii(tcpdump_ascii(args.pcap))
        if args.reference_pcap is None:
            checks.extend(collect_pcap_checks(candidate_packets, mode=args.mode))
        else:
            checks.extend(
                collect_reference_pcap_checks(
                    mode=args.mode,
                    reference_packets=parse_tcpdump_ascii(
                        tcpdump_ascii(args.reference_pcap)
                    ),
                    candidate_packets=candidate_packets,
                )
            )
    report_checks(checks, verbose=args.verbose)
    return 1 if any(not check.ok for check in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
