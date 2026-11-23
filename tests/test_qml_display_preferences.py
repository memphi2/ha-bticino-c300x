"""Stock-settings patch and GUI preference regressions without a device."""

import shutil
import stat
import subprocess

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
    assert (gui / GENERAL).read_text() == ORIGINAL_GENERAL_SETTINGS
    assert 'sourceUrl: "C300XSettings.qml"' in (gui / SETTINGS).read_text()
    result = _run_qml_patch(tmp_path, gui, backup, "restore")
    assert result["patched"] is False
    assert result["core_patched"] is True
    assert (gui / SETTINGS).read_text() == ORIGINAL_SETTINGS


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
