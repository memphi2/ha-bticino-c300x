#!/usr/bin/env python3
"""Validate the HA/go2rtc media integration contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "custom_components" / "bticino_c300x" / "manifest.json"
CAMERA = ROOT / "custom_components" / "bticino_c300x" / "camera.py"
CAMERA_TESTS = ROOT / "tests" / "test_camera.py"

REQUIRED_CAMERA_TOKENS = (
    "_async_get_supported_webrtc_provider",
    "No Home Assistant WebRTC provider is available for the C300X RTSP stream",
    "provider_offer_failed = False",
    "provider_offer_failed = True",
    "await self._async_close_webrtc_session(",
    "session.ready = True",
)
REQUIRED_CAMERA_TESTS = (
    "test_doorbell_camera_webrtc_offer_reports_missing_provider",
    "test_doorbell_camera_provider_offer_error_closes_local_session",
    "test_doorbell_camera_home_call_provider_offer_error_stops_call",
    "test_doorbell_camera_provider_offer_uses_backchannel_for_talkback",
    "test_doorbell_camera_provider_offer_omits_backchannel_without_microphone",
    "test_doorbell_camera_ring_webrtc_offers_share_one_rtsp_source",
)


def main() -> int:
    failures = check_media_contracts()
    if failures:
        for failure in failures:
            sys.stderr.write(f"FAIL: {failure}\n")
        return 1
    sys.stdout.write("Media/go2rtc contract validation passed\n")
    return 0


def check_media_contracts() -> list[str]:
    failures: list[str] = []
    failures.extend(_check_manifest_contract())
    failures.extend(_check_camera_contract())
    failures.extend(_check_camera_tests())
    return failures


def _check_manifest_contract() -> list[str]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    failures: list[str] = []
    dependencies = set(manifest.get("dependencies", []))
    requirements = set(manifest.get("requirements", []))
    after_dependencies = set(manifest.get("after_dependencies", []))
    if "go2rtc" not in dependencies:
        failures.append("manifest.json must keep go2rtc as a hard dependency")
    if "go2rtc" in after_dependencies:
        failures.append("manifest.json must not make go2rtc a soft after_dependency")
    if any(str(requirement).startswith("aiortc") for requirement in requirements):
        failures.append("manifest.json must not reintroduce aiortc runtime requirements")
    return failures


def _check_camera_contract() -> list[str]:
    source = CAMERA.read_text(encoding="utf-8")
    failures = [
        f"camera.py must keep provider contract token: {token}"
        for token in REQUIRED_CAMERA_TOKENS
        if token not in source
    ]
    failed_index = source.find("if provider_offer_failed:")
    ready_index = source.find("session.ready = True")
    if failed_index == -1 or ready_index == -1 or ready_index < failed_index:
        failures.append("camera.py must only mark provider sessions ready after offer-error handling")
    return failures


def _check_camera_tests() -> list[str]:
    tests = CAMERA_TESTS.read_text(encoding="utf-8")
    return [
        f"tests/test_camera.py must keep media contract test {test_name}"
        for test_name in REQUIRED_CAMERA_TESTS
        if test_name not in tests
    ]


if __name__ == "__main__":
    sys.exit(main())
