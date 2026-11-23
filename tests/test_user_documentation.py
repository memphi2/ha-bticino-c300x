"""Focused documentation contracts for removal and WebRTC policy choices."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from custom_components.bticino_c300x.camera_media.webrtc_ice_filter import (
    ice_candidate_should_pass,
)
from custom_components.bticino_c300x.const import (
    DEFAULT_WEBRTC_ICE_POLICY,
    WEBRTC_ICE_POLICIES,
)

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
ICE_LINK = "media-troubleshooting.md#connection-paths-for-the-live-picture"
REMOVAL_LINK = "advanced-maintenance.md#remove-home-assistant-integration"
ADDRESS_GROUPS = {
    "IPv4": "192.0.2.5",
    "IPv4 link-local": "169.254.1.1",
    "IPv6 link-local": "fe80::1%eth0",
    "IPv6 ULA": "fd12::1",
    "Other IPv6": "2001:db8::1",
}


def section(document: str, heading: str) -> str:
    text = (DOCS / document).read_text(encoding="utf-8")
    return text.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]


def test_support_policy_matches_latest_dated_stable_release():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    versions = re.findall(r"^## v(\d+\.\d+\.\d+) - \d{4}-\d{2}-\d{2}$", changelog, re.M)
    assert versions, "A stable release must be documented in the changelog"
    stable = versions[0]
    minor = stable.rsplit(".", 1)[0]
    support = (ROOT / "SUPPORT.md").read_text(encoding="utf-8")
    assert f"- `{minor}.x`: current stable ({stable})" in support
    assert support.count("current stable") == 1


def ice_rows():
    text = section("media-troubleshooting.md", "Connection Paths for the Live Picture")
    rows = re.findall(r"^\| ([^|]+) \| `([^`]+)` \| ([^|]+) \| ([^|]+) \|$", text, re.M)
    assert len(rows) == len(WEBRTC_ICE_POLICIES)
    assert {row[1] for row in rows} == set(WEBRTC_ICE_POLICIES)
    return {policy: (label, set() if dropped == "None" else set(dropped.split("; ")))
            for label, policy, dropped, _use in rows}


@pytest.mark.parametrize("policy", WEBRTC_ICE_POLICIES)
def test_documented_ice_choices_and_drops_match_actual_filter(policy):
    label, dropped = ice_rows()[policy]
    translations = json.loads((ROOT / "custom_components/bticino_c300x/strings.json").read_text())
    assert label == translations["selector"]["webrtc_ice_policy"]["options"][policy]
    assert dropped <= ADDRESS_GROUPS.keys()
    for group, address in ADDRESS_GROUPS.items():
        candidate = f"candidate:1 1 udp 1 {address} 5000 typ host"
        assert ice_candidate_should_pass(candidate, policy) == (group not in dropped)


def test_ice_docs_state_real_default_and_non_absolute_family_filter():
    text = " ".join(section("media-troubleshooting.md", "Connection Paths for the Live Picture").split())
    assert f"recommended** (`{DEFAULT_WEBRTC_ICE_POLICY}`)." in text
    for phrase in (
        "TURN relay candidates", "mDNS `.local` candidates", "unparseable candidate lines",
        "provider-to-browser", "answer SDP", "trickled candidates",
        "Browser-to-provider candidates are not filtered",
        "IPv4 only is not a guarantee of an IPv4-only connection",
        "IPv4-mapped IPv6", "not just globally routable", "not their priority",
        "does not install a device patch",
    ):
        assert phrase in text
    for policy in WEBRTC_ICE_POLICIES:
        for address in ("2001:db8::1", "fd12::1", "fe80::1"):
            assert ice_candidate_should_pass(f"candidate:1 1 udp 1 {address} 9 typ relay", policy)
        assert ice_candidate_should_pass("candidate:1 1 udp 1 camera.local 9 typ host", policy)
        assert ice_candidate_should_pass("unparseable", policy)
    assert ice_candidate_should_pass("candidate:1 1 udp 1 ::ffff:192.0.2.5 9 typ host", "ipv4_only")
    assert not ice_candidate_should_pass("candidate:1 1 udp 1 ::1 9 typ host", "prefer_ipv4_ula")


@pytest.mark.parametrize("document", ["quickstart.md", "feature-reference.md"])
def test_setup_docs_link_policy_and_removal_guides(document):
    text = (DOCS / document).read_text(encoding="utf-8")
    assert f"]({ICE_LINK})" in text
    assert f"]({REMOVAL_LINK})" in text
    assert "IPv4 and local IPv6 (ULA) -" in text
    assert "## Connection Paths for the Live Picture" in (DOCS / ICE_LINK.split("#")[0]).read_text()
    assert "## Remove Home Assistant Integration" in (DOCS / REMOVAL_LINK.split("#")[0]).read_text()


def test_removal_docs_distinguish_entry_package_device_and_retained_data():
    text = " ".join(section("advanced-maintenance.md", "Remove Home Assistant Integration").split())
    for phrase in (
        "separate operations", "does not uninstall the device agent",
        "Settings > Devices & services", "**Delete**", "**Marketplace (HA 2026.11+):**",
        "**Uninstall**", "**HACS:**", "**Remove**", "**Manual installation:**",
        "custom_components/bticino_c300x", "another C300X entry still uses it",
        "actually includes their media storage", "not a C300X firmware/config backup",
        "Snapshot retention stops", "does not adopt that old snapshot directory",
        ".storage/bticino_c300x.snapshots.<entry_id>", "not credential revocation",
        "not a historical-data purge", "does not erase older backup copies",
        "Do not edit `.storage` while HA is running", "no removal operation was performed",
    ):
        assert phrase in text
    assert text.index("backup before removing configuration") < text.index("**Delete**")
    assert text.index("**Delete**") < text.index("**Uninstall**")
    for url in (
        "https://www.home-assistant.io/common-tasks/general/#removing-an-integration-instance",
        "https://www.home-assistant.io/integrations/marketplace/#uninstalling-a-repository",
        "https://www.hacs.xyz/docs/use/repositories/dashboard/#removing-a-repository",
        "https://www.home-assistant.io/common-tasks/general/backups/",
    ):
        assert url in text


def test_agent_removal_docs_disclose_writes_backup_removal_and_reboot():
    text = " ".join(section("advanced-maintenance.md", "Remove Agent").split())
    for phrase in (
        "device-writing, rebooting operation", "not the HA-entry Delete action",
        "no active call or recording", "only if you intend this removal",
        "config.json", "removes its managed device-file backup root",
        "scheduling a device reboot", "starts SSH for recovery",
        "retains agent files/backups", "not a promise that every earlier step was rolled back",
        "not a factory reset", "does not erase HA media or HA backups",
    ):
        assert phrase in text
    script = (ROOT / "native_agent/scripts/remove_agent.sh").read_text()
    assert 'rm -rf "$AGENT_DIR" "$BACKUP_ROOT"' in script
    assert "schedule_reboot" in script


def test_three_documentation_rules_are_closed_with_evidence_only():
    rules = yaml.safe_load((ROOT / "custom_components/bticino_c300x/quality_scale.yaml").read_text())["rules"]
    for rule in ("docs-removal-instructions", "docs-installation-parameters", "docs-configuration-parameters"):
        assert rules[rule]["status"] == "done"
        assert rules[rule]["comment"]
    audit = (DOCS / "dev" / "quality-scale.md").read_text()
    assert "test_user_documentation.py" in audit
    assert f"](../{REMOVAL_LINK})" in audit
    assert f"](../{ICE_LINK})" in audit


def test_the_api_lists_every_error_the_agent_update_answers_with():
    source = (ROOT / "native_agent/src/agent_update.c").read_text()
    body = source.split("const char *agent_update_error_json", 1)[1].split("\n}\n", 1)[0]
    codes = re.findall(r'\\"error\\":\\"([a-z_]+)\\"', body)
    assert "update_root_already_writable" in codes
    api = (ROOT / "native_agent/API.md").read_text()
    section = api.split("`POST /api/v1/maintenance/update/apply`", 1)[1].split("\n### ", 1)[0]
    for code in codes:
        assert f"`{code}`" in section


def test_the_api_names_every_display_call_that_follows_the_ui_port():
    sources = [ROOT / "native_agent/scripts/qml_patch.sh"]
    sources += sorted((ROOT / "device_qml").rglob("*.qml")) + sorted((ROOT / "device_qml").rglob("*.js"))
    routes = set()
    for path in sources:
        routes |= set(re.findall(r'uiBaseUrl \+ "(/ui/[a-z/-]+)', path.read_text(encoding="utf-8")))
    assert "/ui/media-closed" in routes
    api = (ROOT / "native_agent/API.md").read_text()
    paragraph = api.split("Only these calls follow a changed port:", 1)[1].split("\n\n", 1)[0]
    assert set(re.findall(r"`(/ui/[a-z/-]+)`", paragraph)) == routes


def test_the_api_lists_every_error_the_picture_route_answers_with():
    sources = (ROOT / "native_agent/src/picture_control.c").read_text()
    codes = set(re.findall(r'\\"error\\":\\"([a-z_]+)\\"', sources)) - {"method_not_allowed"}
    ringer = (ROOT / "native_agent/src/ringer_control.c").read_text()
    codes |= set(re.findall(r'"(picture_gui_[a-z]+)"', ringer))
    assert {"media_busy", "picture_gui_timeout"} <= codes
    api = (ROOT / "native_agent/API.md").read_text()
    section = api.split("### `GET`, `POST /api/v1/video/picture`", 1)[1].split("\n### ", 1)[0]
    for code in codes:
        assert f"`{code}`" in section
    assert "| `409` | `media_busy` |" in section
