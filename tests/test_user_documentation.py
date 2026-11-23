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


def _c_skip(text, index):
    """The index after the string, character literal or comment at ``index``, else ``index``."""
    if text.startswith("/*", index):
        return text.index("*/", index) + 2
    if text.startswith("//", index):
        return text.index("\n", index)
    if text[index] in "\"'":
        end = index + 1
        while text[end] != text[index]:
            end += 2 if text[end] == "\\" else 1
        return end + 1
    return index


def _c_args(text, index):
    """The top-level arguments of the parenthesis at ``index`` and the index of its closing one."""
    args, depth, start = [], 0, index + 1
    while True:
        end = _c_skip(text, index)
        if end != index:
            index = end
            continue
        if text[index] in "([{":
            depth += 1
        elif text[index] in ")]}":
            depth -= 1
            if not depth:
                args.append(text[start:index])
                return [arg.strip() for arg in args], index
        elif text[index] == "," and depth == 1:
            args.append(text[start:index])
            start = index + 1
        index += 1


def _c_functions(source):
    """Every function defined in the C ``source``, by name, with its full text."""
    functions = {}
    for match in re.finditer(r"^[A-Za-z_][^;{}()\n]*?\b(\w+)\([^;{}]*?\)\s*\{", source, re.MULTILINE):
        end = match.end() - 1
        assert source[end] == "{"
        depth = 0
        while True:
            skipped = _c_skip(source, end)
            if skipped != end:
                end = skipped
                continue
            depth += {"{": 1, "}": -1}.get(source[end], 0)
            end += 1
            if not depth:
                break
        functions[match[1]] = source[match.start():end]
    return functions


def _c_function(source, name):
    """The text of the C function ``name`` defined in ``source``; fails when it is not defined there."""
    functions = _c_functions(source)
    assert name in functions, f"no C function {name}"
    return functions[name]


def _client_functions(functions, name, fd):
    """``name`` and every function in ``functions`` it (transitively) hands its client socket ``fd``."""
    found, pending = {}, [(name, fd)]
    while pending:
        name, fd = pending.pop()
        if name in found:
            continue
        assert name in functions, f"no C function {name}"
        found[name] = text = functions[name]
        for call in re.finditer(r"\b(\w+)\(", text[text.index("{"):]):
            args, _ = _c_args(text, text.index("{") + call.end() - 1)
            if call[1] in functions and fd in args:
                params, _ = _c_args(functions[call[1]], functions[call[1]].index("("))
                pending.append((call[1], params[args.index(fd)].split()[-1].lstrip("*")))
    return found


_ERROR_LITERAL = re.compile(r'\\"error\\":\\"([a-z_]+)\\"')


def _error_replies(functions):
    """``(status, code)`` of each error code the C ``functions`` answer with.

    A code is an ``\\"error\\":\\"<code>\\"`` JSON literal or a literal passed to an error helper,
    a function of ``functions`` that formats ``\\"error\\":\\"%s\\"``. Its status is the HTTP status
    among the arguments of the innermost call that carries it, or None.
    """
    helpers = {name for name, text in functions.items() if '\\"error\\":\\"%s\\"' in text}
    replies = set()
    for text in functions.values():
        calls, index = [], 0
        while index < len(text):
            end = _c_skip(text, index)
            if end != index:
                literal = text[index:end]
                codes = _ERROR_LITERAL.findall(literal)
                if calls and calls[-1][0] in helpers:
                    codes += re.findall(r'^"([a-z_]+)"$', literal)
                if calls:
                    calls[-1][2].extend(codes)
                else:
                    replies |= {(None, code) for code in codes}
                index = end
                continue
            if text[index] == "(":
                calls.append((re.search(r"(\w*)\s*$", text[:index])[1], index, []))
            elif text[index] == ")" and calls[-1][2]:
                _, start, codes = calls.pop()
                statuses = [int(status) for status in re.findall(r"\b[1-5]\d\d\b", _c_blank(text[start:index]))]
                if not statuses and calls:
                    calls[-1][2].extend(codes)  # e.g. a body built here and sent by the enclosing call
                else:
                    statuses = statuses * len(codes) if len(statuses) == 1 else statuses or [None] * len(codes)
                    replies |= set(zip(statuses, codes, strict=True))
            elif text[index] == ")":
                calls.pop()
            index += 1
    return replies


def _c_blank(text):
    """``text`` with its string and character literals and comments blanked out."""
    blanked, index = [], 0
    while index < len(text):
        end = _c_skip(text, index)
        blanked.append(" " if end != index else text[index])
        index = max(end, index + 1)
    return "".join(blanked)


def _api_error_rows(heading):
    """``(status, code)`` of each row of the error table in the API.md section after ``heading``."""
    section = (ROOT / "native_agent/API.md").read_text().split(heading, 1)[1].split("\n### ", 1)[0]
    return {(int(status), code) for status, code in re.findall(r"^\| `(\d{3})` \| `([a-z_]+)` \|", section, re.MULTILINE)}


def test_the_api_lists_every_error_the_agent_update_answers_with():
    # The handler refuses a request itself, also through the send_* helpers it
    # hands its client socket to, before the install starts.
    functions = _client_functions(_c_functions((ROOT / "native_agent/src/http.c").read_text()),
                                  "handle_agent_update_apply", "client_fd")
    assert "send_maintenance_unauthorized" in functions
    replies = _error_replies(functions)
    assert None not in {status for status, _ in replies}
    # A failed install answers agent_update_error_json(error) with the status
    # agent_update_error_status(error) picks for the same error.
    handler = functions["handle_agent_update_apply"]
    assert "agent_update_error_status(summary.error)" in handler
    assert "agent_update_error_json(summary.error)" in handler
    update = _c_functions((ROOT / "native_agent/src/agent_update.c").read_text())
    install = {code for _, code in _error_replies({"json": update["agent_update_error_json"]})}
    cases = dict(re.findall(r'(?:case (\w+)|default):\s*return "(?:[^"\\]|\\.)*?\\"error\\":\\"([a-z_]+)\\"',
                            update["agent_update_error_json"]))
    assert set(cases.values()) == install
    special, status, other = re.search(r"return error == (\w+) \? (\d{3}) : (\d{3});",
                                       update["agent_update_error_status"]).groups()
    replies |= {(int(status) if error == special else int(other), code) for error, code in cases.items()}
    assert (409, "update_root_already_writable") in replies
    assert replies == _api_error_rows("`POST /api/v1/maintenance/update/apply`")


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
    picture = _c_functions((ROOT / "native_agent/src/picture_control.c").read_text())
    ringer = _c_functions((ROOT / "native_agent/src/ringer_control.c").read_text())
    assert not picture.keys() & ringer.keys()
    # picture_request answers itself or hands the client to the GUI path in
    # ringer_control.c. That path keeps the client and answers it later from
    # picture_reply, on its timeout and at shutdown.
    functions = _client_functions(picture | ringer, "picture_request", "fd")
    assert {"c300x_gui_picture_request", "gui_request"} <= functions.keys()
    functions |= picture
    for name in ("c300x_ringer_control_expire", "c300x_ringer_control_close"):
        functions[name] = ringer[name]
    replies = _error_replies(functions)
    ringer_only = {
        "ringer_gui_busy": "gui_request answers it to a ringer command; a picture command gets picture_gui_busy",
        "ringer_not_applied": "the ringer branch of c300x_ringer_control_expire",
        "ringer_gui_timeout": "the ringer branch of c300x_ringer_control_expire",
    }
    assert set(ringer_only) <= {code for _, code in replies}
    replies = {(status, code) for status, code in replies if code not in ringer_only}
    assert {(504, "picture_gui_timeout"), (503, "ringer_gui_unavailable")} <= replies
    assert replies == _api_error_rows("### `GET`, `POST /api/v1/video/picture`")
    section = (ROOT / "native_agent/API.md").read_text().split("### `GET`, `POST /api/v1/video/picture`", 1)[1]
    unavailable = section.split("| `picture_controls_unavailable` |", 1)[1].split("\n", 1)[0]
    # picture_reply answers it when the GUI sends malformed values.
    assert "the GUI answered with missing or out-of-range values" in unavailable


def test_the_api_names_the_unread_refusal_of_display_bridge_events():
    source = (ROOT / "native_agent/src/http.c").read_text()
    assert '\\"error\\":\\"invalid_unread\\"' in source
    # Only a body that carries unread is validated; any other body is accepted.
    event = _c_function((ROOT / "native_agent/src/memo_led.c").read_text(), "c300x_memo_led_event")
    presence = event.index('c300x_json_find_member(body, body + strlen(body), "unread", &value)) return 1;')
    assert presence < event.index("c300x_json_object_valid(body)")
    api = (ROOT / "native_agent/API.md").read_text()
    section = api.split("optional boolean `unread`", 1)[1].split("\n### ", 1)[0]
    refusal = " ".join(section.split("`400 invalid_unread`", 1)[1].split(";", 1)[0].split())
    condition = "when the body carries `unread` and "
    assert refusal.startswith(condition)
    cases = refusal.removeprefix(condition)
    for case in ("the topic is another one", "the value is not a boolean", "the body is not a valid JSON object"):
        assert case in cases
    assert "A body without `unread` is not checked for it." in " ".join(section.split())
