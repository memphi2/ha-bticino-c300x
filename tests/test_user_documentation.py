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


# The repository of each project, by its owner: scripts/check_repo.py keeps
# the full name of fquinto's project out of code.
SSH_PROJECTS = {
    "fquinto": "(C300X `1.7.x`)",
    "davemajor/c300x-root": "(C300X `2.0.2` and `3.0.6`)",
    "daniel-sc/bticino-c100x-firmware-tools": "(C100X `1.5.8`)",
}


def test_quickstart_requirements_name_the_three_ssh_projects_and_a_clean_firmware():
    requirements = " ".join(section("quickstart.md", "Requirements").split("\n### ", 1)[0].split())
    for phrase in ("The integration cannot root a stock station.",
                   "This project provides no firmware images", "rooting instructions",
                   "at your own risk and without warranty", "flashing can brick the station",
                   "The integration assumes a clean firmware: enable only SSH, no camera, MQTT "
                   "or other extras."):
        assert phrase in requirements, phrase
    # Exactly these three projects, each a repository front page with its
    # station and firmware; the C100X line links this project's own test issue.
    links = [link for link in re.findall(r"\]\((https?://[^)]+)\)", requirements)
             if "/ha-bticino-c300x/" not in link]
    assert len(links) == len(SSH_PROJECTS)
    for link, (project, scope) in zip(links, SSH_PROJECTS.items(), strict=True):
        assert re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+", link), link
        assert link.startswith(f"https://github.com/{project}"), link
        assert f"]({link}) {scope}" in requirements, scope


def test_no_separate_rooting_page_and_no_link_to_one():
    assert not (DOCS / "root-access.md").exists()
    texts = [path for path in ROOT.rglob("*.md")
             if not {".git", ".venv", "node_modules"} & set(path.relative_to(ROOT).parts)]
    assert [path for path in texts if "root-access.md" in path.read_text(encoding="utf-8")] == []
    # Only the quick start requirements name the projects; README and the C100X
    # notes send the reader there.
    for document in (ROOT / "README.md", DOCS / "c100x-experimental.md"):
        text = document.read_text(encoding="utf-8")
        assert "quickstart.md#requirements)" in text
        assert not any(f"github.com/{project}" in text for project in SSH_PROJECTS), document.name


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


_C_KEYWORDS = {"if", "for", "while", "switch", "return", "sizeof"}
_ERROR_MEMBER = re.compile(r'\\"error\\"\s*:\s*\\"((?:[^"\\]|\\[^"])*)\\"')
_CODE = re.compile(r"[a-z0-9_]+")
_FORMAT = re.compile(r"%[-+ #0]*\d*(?:\.\d+)?(?:hh|h|ll|l|z|j|t)?[a-zA-Z]")
# Calls that get a client socket without answering it.
_NO_ANSWER = {"close_agent_socket": "closes the socket and sends nothing"}


def _c_calls(text):
    """``(callee, arguments)`` of each call in the body of the C function ``text``."""
    blank = _c_blank(text)
    body = blank.index("{")
    for call in re.finditer(r"\b(\w+)\s*\(", blank[body:]):
        if call[1] not in _C_KEYWORDS:
            yield call[1], _c_args(text, body + call.end() - 1)[0]


def _c_params(text):
    """The parameter names of the C function ``text``."""
    params, _ = _c_args(text, text.index("("))
    return [re.search(r"(\w+)\s*(?:\[[^]]*\])?$", param)[1] for param in params if param not in ("", "void")]


def _c_literals(expression):
    """The string literal ``expression`` is, or the two of ``cond ? "a" : "b"``; None for anything else."""
    blank = _c_blank(expression)
    if re.fullmatch(r"[^?:]+\?[\s]*:[\s]*", blank):
        question = blank.index("?")
        colon = blank.index(":", question)
        sides = [expression[question + 1:colon], expression[colon + 1:]]
    elif blank.strip():
        return None
    else:
        sides = [expression]
    return ["".join(re.findall(r'"((?:[^"\\]|\\.)*)"', side)) for side in sides]


def _client_answers(functions, roots, resolved=None, ignore=None):
    """``(status, code)`` of each error answer a client socket gets, and the ``resolved`` helpers met.

    ``roots`` holds ``(function, socket expression)`` pairs. A call that hands the socket to a function
    of ``functions`` is followed with its arguments bound to that function's parameters. Any other call
    that gets the socket answers the client, unless ``_NO_ANSWER`` or ``ignore`` names it with a reason.
    The body of an answer, its last argument followed back through the callers, must be a string literal
    (or a ``?:`` of two), a buffer that an ``snprintf`` of the function owning it fills, or a call to a
    ``resolved`` helper whose codes the caller reads in another way. A code is the
    ``\\"error\\":\\"<code>\\"`` member of that body, or the literal given for the member's ``%s``; its
    status is the HTTP status among the other arguments. Anything else fails, so no answer goes unread.
    """
    resolved, ignore = resolved or {}, {**_NO_ANSWER, **(ignore or {})}
    answers, helpers = set(), set()

    def bound(expression, frame):
        return frame[1].get(expression, (expression, frame))

    def codes_of(literals, where):
        for code in literals:
            assert _CODE.fullmatch(code), f"{where}: the error code {code!r} is not [a-z0-9_]+"
        return literals

    def body_codes(expression, frame, where):
        expression, frame = bound(expression, frame)
        literals = _c_literals(expression)
        if literals is not None:
            return codes_of([code for literal in literals for code in _ERROR_MEMBER.findall(literal)], where)
        fills = [args for callee, args in _c_calls(functions[frame[0]]) if callee == "snprintf" and args[0] == expression]
        callee = re.match(r"(\w+)\s*\(", expression)
        if callee and callee[1] in resolved:
            helpers.add(callee[1])
            return []
        assert fills, f"{where}: the body {expression!r} is neither a literal nor a buffer built in {frame[0]}"
        codes = []
        for args in fills:
            formats = _c_literals(args[2])
            assert formats is not None and len(formats) == 1, f"{where}: the format of {expression!r} is not a literal"
            for member in _ERROR_MEMBER.finditer(formats[0]):
                if member[1] != "%s":
                    codes += codes_of([member[1]], where)
                    continue
                argument = args[3 + len(_FORMAT.findall(formats[0][:member.start(1)].replace("%%", "")))]
                argument, owner = bound(argument, frame)
                literals = _c_literals(argument)
                assert literals is not None, f"{where}: the error code {argument!r} in {owner[0]} is not a literal"
                codes += codes_of(literals, where)
        return codes

    def visit(name, fd, bindings, depth):
        assert name in functions, f"no C function {name}"
        assert depth < 16, f"{name}: the client socket is handed on too deeply"
        frame = (name, bindings)
        for callee, args in _c_calls(functions[name]):
            if fd not in args:
                continue
            if callee in functions:
                params = _c_params(functions[callee])
                visit(callee, params[args.index(fd)], {p: bound(a, frame) for p, a in zip(params, args, strict=True)}, depth + 1)
                continue
            if callee in ignore:
                continue
            where = f"{name}: {callee}({', '.join(args)})"
            codes = body_codes(args[-1], frame, where)
            if not codes:
                continue
            others = [bound(arg, frame)[0] for index, arg in enumerate(args[:-1]) if index != args.index(fd)]
            statuses = [int(status) for arg in others for status in re.findall(r"\b[1-5]\d\d\b", _c_blank(arg))]
            assert len(statuses) in (1, len(codes)), f"{where}: no literal HTTP status for {codes}"
            answers.update(zip(statuses * len(codes) if len(statuses) == 1 else statuses, codes, strict=True))

    for name, fd in roots:
        visit(name, fd, {}, 0)
    return answers, helpers


def _c_blank(text):
    """``text`` with its string and character literals and comments turned into spaces, at the same length."""
    blanked, index = [], 0
    while index < len(text):
        end = _c_skip(text, index)
        blanked.append(" " * (end - index) if end != index else text[index])
        index = max(end, index + 1)
    return "".join(blanked)


def _api_error_rows(heading):
    """``(status, code)`` of each row of the error table in the API.md section after ``heading``."""
    section = (ROOT / "native_agent/API.md").read_text().split(heading, 1)[1].split("\n### ", 1)[0]
    table = section.split("\nErrors:\n", 1)[1].strip().split("\n\n", 1)[0].splitlines()
    assert table[:2] == ["| Status | `error` | Meaning |", "| --- | --- | --- |"], heading
    rows = set()
    for line in table[2:]:
        row = re.match(r"\|\s*`?(\d{3})`?\s*\|\s*`?([a-z0-9_]+)`?\s*\|", line)
        assert row, f"unreadable error row after {heading}: {line}"
        rows.add((int(row[1]), row[2]))
    return rows


def test_the_api_lists_every_error_the_agent_update_answers_with():
    # The handler refuses a request itself, also through the send_* helpers it
    # hands its client socket to, before the install starts.
    functions = _c_functions((ROOT / "native_agent/src/http.c").read_text())
    replies, helpers = _client_answers(functions, [("handle_agent_update_apply", "client_fd")], resolved={
        "agent_update_error_json": "a failed install: the codes of its enum switch, with the status "
                                   "agent_update_error_status picks, are added below",
    })
    assert helpers == {"agent_update_error_json"}
    assert (403, "maintenance_unauthorized") in replies
    # A failed install answers agent_update_error_json(error) with the status
    # agent_update_error_status(error) picks for the same error.
    handler = functions["handle_agent_update_apply"]
    assert "agent_update_error_status(summary.error)" in handler
    assert "agent_update_error_json(summary.error)" in handler
    update = _c_functions((ROOT / "native_agent/src/agent_update.c").read_text())
    text = update["agent_update_error_json"]
    returns = re.findall(r"\breturn\b([^;]*);", _c_blank(text))
    assert returns and not any(value.strip() for value in returns), "agent_update_error_json returns a non-literal"
    install = set(_ERROR_MEMBER.findall(text))
    cases = dict(re.findall(r'(?:case (\w+)|default):\s*return "(?:[^"\\]|\\.)*?\\"error\\"\s*:\s*\\"([a-z0-9_]+)\\"',
                            text))
    assert set(cases.values()) == install
    special, status, other = re.search(r"return error == (\w+) \? (\d{3}) : (\d{3});",
                                       update["agent_update_error_status"]).groups()
    replies |= {(int(status) if error == special else int(other), code) for error, code in cases.items()}
    assert (409, "update_root_already_writable") in replies
    assert replies == _api_error_rows("`POST /api/v1/maintenance/update/apply`")
    # read_bounded_text_file also fails for a file that is empty or holds only line breaks.
    api = (ROOT / "native_agent/API.md").read_text()
    row = api.split("| `400` | `update_manifest_missing` |", 1)[1].split("\n", 1)[0]
    assert "missing, empty or only line breaks, unreadable or 8 KiB or larger" in row


def test_the_label_write_is_documented_as_the_qml_write_job_it_is():
    """The label apply/restore runs with the QML write deadline and grace
    period; no part of the developer texts may still call it synchronous."""

    label = (ROOT / "native_agent/src/device_user_label.c").read_text()
    start = label.split("int c300x_label_job_start(", 1)[1].split("\n}", 1)[0]
    assert "C300X_QML_WRITE_TIMEOUT_MS" in start and "C300X_QML_WRITE_TERM_GRACE_MS" in start
    api = " ".join((ROOT / "native_agent/API.md").read_text().split())
    architecture = " ".join((ROOT / "docs/dev/architecture.md").read_text().split())
    for stale in (
        "label apply/restore are **synchronous**", "without an execution deadline",
        "block HTTP dispatch and graceful shutdown indefinitely",
        "synchronous label transaction", "exit-status-only",
        "| Label apply/restore | none",
    ):
        assert stale not in api and stale not in architecture, stale
    assert "Label apply/restore is not: it is a QML write job" in api
    assert "| Label apply/restore (QML write jobs, see below) | 30 s |" in architecture


def test_every_display_call_follows_the_ui_port_as_the_api_says():
    api = (ROOT / "native_agent/API.md").read_text()
    listeners = api.split("## Listeners", 1)[1].split("\n## ", 1)[0]
    assert "Every display call follows `listen.uiPort`" in listeners
    assert "8090" not in listeners
    # The Display patch writes only the configured port into the pages it
    # generates; a fixed port there would not follow listen.uiPort.
    script = (ROOT / "native_agent/scripts/qml_patch.sh").read_text(encoding="utf-8")
    ports = re.findall(r'127\.0\.0\.1:(\$[a-z_]+|" [a-z_]+ "|\S*)', script)
    assert len(ports) >= 2
    assert set(ports) <= {"$feature_port", "$core_port", '" port "'}, ports
    # Device files keep 8090 only as the libraries' default until a page hands
    # them the configured base URL, and never open a fixed URL.
    adapter = ROOT / "device_qml/c100x"
    sources = [path for path in sorted((ROOT / "device_qml").rglob("*.qml"))
               + sorted((ROOT / "device_qml").rglob("*.js")) if adapter not in path.parents]
    # The C100X adapter reaches the agent on the default port only; its
    # activation refuses another UI port, as the listeners section says.
    assert "The C100X display adapter is the exception" in " ".join(listeners.split())
    activation = (ROOT / "native_agent/src/http_c100x_display_api.c").read_text()
    assert "config->ui_port != 8090" in activation
    assert "c100x_display_ui_port_unsupported" in activation
    defaults = []
    opened = []
    for path in sources:
        text = path.read_text(encoding="utf-8")
        defaults += [(path.name, line) for line in text.splitlines() if "127.0.0.1" in line]
        opened += re.findall(r"\.open\([^,]+,\s*(\S+)", text)
    opened += re.findall(r'\.open\(\\"[A-Z]+\\",\s*(\S+)', script)
    assert sorted(defaults) == [("c300x_ha.js", 'var BASE_URL = "http://127.0.0.1:8090"'),
                                ("c300x_memos.js", 'var BASE_URL = "http://127.0.0.1:8090"')]
    assert len(opened) >= 10
    assert not [first for first in opened if first.startswith(('"', '\\"'))]


def test_the_api_lists_every_error_the_picture_route_answers_with():
    picture = _c_functions((ROOT / "native_agent/src/picture_control.c").read_text())
    source = (ROOT / "native_agent/src/ringer_control.c").read_text()
    ringer = _c_functions(source)
    assert not picture.keys() & ringer.keys()
    # picture_request answers itself or hands the client to the GUI path in
    # ringer_control.c. That path keeps it as control->client_fd and answers
    # it wherever a function there passes that socket on.
    blank = _c_blank(source)
    assert len(re.findall(r"\bclient_fd\b", blank)) == len(re.findall(r"\bcontrol->client_fd\b", blank))
    roots = [("picture_request", "fd")] + [(name, "control->client_fd") for name in ringer]
    replies, helpers = _client_answers(picture | ringer, roots, ignore={
        "apply": "c300x_ringer_control_next sets it only for a ringer ack (completed=), never for a picture command",
    })
    assert not helpers
    ringer_only = {
        "ringer_gui_busy": "gui_request answers it to a ringer command; a picture command gets picture_gui_busy",
        "ringer_not_applied": "the ringer branch of c300x_ringer_control_expire",
        "ringer_gui_timeout": "the ringer branch of c300x_ringer_control_expire",
        "ringer_gui_not_applied": "the completed= branch of c300x_ringer_control_next, which answers "
                                  "the ack of a picture command as stale before",
    }
    assert set(ringer_only) <= {code for _, code in replies}
    replies = {(status, code) for status, code in replies if code not in ringer_only}
    assert {(409, "picture_gui_busy"), (504, "picture_gui_timeout"), (503, "ringer_gui_unavailable")} <= replies
    # handle_client checks every request before any route runs. A picture body
    # that is not a JSON object gets its invalid_json, never invalid_picture_control.
    http = _c_functions((ROOT / "native_agent/src/http.c").read_text())
    client = http["handle_client"]
    checks = client[client.index("if (!parse_request("):client.index("if (kind == LISTENER_API)")]
    assert client.index("if (kind == LISTENER_API)") < client.index("handle_api_request(")
    http["request_checks"] = "static void request_checks(int client_fd)\n{\n" + checks + "}"
    generic, _ = _client_answers(http, [("request_checks", "client_fd")])
    route_unknown = {"bad_request": "the request line or headers do not parse, so no route is known yet"}
    assert set(route_unknown) <= {code for _, code in generic}
    replies |= {(status, code) for status, code in generic if code not in route_unknown}
    assert (400, "invalid_json") in replies
    assert replies == _api_error_rows("### `GET`, `POST /api/v1/video/picture`")
    section = (ROOT / "native_agent/API.md").read_text().split("### `GET`, `POST /api/v1/video/picture`", 1)[1]
    unavailable = section.split("| `picture_controls_unavailable` |", 1)[1].split("\n", 1)[0]
    # picture_reply answers it when the GUI sends malformed values.
    assert "the GUI answered with missing or out-of-range values" in unavailable
    # The tvp5150 driver answers contrast from its cache and ignores I2C write
    # errors, but the write ioctl, the other re-reads and the deadline still
    # make picture_source_execute refuse and roll back a contrast write.
    text = " ".join(section.split("\nErrors:", 1)[0].split())
    assert "Once a TVP5150 contrast write ioctl succeeds, its read-back always matches" in text
    assert "a failed I2C contrast write cannot be detected" in text
    assert "Only brightness and saturation have a genuine read-back there." in text
    assert "A contrast write is still answered as not applied and rolled back when the write ioctl fails" in text
    assert "always confirmed" not in text


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


def test_display_docs_name_the_home_page_button_layouts_as_the_form_does():
    strings = json.loads((ROOT / "custom_components/bticino_c300x/strings.json").read_text())
    label = strings["options"]["step"]["dashboard"]["data"]["dashboard_dynamic_homepage"]
    options = strings["selector"]["dashboard_dynamic_homepage"]["options"]
    display = section("display.md", "Enable the Display Pages")
    row = next(line for line in display.splitlines() if line.startswith(f"| **{label}** |"))
    assert f"**{options['stock']}** (default)" in row
    assert f"**{options['side_by_side']}**" in row
    assert "restarts the display once" in row
    reference = (DOCS / "feature-reference.md").read_text(encoding="utf-8")
    row = next(line for line in reference.splitlines() if line.startswith("| Display > Display and Display patch |"))
    assert label in row
    assert "Changing the home page buttons applies it again and restarts the display once" in row


def test_the_display_docs_name_the_notice_for_an_unknown_display():
    strings = json.loads((ROOT / "custom_components/bticino_c300x/strings.json").read_text())
    title = strings["issues"]["device_display_unsupported"]["title"]
    qt5 = section("display.md", "Enable the Display Pages").split("### Display Patch on Firmware 3.0.6\n", 1)[1]
    assert f"**{title}**" in qt5


def test_picture_control_docs_say_tvp5150_may_need_the_ring_call_path():
    guide = (DOCS / "user-guide.md").read_text(encoding="utf-8")
    guide = guide.split("### Picture Controls\n", 1)[1].split("\n### ", 1)[0]
    readme = next(line for line in (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
                  if line.startswith("| Picture controls |"))
    for text in (guide.replace("\n  ", " "), readme):
        assert "checked offline only" in text
        assert "may only work during a Ring Call" in text


def test_announcement_docs_name_each_stations_own_sound_files():
    announcements = section("user-guide.md", "Speaker Announcements and TTS").replace("\n", " ")
    assert "same sound parts" not in announcements
    assert "each station's own sound files" in announcements


def test_the_qt5_marker_is_named_as_the_trap_for_the_c100x_merge():
    audit = (DOCS / "dev/firmware-3.0.6-display.md").read_text(encoding="utf-8")
    trap = audit.split("## Known Trap: One Marker For Camera And Display\n", 1)[1].split("\n## ", 1)[0]
    for name in ("libQt5Core.so.5", "camera_quality.c", "qml_patch.sh", "C100X"):
        assert name in trap


def changelog_2_10_0() -> str:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    return changelog.split("## v2.10.0 - ", 1)[1].split("\n## ", 1)[0]


def test_the_3_0_6_texts_say_what_ran_on_a_station():
    """Dave ran the overlay on a 3.0.6 station (PR #126); the rest is offline only."""

    texts = {
        "CHANGELOG v2.10.0": changelog_2_10_0(),
        "v2.10.0.md": (ROOT / ".github/release-notes/v2.10.0.md").read_text(encoding="utf-8"),
        "README.md": (ROOT / "README.md").read_text(encoding="utf-8"),
        "SUPPORT.md": (ROOT / "SUPPORT.md").read_text(encoding="utf-8"),
        "display.md": (DOCS / "display.md").read_text(encoding="utf-8"),
        "quickstart.md": (DOCS / "quickstart.md").read_text(encoding="utf-8"),
    }
    for name, text in texts.items():
        flat = " ".join(text.split())
        assert "not yet tested on a device" not in flat, name
        assert "offline only" in flat, name


def test_the_way_out_of_a_restart_loop_removes_the_overlay_before_the_setting():
    """Turning the pages off while the overlay is left writes the resource file back
    (tests/test_qml_patch_qt5_overlay.py); restore-all gives the display back as shipped."""

    agent = "/home/bticino/cfg/extra/c300x-native-agent"
    for name, path in (("display.md", DOCS / "display.md"),
                       ("v2.10.0.md", ROOT / ".github/release-notes/v2.10.0.md")):
        text = path.read_text(encoding="utf-8")
        way_out = " ".join(text.split("keeps restarting", 1)[1].split("\n## ", 1)[0].split())
        rename = way_out.index(f"`mv {agent}/display-qt5.rcc {agent}/display-qt5.rcc.hang`")
        removal = way_out.index(f"`{agent}/qml_patch.sh restore-all`")
        pages_off = way_out.index("turn off **Home Assistant pages on the display**")
        assert rename < removal < pages_off, name
        for control in ("core hook Repair", "**Display patch** switch", "agent update"):
            assert control in way_out[pages_off:], (name, control)


def test_the_quarantine_texts_name_the_controls_that_retry_the_pages():
    """A quarantined overlay is retried by the switch, the core Repair or an update;
    the Display setting sync never retries it (display_patch_sync._differs)."""

    texts = {
        "display.md": (DOCS / "display.md").read_text(encoding="utf-8"),
        "v2.10.0.md": (ROOT / ".github/release-notes/v2.10.0.md").read_text(encoding="utf-8"),
        "CHANGELOG v2.10.0": changelog_2_10_0(),
    }
    for name, text in texts.items():
        flat = " ".join(text.split())
        assert "pplying the Display patch" not in flat, name
        assert "the **Display patch** switch on" in flat, name
        assert "saving the display settings does not" in flat, name
