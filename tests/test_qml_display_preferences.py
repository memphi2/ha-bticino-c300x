"""Stock-settings patch and GUI preference regressions without a device."""

import shutil
import stat
import subprocess

import pytest
from test_qml_patch_script import (
    ORIGINAL_GENERAL_SETTINGS,
    ROOT,
    _run_qml_patch,
    _run_qml_patch_raw,
    _write_original_gui,
)

SETTINGS = "Components/Settings/GeneralsChoice.qml"


def test_preferences_production_runtime():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    result = subprocess.run(
        [node, str(ROOT / "tests/qml/display_preferences.cjs")],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("topic", ["display_bridge.state", "notifications"])
def test_home_availability_event_refreshes_after_inflight_read(tmp_path, topic):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    _run_qml_patch(
        tmp_path, gui, backup, "apply",
        env_overrides={"C300X_QML_DYNAMIC_HOME_PAGE": "1"},
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
    const page = {alarmButtonVisible: previous, haButtonVisible: previous};
    let unreadRefreshes = 0;
    const home = vm.createContext({page, HAConfig: api,
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
    home.handleMessageNotificationEvent({topic: process.argv[2]});
    assert.equal(api.forwardQueue.length, 1, 'each availability event invalidates the pre-event read');
    home.handleMessageNotificationEvent({topic: 'notifications'});
    home.handleMessageNotificationEvent({topic: 'display_bridge.state'});
    home.handleMessageNotificationEvent({topic: 'memos'});
    home.handleMessageNotificationEvent({topic: 'answering_machine.messages'});
    assert.equal(unreadRefreshes, 2, 'memo and answering-machine refreshes are preserved');
    assert.equal(requests.length, 1, 'forwarded requests remain serialized');
    requests[0].finish(previous);
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
}
""", str(gui), topic], capture_output=True, text=True, check=False, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


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
    assert "c300xFeedbackSetting" in (gui / SETTINGS).read_text()
    result = _run_qml_patch(tmp_path, gui, backup, "restore")
    assert result["patched"] is False
    assert result["core_patched"] is True
    assert (gui / SETTINGS).read_text() == ORIGINAL_GENERAL_SETTINGS


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
    assert patched.count("id: c300xFeedbackSetting") == 1
    assert "anchors.top: beepButton.bottom" in patched
    assert "anchors.topMargin: 8" in patched
    assert "        spacing: 4" in patched
    assert "checked: global.beepEnabled" in patched
    assert "onTouched: global.beepEnabled = checked" in patched
    assert "Qt.createQmlObject" not in (gui / "MainApp.qml").read_text()
    assert "property variant request:" not in (gui / "MainApp.qml").read_text()
    assert _run_qml_patch(tmp_path, gui, backup, "apply")["changed_files"] == 0
    assert (backup / SETTINGS).read_bytes() == original
    _run_qml_patch(tmp_path, gui, backup, "restore-all")
    assert settings.read_bytes() == original
    assert stat.S_IMODE(settings.stat().st_mode) == 0o640
    assert settings.stat().st_mtime_ns == original_time


@pytest.mark.parametrize("broken", [
    "onTouched: global.beepEnabled = checked", "id: beepButton", "anchors.topMargin: 32",
    "anchors.topMargin: parent.height / 100 * 4", "spacing: 6",
])
def test_unknown_settings_layout_aborts_before_touching_gui(tmp_path, broken):
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    (gui / SETTINGS).write_text(ORIGINAL_GENERAL_SETTINGS.replace(broken, "// changed vendor layout"))
    before = {p.relative_to(gui): p.read_bytes() for p in gui.rglob("*") if p.is_file()}
    assert _run_qml_patch_raw(tmp_path, gui, backup, "apply").returncode != 0
    assert {p.relative_to(gui): p.read_bytes() for p in gui.rglob("*") if p.is_file()} == before


def test_settings_fit_original_800_by_480_screen(tmp_path):
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    _run_qml_patch(tmp_path, gui, backup, "apply")
    source = (gui / SETTINGS).read_text()
    assert "    anchors.topMargin: 8" in source
    assert "        spacing: 4" in source
    tone = source.split("id: beepButton", 1)[1].split("id: c300xFeedbackSetting", 1)[0]
    feedback = source.split("id: c300xFeedbackSetting", 1)[1]
    assert "anchors.topMargin: 8" in tone
    assert "anchors.topMargin: 6" in feedback
    assert "height: 44" in feedback
    # Stock Settings.qml header/section and SVG button dimensions.
    section_top = 78 + 480 * 0.05
    button_column_height = 5 * 50 + 4 * 4
    feedback_bottom = section_top + 8 + button_column_height + 8 + 34.239 + 6 + 44
    assert feedback_bottom <= 480 - 10


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
        assert "GeneralsChoice.qml" in result.stderr
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
    assert (gui / SETTINGS).read_text() == ORIGINAL_GENERAL_SETTINGS


def test_settings_are_inert_when_older_restore_removes_ha_helpers(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    _run_qml_patch(tmp_path, gui, backup, "apply")
    source = (gui / SETTINGS).read_text()
    assert not any("js/" in line for line in source.splitlines() if line.startswith("import "))
    result = subprocess.run([node, "-e", """
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1], 'utf8').split('id: c300xFeedbackSetting')[1];
const ctx = vm.createContext({c300xFeedbackSetting: {visible: false}});
function expression(name) {
    return source.match(new RegExp('^ +'+ name + ': (.+)$', 'm'))[1];
}
assert.equal(vm.runInContext(expression('visible'), ctx), false);
assert.equal(vm.runInContext(expression('text'), ctx), '');
assert.equal(vm.runInContext(expression('enabled'), ctx), false);
assert.equal(vm.runInContext(expression('checked'), ctx), true);
ctx.c300xDisplayPreferences = {ready: true, busy: false, feedbackEnabled: false, label: 'HA feedback'};
ctx.c300xFeedbackSetting.visible = vm.runInContext(expression('visible'), ctx);
assert.equal(ctx.c300xFeedbackSetting.visible, true);
assert.equal(vm.runInContext(expression('text'), ctx), 'HA feedback');
assert.equal(vm.runInContext(expression('enabled'), ctx), true);
assert.equal(vm.runInContext(expression('checked'), ctx), false);
""", str(gui / SETTINGS)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
