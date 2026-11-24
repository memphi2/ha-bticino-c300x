"""Stock-settings patch and GUI preference regressions without a device."""

import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

import pytest
from test_qml_patch_script import (
    ORIGINAL_GENERAL_SETTINGS,
    ORIGINAL_SETTINGS,
    ROOT,
    _run_qml_patch,
    _run_qml_patch_raw,
    _write_original_gui,
)

GENERAL = "Components/Settings/GeneralsChoice.qml"
SETTINGS = "Settings.qml"


def test_preferences_production_runtime():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    result = subprocess.run(
        [node, str(ROOT / "tests/qml/display_preferences.cjs")],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("layout", ["1", "0"], ids=["stock", "side_by_side"])
@pytest.mark.parametrize("topic", ["display_bridge.state", "notifications", "missed"])
def test_home_availability_event_refreshes_after_inflight_read(tmp_path, topic, layout):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    _run_qml_patch(
        tmp_path, gui, backup, "apply",
        env_overrides={"C300X_QML_DYNAMIC_HOME_PAGE": layout},
    )
    result = subprocess.run([node, "-e", r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const homeSource = fs.readFileSync(path.join(process.argv[1], 'HomePage.qml'), 'utf8');
const apiSource = fs.readFileSync(path.join(process.argv[1], 'js/c300x_ha.js'), 'utf8')
    .replace(/^\.pragma library\s*/, '');
for (const previous of [false, true]) {
    const requests = [];
    function Request() { this.readyState = 1; }
    Request.prototype.open = function(method, url) { this.url = url; };
    Request.prototype.send = function() { requests.push(this); };
    Request.prototype.finish = function(available) {
        this.readyState = 4;
        this.status = 200;
        this.responseText = JSON.stringify({alarm_configured: available, dashboard_available: available});
        this.onreadystatechange();
    };
    const api = vm.createContext({XMLHttpRequest: Request});
    vm.runInContext(apiSource, api);
    const page = {visible: true, buttonReadGeneration: 0, buttonRetries: 0,
                  alarmButtonVisible: previous, haButtonVisible: previous};
    const buttonRetryTimer = {stop() {}, restart() { assert.fail('obsolete read scheduled retry'); }};
    let unreadRefreshes = 0;
    const home = vm.createContext({page, buttonRetryTimer, HAConfig: api,
        c300xDisplayPreferences: {bridgeProblem: '', bridgeShown: true},
        MemoSync: {syncHomeNotifications(owner) {
            assert.equal(owner, page);
            unreadRefreshes++;
        }},
    });
    for (const name of ['refreshDisplayBridgeButtons', 'refreshMessageNotifications',
                        'handleMessageNotificationEvent']) {
        const body = homeSource.match(new RegExp('^    function ' + name
            + '\\([^)]*\\) \\{[\\s\\S]*?^    \\}', 'm'));
        assert.ok(body, name);
        vm.runInContext(body[0], home);
    }
    // Ordinary simultaneous reads still share the original request.
    home.refreshDisplayBridgeButtons();
    home.refreshDisplayBridgeButtons();
    assert.equal(requests.length, 1);
    home.handleMessageNotificationEvent(process.argv[2] === 'missed'
        ? {topic: 'media.closed', missedRevisions: true} : {topic: process.argv[2]});
    assert.equal(api.forwardQueue.length, 1, 'each availability event invalidates the pre-event read');
    home.handleMessageNotificationEvent({topic: 'notifications'});
    home.handleMessageNotificationEvent({topic: 'display_bridge.state'});
    home.handleMessageNotificationEvent({topic: 'memos'});
    home.handleMessageNotificationEvent({topic: 'answering_machine.messages'});
    assert.equal(unreadRefreshes, 2, 'memo and answering-machine refreshes are preserved');
    assert.equal(requests.length, 1, 'forwarded requests remain serialized');
    // Both initial callers share the boot-time failure. Only the newer,
    // queued post-registration snapshot may change buttons or schedule retries.
    requests[0].readyState = 4;
    requests[0].status = 404;
    requests[0].onreadystatechange();
    assert.equal(requests.length, 2, 'the event must queue a fresh read after the old response');
    assert.ok(requests.every(request => request.url.endsWith('/ui/state')));
    requests[1].finish(!previous);
    assert.equal(page.alarmButtonVisible, !previous);
    assert.equal(page.haButtonVisible, !previous);
    home.handleMessageNotificationEvent(null);
    home.handleMessageNotificationEvent({topic: 'unrelated'});
    assert.equal(requests.length, 2, 'back-to-back availability events share the fresh queued read');
    assert.equal(unreadRefreshes, 2);
    assert.equal(api.forwardActive, null);
    assert.equal(api.forwardQueue.length, 0);
    // Hide while a post-event refresh is queued. A HomePage-only read drops,
    // but a shared caller from another page must still receive its answer.
    home.refreshDisplayBridgeButtons();
    home.handleMessageNotificationEvent({topic: 'notifications'});
    let answered = false;
    if (previous) api.getJsonShared('/ui/state', () => { answered = true; });
    page.visible = false;
    requests[2].finish(false);
    assert.equal(requests.length, previous ? 4 : 3);
    if (previous) { requests[3].finish(true); assert.ok(answered); }
}
""", str(gui), topic], capture_output=True, text=True, check=False, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("layout", ["1", "0"], ids=["stock", "side_by_side"])
def test_home_buttons_qt4_retry_without_navigation(tmp_path, layout):
    from scripts.setup_qt4_runtime import probe_command, runtime_paths

    paths = runtime_paths()
    if not paths:
        pytest.skip("Local firmware Qt 4 runtime not configured")
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    _run_qml_patch(tmp_path, gui, backup, "apply", env_overrides={"C300X_QML_DYNAMIC_HOME_PAGE": layout})
    source = (gui / "HomePage.qml").read_text()
    # Run the generated controls and lifecycle handler on firmware Qt without
    # loading the hardware GUI. Only the forwarded HA request is substituted.
    controls = re.search(r"    property bool alarmButtonVisible:.*?function refreshDisplayBridgeButtons\(\).*?^    }",
                         source, re.S | re.M).group()
    visibility = re.search(r"    onVisibleChanged: \{.*?^    }", source, re.S | re.M).group()
    event_handler = re.search(r"    function handleMessageNotificationEvent\(event\).*?^    }",
                              source, re.S | re.M).group()
    with tempfile.TemporaryDirectory(dir="/var/tmp") as folder:
        qml = Path(folder) / "HomeButtons.qml"
        (qml.parent / "mock.js").write_text("var requests = 0, reply = null\n"
                                            "function homeButtons(cb) { requests++; reply = cb }\n"
                                            "function invalidateSharedRead(path) {}\n")
        qml.write_text('import QtQuick 1.1\nimport "mock.js" as HAConfig\nItem { id: page\n'
                       '    QtObject { id: c300xDisplayPreferences; property string bridgeProblem: ""; property bool bridgeShown: true }\n'
                       + controls + "\n" + visibility + "\n" + event_handler + """
    function respond(a, b, valid) { HAConfig.reply(a, b, valid, valid ? "" : "bridge_unreachable") }
    property string problem: c300xDisplayPreferences.bridgeProblem
    property int starts: 0
    function startMessageNotificationWatch() { starts++ }
    function stopMessageNotificationWatch() {}
    function check(ok) { if (!ok) throw new Error("home recovery failed") }
    Component.onCompleted: {
        // Stock TabView calls aboutToShow before setting visible=true.
        // The first read and watch must start even with no clock loader.
        visible = false
        var beforeShow = HAConfig.requests
        var beforeWatch = starts
        refreshDisplayBridgeButtons()
        check(HAConfig.requests === beforeShow)
        visible = true
        check(HAConfig.requests === beforeShow + 1 && starts === beforeWatch + 1)
        respond(false, false, false)
        check(buttonRetryTimer.running && buttonRetryTimer.interval === 1000)
        // No availability event arrives. Fire the same one-shot as the Qt clock.
        buttonRetryTimer.triggered()
        respond(true, true, true)
        check(HAConfig.requests === beforeShow + 2 && haButtonVisible && alarmButtonVisible && !buttonRetryTimer.running)
        refreshDisplayBridgeButtons()
        respond(false, false, true)
        check(!haButtonVisible && !alarmButtonVisible && !buttonRetryTimer.running)
        refreshDisplayBridgeButtons()
        for (var i = 0; i < 6; i++) {
            respond(false, false, false)
            check(buttonRetryTimer.running && buttonRetryTimer.interval === 1000 * Math.pow(2, i) && problem === "")
            buttonRetryTimer.triggered()
        }
        respond(false, false, false)
        // The quick retries are used up: the mark shows and one slow
        // one-shot keeps asking while the page is visible.
        check(buttonRetryTimer.running && buttonRetryTimer.interval === 300000 && problem === "bridge_unreachable")
        buttonRetryTimer.triggered()
        respond(false, false, false)
        check(buttonRetryTimer.running && buttonRetryTimer.interval === 300000 && problem === "bridge_unreachable")
        var beforeRegistration = HAConfig.requests
        handleMessageNotificationEvent({topic: "display_bridge.state"})
        check(HAConfig.requests === beforeRegistration + 1)
        respond(false, false, false)
        check(buttonRetryTimer.running && buttonRetryTimer.interval === 1000 && problem === "bridge_unreachable")
        buttonRetryTimer.triggered()
        check(HAConfig.requests === beforeRegistration + 2)
        respond(true, true, true)
        check(haButtonVisible && alarmButtonVisible && !buttonRetryTimer.running && problem === "")
        refreshDisplayBridgeButtons()
        respond(false, false, true)
        visible = false
        visible = true
        refreshDisplayBridgeButtons()
        respond(false, false, false)
        check(buttonRetryTimer.running)
        visible = false
        var count = HAConfig.requests
        respond(true, true, true)
        buttonRetryTimer.triggered()
        check(!buttonRetryTimer.running && HAConfig.requests === count && !haButtonVisible)
        console.log("QT4_HOME_BUTTON_RECOVERY_PASS")
    }
}
""")
        result = subprocess.run(probe_command(paths, qml), capture_output=True, text=True, timeout=15, check=True)
    assert "QT4_HOME_BUTTON_RECOVERY_PASS" in result.stdout + result.stderr, result.stdout + result.stderr


@pytest.mark.parametrize("action", ["status", "core-apply", "media-user-label-apply"])
def test_settings_are_untouched_without_optional_display_pages(tmp_path, action):
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    settings = gui / SETTINGS
    settings.chmod(0o640)
    before = (settings.read_bytes(), settings.stat().st_mode, settings.stat().st_mtime_ns)
    result = _run_qml_patch(tmp_path, gui, backup, action)
    assert result["patched"] is False
    assert (settings.read_bytes(), settings.stat().st_mode, settings.stat().st_mtime_ns) == before
    assert not (backup / SETTINGS).exists()
    assert "c300xDisplayPreferences" not in (gui / "MainApp.qml").read_text()


def test_disabling_optional_display_restores_settings_but_keeps_media_hooks(tmp_path):
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    _run_qml_patch(tmp_path, gui, backup, "apply")
    assert (gui / GENERAL).read_text() == ORIGINAL_GENERAL_SETTINGS
    assert 'sourceUrl: "C300XSettings.qml"' in (gui / SETTINGS).read_text()
    result = _run_qml_patch(tmp_path, gui, backup, "restore")
    assert result["patched"] is False
    assert result["core_patched"] is True
    assert (gui / SETTINGS).read_text() == ORIGINAL_SETTINGS


HINT_HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const homeSource = fs.readFileSync(path.join(process.argv[1], 'HomePage.qml'), 'utf8');
const apiSource = fs.readFileSync(path.join(process.argv[1], 'js/c300x_ha.js'), 'utf8')
    .replace(/^\.pragma library\s*/, '');
for (const [status, reason] of [[404, 'bridge_not_registered'], [502, 'bridge_unreachable'], [0, 'bridge_unreachable']]) {
    const requests = [];
    function Request() { this.readyState = 1; }
    Request.prototype.open = function(method, url) { this.url = url; };
    Request.prototype.send = function() { requests.push(this); };
    Request.prototype.finish = function(code, body) {
        this.readyState = 4; this.status = code; this.responseText = JSON.stringify(body || {});
        this.onreadystatechange();
    };
    const api = vm.createContext({XMLHttpRequest: Request});
    vm.runInContext(apiSource, api);
    const page = {visible: true, buttonReadGeneration: 0, buttonRetries: 0,
                  alarmButtonVisible: false, haButtonVisible: false, uiBaseUrl: 'http://127.0.0.1:18123'};
    const preferences = {bridgeProblem: '', bridgeShown: true};
    const timer = {interval: 0, starts: [], stop() {}, restart() { this.starts.push(this.interval); }};
    const home = vm.createContext({page, buttonRetryTimer: timer, HAConfig: api,
        c300xDisplayPreferences: preferences, Math});
    const body = homeSource.match(/^    function refreshDisplayBridgeButtons\([^)]*\) \{[\s\S]*?^    \}/m);
    vm.runInContext(body[0], home);
    for (let attempt = 0; attempt < 6; attempt++) {
        home.refreshDisplayBridgeButtons();
        requests.pop().finish(status);
        assert.equal(preferences.bridgeProblem, '', 'no mark during the quick retries of a normal start');
    }
    assert.deepEqual(timer.starts, [1000, 2000, 4000, 8000, 16000, 32000]);
    for (let slow = 0; slow < 2; slow++) {
        home.refreshDisplayBridgeButtons();
        requests.pop().finish(status);
        assert.equal(preferences.bridgeProblem, reason);
        assert.equal(timer.starts.at(-1), 300000, 'slow retry while the mark shows');
    }
    page.visible = false;
    home.refreshDisplayBridgeButtons();
    assert.equal(requests.length, 0, 'a hidden home page does not ask');
    page.visible = true;
    const before = timer.starts.length;
    home.refreshDisplayBridgeButtons();
    requests.pop().finish(200, {alarm_configured: true, dashboard_available: true});
    assert.equal(preferences.bridgeProblem, '', 'the next valid read removes the mark');
    assert.equal(page.alarmButtonVisible && page.haButtonVisible, true);
    assert.equal(page.buttonRetries, 0);
    assert.equal(timer.starts.length, before, 'no polling once Home Assistant answers');
    assert.equal(preferences.bridgeShown, true, 'the plain house stays while Home Assistant answers');
    home.refreshDisplayBridgeButtons();
    requests.pop().finish(200, {device_ui_enabled: false});
    assert.equal(preferences.bridgeShown, false, 'no symbol while the display pages are switched off');
    home.refreshDisplayBridgeButtons();
    requests.pop().finish(200, {device_ui_enabled: true});
    assert.equal(preferences.bridgeShown, true);
    const seen = [];
    api.homeButtons(function() { seen.push(Array.prototype.slice.call(arguments)); }, page);
    requests.pop().finish(200, {});
    api.homeButtons(function() { seen.push(Array.prototype.slice.call(arguments)); }, page);
    requests.pop().finish(status);
    assert.deepEqual(seen, [[false, false, true, '', true], [false, false, false, reason, true]],
        'three-argument callers keep their contract; reason and page switch are appended');
}
"""


@pytest.mark.parametrize("layout", ["1", "0"], ids=["stock", "side_by_side"])
def test_home_page_shows_the_home_assistant_connection(tmp_path, layout):
    """Issue #119: the home page gave up silently and the buttons stayed hidden.

    A house symbol beside the power button shows the connection. After the
    six quick retries it gets an amber mark, the page keeps asking every five
    minutes while it is visible, and the next valid read removes the mark. A
    tap opens the Integration settings tab, which names the reason.
    """

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    env = {"C300X_QML_DYNAMIC_HOME_PAGE": layout}
    _run_qml_patch(tmp_path, gui, backup, "apply", env_overrides=env)
    home = (gui / "HomePage.qml").read_text()
    start = home.index("    Image {\n        id: c300xBridgeHint")
    hint = home[start:home.index("\n    }\n", start)]
    # One element carries the symbol: the vendor's own house icon, always
    # shown; only the amber mark depends on the state.
    assert (
        "        visible: c300xDisplayPreferences.bridgeShown\n"
        '        source: "images/call/icon_call-home.svg"\n'
        "        anchors.verticalCenter: header.verticalCenter\n"
        # Beside the power button, or beside the vendor's own warning when that shows.
        "        x: (datecert.visible ? datecert.x + datecert.width : off.x + off.width) + page.width / 100 * 2\n"
        "        Rectangle {\n"
        '            visible: c300xDisplayPreferences.bridgeProblem !== ""\n'
    ) in hint
    assert hint.count("source:") == 1 and "data:" not in home
    # The tap area stays clear of the power button (16 px away at 800 px).
    assert "            anchors.fill: parent\n            anchors.margins: -6\n" in hint
    assert (
        "            onPressed: {\n"
        "                c300xDisplayPreferences.openIntegration = true\n"
        "                tabView.activateTab(settingsPage)\n"
    ) in hint
    assert "repeat: true" not in home[home.index("id: buttonRetryTimer"):home.index("function refreshDisplayBridgeButtons")]
    main_app = (gui / "MainApp.qml").read_text()
    assert '        property string bridgeProblem: ""\n        property bool bridgeShown: true\n' in main_app
    assert "        property bool openIntegration: false\n" in main_app
    settings = (gui / SETTINGS).read_text()
    assert (
        "    function aboutToShow() {\n"
        '        if (typeof c300xDisplayPreferences !== "undefined" && c300xDisplayPreferences.openIntegration) {\n'
        "            c300xDisplayPreferences.openIntegration = false\n"
        "            c300xIntegrationButton.checked = true\n"
        "        }\n"
    ) in settings
    assert "        id: c300xIntegrationButton\n        property Item tab: c300xSettings\n" in settings
    result = subprocess.run([node, "-e", HINT_HARNESS, str(gui)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    broken = home.replace("id: c300xBridgeHint", "id: otherHint")
    (gui / "HomePage.qml").write_text(broken)
    assert _run_qml_patch(tmp_path, gui, backup, "status", env_overrides=env)["state"] == "partial"
    assert _run_qml_patch(tmp_path, gui, backup, "apply", env_overrides=env)["state"] == "patched"
    assert (gui / "HomePage.qml").read_text() == home


TAB_HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const root = process.argv[1];
const qml = fs.readFileSync(root + '/device_qml/C300XSettings.qml', 'utf8');
const texts = vm.createContext({});
vm.runInContext(fs.readFileSync(root + '/device_qml/js/c300x_i18n.js', 'utf8').replace(/^\.pragma library\s*/, ''), texts);
function tab(language) {
    const calls = {status: [], details: [], setting: []};
    const preferences = {bridgeProblem: ''};
    const panel = vm.createContext({c300xDisplayPreferences: preferences, visible: true, pending: '', saving: false,
        answered: false, problem: '', bridgeOff: false, address: '', contact: '', agentVersion: '', firmwareVersion: '', integrationVersion: '',
        instanceName: '', keepOpen: false, tabNavigation: false, status: '', Math,
        label(key) { return texts.text(language || 'de', key); },
        Bridge: {
            stationStatus(callback, owner) { calls.status.push({callback, owner}); },
            bridgeDetails(callback, owner) { calls.details.push({callback, owner}); },
            displaySetting(key, value, callback, owner) { calls.setting.push({key, value, callback, owner}); },
        }});
    panel.panel = panel;
    Object.defineProperty(panel, 'reachable', {get() { return panel.answered && panel.problem === ''; }});
    vm.runInContext(qml.slice(qml.indexOf('    function contactText'), qml.indexOf('    function aboutToShow')), panel);
    return {panel, calls, preferences};
}
"""


def _run_tab_harness(body: str) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    result = subprocess.run([node, "-e", TAB_HARNESS + body, str(ROOT)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_integration_tab_shows_the_connection_status():
    """The block answers "does it work, and with which Home Assistant" on the station.

    The address, the last contact and the versions of agent and firmware come
    from the agent, so they also show while Home Assistant cannot be reached.
    """

    _run_tab_harness(r"""
let {panel, calls, preferences} = tab('de');
panel.readStatus();
assert.deepEqual([calls.status.length, calls.details.length], [1, 1]);
assert.equal(typeof calls.details[0].owner.readStatus, 'function', 'the panel owns the reads, so a hidden tab drops them');
assert.equal(panel.reachable, false, 'not called reachable before Home Assistant answered');
calls.status[0].callback({ok: true, version: '2.9.2', firmware: '1.7.19', registered: true,
    home_assistant: 'http://192.0.2.10:8123', last_contact_age: 120});
calls.details[0].callback({ok: true, integration_version: '2.9.2', instance_name: 'Zuhause',
    preventReturnToHomepage: true, navigation: 'tabs'}, '');
assert.deepEqual([panel.reachable, panel.address, panel.contact, panel.agentVersion, panel.firmwareVersion,
    panel.integrationVersion, panel.instanceName, panel.keepOpen, panel.tabNavigation],
    [true, 'http://192.0.2.10:8123', 'vor 2 Min', '2.9.2', '1.7.19', '2.9.2', 'Zuhause', true, true]);
// The bridge answer is itself a contact, so the age is read again after it.
assert.equal(calls.status.length, 2, 'the local status is read again after the bridge answer');
calls.status[1].callback({ok: true, version: '2.9.2', firmware: '1.7.19', registered: true,
    home_assistant: 'http://192.0.2.10:8123', last_contact_age: 0});
assert.equal(panel.contact, 'gerade eben');
// Not reachable: the tab shows its own reason, the local facts stay.
panel.readStatus();
calls.status.at(-1).callback({ok: true, version: '2.9.2', firmware: '1.7.19', registered: true,
    home_assistant: 'https://ha.example.org', last_contact_age: 10800});
calls.details[1].callback(null, 'bridge_unreachable');
calls.status.at(-1).callback({ok: true, version: '2.9.2', firmware: '1.7.19', registered: true,
    home_assistant: 'https://ha.example.org', last_contact_age: 10800});
assert.deepEqual([panel.reachable, panel.problem, panel.address, panel.contact],
    [false, 'bridge_unreachable', 'https://ha.example.org', 'vor 3 Std']);
assert.equal(preferences.bridgeProblem, '', 'the mark on the home page follows the home page reads alone');
assert.ok(!qml.includes('c300xDisplayPreferences.bridgeProblem'));
panel.readStatus();
calls.details[2].callback({}, '');
assert.deepEqual([panel.reachable, panel.problem], [true, ''], 'the next answer clears the reason');
// The agent sends scheme, host and port only. Anything else is not shown at all.
for (const bad of ['http://192.0.2.10:8123/api/webhook/abc', 'http://ha.local:8123?token=x', 'http://ha.local#x',
                   'http://user:pw@ha.local:8123', 'ftp://ha.local', 'ha.local:8123', '', null, 7, 'http://ha.local/ ']) {
    panel.readStatus();
    calls.status.at(-1).callback({ok: true, home_assistant: bad, last_contact_age: null});
    assert.equal(panel.address, '', String(bad));
}
panel.readStatus();
calls.status.at(-1).callback(null);
assert.deepEqual([panel.address, panel.contact, panel.agentVersion], ['', '', ''], 'an agent that does not answer shows dashes');
for (const [age, text] of [[null, 'nie seit Start'], [undefined, 'nie seit Start'], [0, 'gerade eben'], [89, 'gerade eben'],
        [90, 'vor 2 Min'], [5399, 'vor 90 Min'], [5400, 'vor 2 Std'], [172799, 'vor 48 Std'], [172800, 'vor 2 Tagen'],
        [864000, 'vor 10 Tagen']]) {
    assert.equal(panel.contactText(age), text, String(age));
}
// The agent answers 404 for "never registered" and for "switched off"; its local status tells them apart.
{
    const {panel, calls} = tab('en');
    panel.readStatus();
    calls.status[0].callback({ok: true, registered: false, disabled: true, home_assistant: '', last_contact_age: 30});
    calls.details[0].callback(null, 'bridge_not_registered');
    assert.equal(texts.text('en', panel.reasonKey()), 'The station pages are switched off in Home Assistant.');
    calls.status[1].callback({ok: true, registered: false, disabled: false, home_assistant: '', last_contact_age: null});
    assert.equal(panel.reasonKey(), 'bridge_not_registered');
    panel.bridgeOff = true; panel.problem = 'bridge_unreachable';
    assert.equal(panel.reasonKey(), 'bridge_unreachable');
    assert.ok(qml.includes('text: panel.problem ? panel.label(panel.reasonKey()) : ""'));
    assert.deepEqual(['de', 'it', 'fr'].map(language => texts.text(language, 'bridge_disabled')), [
        'Die Stationsseiten sind in Home Assistant ausgeschaltet.',
        'Le pagine della stazione sono disattivate in Home Assistant.',
        'Les pages de la station sont désactivées dans Home Assistant.']);
}
assert.equal(tab('en').panel.contactText(600), '10 min ago');
assert.equal(tab('it').panel.contactText(7200), '2 h fa');
assert.equal(tab('fr').panel.contactText(null), 'jamais depuis le démarrage');
for (const key of ['status_ok', 'status_down', 'status_checking', 'status_contact', 'contact_never',
        'contact_now', 'contact_min', 'contact_hours', 'contact_days', 'section_display', 'section_station',
        'bridge_unreachable', 'bridge_not_registered', 'bridge_disabled']) {
    for (const language of ['de', 'en', 'it', 'fr']) assert.notEqual(texts.text(language, key), key, language + ' ' + key);
}
assert.match(texts.text('en', 'bridge_unreachable'), /http, or https with a trusted certificate/);
// One block: state, reason, and no smaller than the vendor's own settings text (18 px).
assert.match(qml, /text: panel\.problem \? panel\.label\(panel\.reasonKey\(\)\) : ""/);
assert.match(qml, /onVisibleChanged: if \(visible\) readStatus\(\); else hidden\(\)/);
const sizes = [...qml.matchAll(/font\.pixelSize: (\d+)/g)].map(match => Number(match[1]));
assert.ok(sizes.length >= 5 && Math.min(...sizes) >= 18, String(sizes));
""")


def test_integration_tab_changes_the_two_display_settings_through_home_assistant():
    _run_tab_harness(r"""
const {panel, calls, preferences} = tab('de');
panel.setDisplay('dashboard_navigation', 'tabs');
assert.equal(calls.setting.length, 0, 'nothing is sent, and nothing kept locally, while Home Assistant is not reachable');
panel.answered = true;
panel.problem = 'bridge_unreachable';
panel.setDisplay('dashboard_navigation', 'tabs');
assert.equal(calls.setting.length, 0);
panel.problem = '';
panel.setDisplay('dashboard_navigation', 'tabs');
assert.deepEqual([calls.setting[0].key, calls.setting[0].value, panel.saving, panel.tabNavigation],
    ['dashboard_navigation', 'tabs', true, false], 'the switch waits for the stored value');
panel.setDisplay('dashboard_prevent_return', 'on');
assert.equal(calls.setting.length, 1, 'one write at a time');
// The answer is what Home Assistant stored, not what was asked for.
calls.setting[0].callback({ok: true, preventReturnToHomepage: true, navigation: 'pager'});
assert.deepEqual([panel.saving, panel.tabNavigation, panel.keepOpen, panel.status], [false, false, true, '']);
panel.setDisplay('dashboard_prevent_return', 'off');
calls.setting[1].callback(null);
assert.deepEqual([panel.saving, panel.keepOpen, panel.status], [false, true, 'display_settings_error'],
    'a failed write keeps the confirmed value and says so');
panel.pending = 'reboot';
panel.setDisplay('dashboard_prevent_return', 'off');
assert.equal(calls.setting.length, 2, 'not while a confirmation is open');
assert.match(qml, /panel\.setDisplay\("dashboard_prevent_return", checked \? "off" : "on"\)/);
assert.match(qml, /panel\.setDisplay\("dashboard_navigation", checked \? "pager" : "tabs"\)/);
assert.ok(qml.includes('return (row === 2 || row === 3) && reachable && !saving'), 'both switches rest while unreachable');
assert.deepEqual(['setting_standby', 'setting_nav_tabs', 'setting_nav_pager', 'setting_nav'].map(key => texts.text('de', key)),
    ['Seite im Standby offen lassen', 'Seitenwechsel: Favoritenleiste', 'Seitenwechsel: Pfeile', 'Seitenwechsel']);
for (const key of ['setting_standby', 'setting_nav_tabs', 'setting_nav_pager', 'setting_nav']) {
    for (const language of ['en', 'it', 'fr']) assert.notEqual(texts.text(language, key), key);
}
// The request helpers: a local read, the reason of a failed read, and one fixed command path.
const requests = [];
function Request() { this.readyState = 1; }
Request.prototype.open = function(method, url) { this.method = method; this.url = url; };
Request.prototype.send = function() { requests.push(this); };
Request.prototype.finish = function(code, body) {
    this.readyState = 4; this.status = code; this.responseText = JSON.stringify(body || {});
    this.onreadystatechange();
};
const api = vm.createContext({XMLHttpRequest: Request});
vm.runInContext(fs.readFileSync(root + '/device_qml/js/c300x_ha.js', 'utf8').replace(/^\.pragma library\s*/, ''), api);
const owner = {visible: true, uiBaseUrl: 'http://127.0.0.1:18123'};
const seen = [];
api.stationStatus(data => seen.push(data), owner);
assert.equal(requests[0].url, 'http://127.0.0.1:18123/ui/status');
requests.shift().finish(200, {ok: true, version: '2.9.2'});
api.stationStatus(data => seen.push(data), owner);
requests.shift().finish(500);
assert.equal(JSON.stringify(seen), JSON.stringify([{ok: true, version: '2.9.2'}, null]));
const details = [];
for (const [code, reason] of [[200, ''], [404, 'bridge_not_registered'], [502, 'bridge_unreachable'], [0, 'bridge_unreachable']]) {
    api.bridgeDetails((data, why) => details.push([data === null, why]), owner);
    assert.equal(requests[0].url, 'http://127.0.0.1:18123/ui/state');
    requests.shift().finish(code, {ok: code === 200});
    assert.deepEqual(details.at(-1), [code !== 200, reason]);
}
const stored = [];
api.displaySetting('dashboard_navigation', 'tabs', data => stored.push(data), owner);
assert.equal(requests[0].url,
    'http://127.0.0.1:18123/homeassistant?domain=c300x&service=setting&entities=dashboard_navigation&option=tabs');
requests.shift().finish(200, {ok: true, navigation: 'tabs'});
api.displaySetting('dashboard_navigation', 'tabs', data => stored.push(data), owner);
requests.shift().finish(200, {ok: false, error: 'invalid_display_setting'});
api.displaySetting('dashboard_navigation', 'tabs', data => stored.push(data), owner);
requests.shift().finish(400, {ok: false});
assert.equal(JSON.stringify(stored), JSON.stringify([{ok: true, navigation: 'tabs'}, null, null]));
""")


def test_station_settings_tab_is_named_integration(tmp_path):
    """The tab holds integration upkeep, not Home Assistant content.

    Only the settings tab is renamed; the home page button that opens the
    Home Assistant page keeps its name. The display texts carry no accents,
    so one word serves German, English and French.
    """

    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    _run_qml_patch(tmp_path, gui, backup, "apply")
    settings = (gui / SETTINGS).read_text()
    assert (
        '            description: (trsl.language === "it" ? "Integrazione" : "Integration") + trsl.empty\n'
        in settings
    )
    assert "Home Assistant" not in settings
    assert 'text: "Home Assistant"' in (gui / "HomePage.qml").read_text()


def test_settings_backup_restore_and_unchanged_reapply(tmp_path):
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    settings = gui / SETTINGS
    settings.chmod(0o640)
    original = settings.read_bytes()
    original_time = settings.stat().st_mtime_ns
    _run_qml_patch(tmp_path, gui, backup, "apply")
    assert (backup / SETTINGS).read_bytes() == original
    assert (backup / SETTINGS).stat().st_mtime_ns == original_time
    assert stat.S_IMODE((backup / SETTINGS).stat().st_mode) == 0o640
    patched = settings.read_text()
    assert patched.count("id: c300xSettings") == 1
    assert "anchors.top: column.bottom" in patched
    assert "property Item tab: c300xSettings" in patched
    assert (gui / GENERAL).read_text() == ORIGINAL_GENERAL_SETTINGS
    assert "Qt.createQmlObject" not in (gui / "MainApp.qml").read_text()
    assert "property variant request:" not in (gui / "MainApp.qml").read_text()
    assert _run_qml_patch(tmp_path, gui, backup, "apply")["changed_files"] == 0
    assert (backup / SETTINGS).read_bytes() == original
    _run_qml_patch(tmp_path, gui, backup, "restore-all")
    assert settings.read_bytes() == original
    assert stat.S_IMODE(settings.stat().st_mode) == 0o640
    assert settings.stat().st_mtime_ns == original_time


@pytest.mark.parametrize("broken", [
    "spacing: 6", "    ExclusiveGroup {", "configurationChoice", 'QT_TR_NOOP("Configuration")',
])
def test_unknown_settings_layout_aborts_before_touching_gui(tmp_path, broken):
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    (gui / SETTINGS).write_text(ORIGINAL_SETTINGS.replace(broken, "// changed vendor layout"))
    before = {p.relative_to(gui): p.read_bytes() for p in gui.rglob("*") if p.is_file()}
    assert _run_qml_patch_raw(tmp_path, gui, backup, "apply").returncode != 0
    assert {p.relative_to(gui): p.read_bytes() for p in gui.rglob("*") if p.is_file()} == before


def test_legacy_feedback_row_is_removed_on_upgrade(tmp_path):
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    (backup / GENERAL).parent.mkdir(parents=True)
    (backup / GENERAL).write_text(ORIGINAL_GENERAL_SETTINGS)
    (gui / GENERAL).write_text(ORIGINAL_GENERAL_SETTINGS + "// c300xFeedbackSetting")
    _run_qml_patch(tmp_path, gui, backup, "apply")
    assert (gui / GENERAL).read_text() == ORIGINAL_GENERAL_SETTINGS
    assert (backup / GENERAL).read_text() == ORIGINAL_GENERAL_SETTINGS


def test_missing_original_settings_backup_blocks_restore_and_rebackup(tmp_path):
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    _run_qml_patch(tmp_path, gui, backup, "apply")
    (backup / SETTINGS).unlink()
    before = (gui / SETTINGS).read_bytes()
    for action in ("apply", "restore", "restore-all"):
        result = _run_qml_patch_raw(tmp_path, gui, backup, action)
        assert result.returncode != 0
        assert "Settings.qml" in result.stderr
        assert (gui / SETTINGS).read_bytes() == before
        assert not (backup / SETTINGS).exists()


def test_older_feature_patch_without_settings_backup_remains_restorable(tmp_path):
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    _run_qml_patch(tmp_path, gui, backup, "apply")
    (gui / SETTINGS).write_bytes((backup / SETTINGS).read_bytes())
    (backup / SETTINGS).unlink()
    _run_qml_patch(tmp_path, gui, backup, "restore-all")
    assert (gui / SETTINGS).read_text() == ORIGINAL_SETTINGS


def test_local_maintenance_transport():
    subprocess.run(["node", str(ROOT / "tests/qml/maintenance.cjs")], check=True)


def test_station_port_from_agent_or_direct_install(tmp_path):
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    agent = tmp_path / "agent"
    agent.write_text(
        '#!/bin/sh\n[ "$3" != "--diagnose-startup" ] || echo \'    "ui_port": 18123,\'\n'
    )
    agent.chmod(0o700)
    (tmp_path / "config.json").write_text("{}")
    env = {"C300X_QML_AGENT_BIN": str(agent)}
    for port in (18123, 65535):
        if port == 65535:
            env["C300X_QML_UI_PORT"] = str(port)
        _run_qml_patch(tmp_path, gui, backup, "apply", env_overrides=env)
        assert f'property string uiBaseUrl: "http://127.0.0.1:{port}"' in (gui / "MainApp.qml").read_text()
    previous = (gui / "MainApp.qml").read_bytes()
    for port in ("0", "65536", "1/path"):
        env["C300X_QML_UI_PORT"] = port
        assert _run_qml_patch_raw(tmp_path, gui, backup, "apply", env_overrides=env).returncode != 0
        assert (gui / "MainApp.qml").read_bytes() == previous


def test_truncated_menu_backup_blocks_uninstall(tmp_path):
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    _run_qml_patch(tmp_path, gui, backup, "apply")
    (backup / SETTINGS).write_text("import QtQuick 1.1\n")
    assert not _run_qml_patch(tmp_path, gui, backup, "status")["backup_available"]
    assert _run_qml_patch_raw(tmp_path, gui, backup, "restore-all").returncode != 0
    assert "c300xSettings" in (gui / SETTINGS).read_text()


@pytest.mark.parametrize("target", ["Settings.qml", "js/c300x_maintenance.js"])
def test_settings_restore_rejects_untrusted_backup(tmp_path, target):
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    _run_qml_patch(tmp_path, gui, backup, "apply")
    victim = tmp_path / "external"
    victim.write_bytes(b"unchanged")
    link = backup / target
    link.parent.mkdir(exist_ok=True)
    link.unlink(missing_ok=True)
    link.symlink_to(victim)
    for action in ("apply", "restore", "restore-all"):
        assert _run_qml_patch_raw(tmp_path, gui, backup, action).returncode != 0
        assert victim.read_bytes() == b"unchanged"
        assert "c300xSettings" in (gui / SETTINGS).read_text()


def test_integration_tab_rows_are_not_rebuilt_when_a_value_changes():
    """A Repeater over a JavaScript array with bindings in it builds all rows anew.

    On the station's Qt 4.8 a tap on a switch changed "saving" inside the
    array, and every row was destroyed and created again while its own click
    handler still ran. The row count is fixed now and each value is bound
    inside its row.
    """
    source = (ROOT / "device_qml/C300XSettings.qml").read_text(encoding="utf-8")
    models = re.findall(r"\n +model: ([^\n]+)", source)
    assert models == ["5", "6", '["reboot", "remove"]']
    assert "panel." not in "".join(models)
    for name in ("statusKey", "statusValue", "rowText", "rowOn", "rowEnabled"):
        assert f"    function {name}(row) {{" in source and f"panel.{name}(index)" in source
    assert not re.search(r"modelData\.[a-z]\b", source)


def test_integration_tab_status_lines_fit_long_values():
    """Measured in the station font at 18 px: the value column is 260 px wide.

    "https://ha.example.duckdns.org:8123" is 298 px and the three versions in
    one line were 435 px with "2.10.0b1" in a 400 px column, so both were cut.
    The address has the full width and may wrap once; the versions are two rows.
    """
    source = (ROOT / "device_qml/C300XSettings.qml").read_text(encoding="utf-8")
    assert "                model: 5\n" in source
    assert "anchors.leftMargin: index === 1 ? 0 : 140" in source
    assert "wrapMode: index === 1 ? Text.WrapAnywhere : Text.NoWrap" in source
    assert "height: Math.max(23, statusValue.paintedHeight + 2)" in source
    assert 'row === 3 ? "Integration" : row === 4 ? "Agent"' in source
    assert '(agentVersion || "-") + " \\u00b7 Firmware " + (firmwareVersion || "-")' in source
    assert '"Integration " +' not in source
    assert "status_server" not in (ROOT / "device_qml/js/c300x_i18n.js").read_text(encoding="utf-8")


def test_integration_tab_status_block_is_readable_on_a_bright_background():
    """Green and grey text straight on the sand-coloured wallpaper could not be read."""
    source = (ROOT / "device_qml/C300XSettings.qml").read_text(encoding="utf-8")
    block = source[source.index("height: statusRows.height + 8"):source.index("                model: 6\n")]
    assert 'source: "images/settings/act_btn.svg"' in block
    assert block.index("Image {") < block.index("id: statusRows") < block.index("model: 5")
    assert 'objectName: "bridgeReason"' in block, "the reason lies on the panel too"
    assert "width: statusRows.width" in block
    assert "color: head ?" not in source, "section titles are white like the station's own text"
