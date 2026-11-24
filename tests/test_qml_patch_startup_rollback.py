"""Process-start fault injection, not Qt/QML readiness or device validation."""

import json
import os
import shutil

import pytest
from test_qml_patch_script import (
    _copy_source_tree,
    _run_qml_patch_raw,
    _write_original_gui,
)
from test_qml_patch_transactions import snapshot


def startup_env(tmp_path, *, succeeds_on=2):
    commands = tmp_path / "startup-commands"
    commands.mkdir()
    observations = tmp_path / "startup-observations"
    observations.mkdir()
    scripts = {
        "killall": '#!/bin/sh\nset -eu\n'
        'count=0\n[ ! -f "$C300X_TEST_OBSERVATIONS/count" ] || '
        'count=$(cat "$C300X_TEST_OBSERVATIONS/count")\n'
        'count=$((count + 1))\n'
        'printf "%s" "$count" > "$C300X_TEST_OBSERVATIONS/count"\n'
        'cp -Rp "$C300X_QML_GUI_DIR" "$C300X_TEST_OBSERVATIONS/$count"\n',
        "pidof": '#!/bin/sh\n'
        '[ -f "$C300X_TEST_OBSERVATIONS/count" ] && '
        '[ "$(cat "$C300X_TEST_OBSERVATIONS/count")" = "$C300X_TEST_SUCCEEDS_ON" ]\n',
    }
    for name, content in scripts.items():
        path = commands / name
        path.write_text(content)
        path.chmod(0o700)
    return {
        "PATH": str(commands) + os.pathsep + os.environ["PATH"],
        "C300X_TEST_OBSERVATIONS": str(observations),
        "C300X_TEST_SUCCEEDS_ON": str(succeeds_on),
        "C300X_QML_RELOAD_GUI": "1",
        "C300X_QML_GUI_RELOAD_DELAY_SECONDS": "0",
        "C300X_QML_GUI_WRAPPER": str(tmp_path / "missing-wrapper"),
    }, observations


@pytest.mark.parametrize("action", ["apply", "core-apply", "media-user-label-apply",
                                   "restore", "core-restore", "media-user-label-restore", "restore-all"])
@pytest.mark.parametrize("recovery_starts", [False, True])
def test_failed_start_restores_previous_files_before_retry(tmp_path, action, recovery_starts):
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    if "restore" in action:
        for setup in ("apply", "media-user-label-apply"):
            _run_qml_patch_raw(tmp_path, gui, backup, setup).check_returncode()
    else:
        (gui / "C300XEnergyDistribution.qml").write_text("old generated content\n")
    for path in gui.rglob("*"):
        if path.is_file():
            path.chmod(0o640)
    before = snapshot(gui)
    env, observations = startup_env(tmp_path, succeeds_on=2 if recovery_starts else 0)
    result = _run_qml_patch_raw(tmp_path, gui, backup, action, env_overrides=env)
    result.check_returncode()
    status = json.loads(result.stdout)
    assert status["ok"] is False and status["state"] == "reload_failed"
    assert status["gui_running"] is recovery_starts
    assert snapshot(gui) == before
    assert snapshot(observations / "2", gui_only=True) == before
    assert observations.joinpath("count").read_text() == "2"
    assert list((observations / "1").glob(".c300x-qml-transaction.*"))
    assert not list(gui.glob(".c300x-qml-transaction.*"))
    assert ("GUI restart could not be confirmed" in result.stderr) is not recovery_starts


def test_upgrade_start_failure_restores_previous_patch_not_stock(tmp_path):
    gui, backup, source = tmp_path / "gui", tmp_path / "backup", tmp_path / "source"
    gui.mkdir()
    _write_original_gui(gui)
    _run_qml_patch_raw(tmp_path, gui, backup, "apply").check_returncode()
    before = snapshot(gui)
    _copy_source_tree(source)
    alert = source / "C300XAlerts.qml"
    alert.write_text(alert.read_text() + "\n// updated alert\n")
    env, observations = startup_env(tmp_path)
    result = _run_qml_patch_raw(tmp_path, gui, backup, "apply", source_dir=source, env_overrides=env)
    result.check_returncode()
    assert json.loads(result.stdout)["state"] == "reload_failed"
    assert snapshot(gui) == snapshot(observations / "2", gui_only=True) == before
    assert (observations / "1/C300XAlerts.qml").read_bytes() == alert.read_bytes()


def test_start_success_keeps_backup_until_check_and_noop_never_restarts(tmp_path):
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    env, observations = startup_env(tmp_path, succeeds_on=1)
    first = _run_qml_patch_raw(tmp_path, gui, backup, "apply", env_overrides=env)
    first.check_returncode()
    assert json.loads(first.stdout)["patched"] is True
    assert list((observations / "1").glob(".c300x-qml-transaction.*"))
    assert not list(gui.glob(".c300x-qml-transaction.*"))
    before = {p: (p.stat().st_ino, p.stat().st_mtime_ns, p.stat().st_ctime_ns)
              for p in gui.rglob("*") if p.is_file()}
    second = _run_qml_patch_raw(tmp_path, gui, backup, "apply", env_overrides=env)
    second.check_returncode()
    assert json.loads(second.stdout)["changed_files"] == 0
    assert observations.joinpath("count").read_text() == "1"
    assert {p: (p.stat().st_ino, p.stat().st_mtime_ns, p.stat().st_ctime_ns) for p in before} == before


def test_failed_start_and_failed_rollback_retain_recovery_without_restart(tmp_path):
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    original = (gui / "MainApp.qml").read_bytes()
    env, observations = startup_env(tmp_path)
    move = tmp_path / "startup-commands/mv"
    move.write_text('#!/bin/sh\ncase "$2" in\n'
                    '  */.c300x-qml-transaction.*/MainApp.qml) exit 1;;\nesac\n'
                    f'exec "{shutil.which("mv")}" "$@"\n')
    move.chmod(0o700)
    result = _run_qml_patch_raw(tmp_path, gui, backup, "apply", env_overrides=env)
    assert result.returncode != 0
    assert "recovery files retained" in result.stderr
    recovery = list(gui.glob(".c300x-qml-transaction.*/MainApp.qml"))
    assert len(recovery) == 1 and recovery[0].read_bytes() == original
    assert observations.joinpath("count").read_text() == "1"
