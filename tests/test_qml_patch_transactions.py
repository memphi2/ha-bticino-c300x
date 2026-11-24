"""Fault injection against real QML scripts, using only temporary GUI files."""

import os
import shutil
import stat
import subprocess

import pytest
from test_qml_patch_script import (
    SCRIPT,
    SOURCE_DIR,
    SOURCE_INSTALLED_FILES,
    _run_qml_patch_raw,
    _write_original_gui,
)

PATCH_FILES = [
    "Settings.qml", "MainApp.qml", "HomePage.qml", "MemoPage.qml", "EventManager.qml",
    *SOURCE_INSTALLED_FILES,
]
STOCK_FILES = ["Settings.qml", "MainApp.qml", "HomePage.qml", "MemoPage.qml", "EventManager.qml",
               "Components/Settings/CallBlockPopup.qml"]


def snapshot(root, *, gui_only=False):
    """``gui_only`` leaves out a write transaction kept next to the GUI files."""
    return {str(p.relative_to(root)): (p.read_bytes(), stat.S_IMODE(p.stat().st_mode))
            for p in root.rglob("*") if p.is_file()
            and not (gui_only and p.relative_to(root).parts[0].startswith(".c300x-qml-transaction."))}


def failing_copy(tmp_path, destination, *, prefix=False):
    commands = tmp_path / "commands"
    commands.mkdir(exist_ok=True)
    script = commands / "cp"
    script.write_text(
        '#!/bin/sh\n'
        'case "$3" in\n'
        f'  "{destination}"{"*" if prefix else ""}) '
        'printf partial > "$3"; chmod 600 "$3"; exit 1;;\n'
        'esac\n'
        f'exec "{shutil.which("cp")}" "$@"\n'
    )
    script.chmod(0o700)
    return {"PATH": str(commands) + os.pathsep + os.environ["PATH"]}


@pytest.mark.parametrize("relative", PATCH_FILES)
def test_apply_copy_failure_restores_all_active_files_and_modes(tmp_path, relative):
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    for path in gui.rglob("*.qml"):
        path.chmod(0o640)
    before = snapshot(gui)
    result = _run_qml_patch_raw(tmp_path, gui, backup, "apply",
                                env_overrides=failing_copy(tmp_path, gui / relative))
    assert result.returncode != 0
    assert snapshot(gui) == before
    assert not list(gui.glob(".c300x-qml-transaction.*"))


@pytest.mark.parametrize("relative", STOCK_FILES)
def test_restore_all_copy_failure_restores_patched_gui_and_modes(tmp_path, relative):
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    for action in ("apply", "media-user-label-apply"):
        _run_qml_patch_raw(tmp_path, gui, backup, action).check_returncode()
    for path in gui.rglob("*"):
        if path.is_file():
            path.chmod(0o640)
    (gui / "js").chmod(0o750)
    before = snapshot(gui)
    result = _run_qml_patch_raw(tmp_path, gui, backup, "restore-all",
                                env_overrides=failing_copy(tmp_path, gui / relative))
    assert result.returncode != 0
    assert snapshot(gui) == before
    assert stat.S_IMODE((gui / "js").stat().st_mode) == 0o750
    assert not list(gui.glob(".c300x-qml-transaction.*"))


@pytest.mark.parametrize("relative", [*STOCK_FILES, "Components/Settings/GeneralsChoice.qml"])
def test_original_backup_copy_failure_is_not_published_and_retry_is_safe(tmp_path, relative):
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    before = snapshot(gui)
    action = "media-user-label-apply" if relative.endswith("CallBlockPopup.qml") else "apply"
    result = _run_qml_patch_raw(
        tmp_path, gui, backup, action,
        env_overrides=failing_copy(tmp_path, str(backup / relative) + ".tmp.", prefix=True),
    )
    assert result.returncode != 0
    assert snapshot(gui) == before
    assert not (backup / relative).exists()
    _run_qml_patch_raw(tmp_path, gui, backup, action).check_returncode()
    assert (backup / relative).read_bytes() == before[relative][0]


def test_transaction_backup_copy_failure_never_changes_active_gui(tmp_path):
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    before = snapshot(gui)
    result = _run_qml_patch_raw(
        tmp_path, gui, backup, "apply",
        env_overrides=failing_copy(tmp_path, str(gui / ".c300x-qml-transaction."), prefix=True),
    )
    assert result.returncode != 0
    assert snapshot(gui) == before


def test_label_only_restore_all_does_not_require_unmodified_core_backup(tmp_path):
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    before = snapshot(gui)
    _run_qml_patch_raw(tmp_path, gui, backup, "media-user-label-apply").check_returncode()
    assert not (backup / "EventManager.qml").exists()
    _run_qml_patch_raw(tmp_path, gui, backup, "restore-all").check_returncode()
    assert snapshot(gui) == before


def test_failed_rollback_retains_original_recovery_file(tmp_path):
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    before = snapshot(gui)
    env = failing_copy(tmp_path, gui / "HomePage.qml")
    move = tmp_path / "commands/mv"
    move.write_text('#!/bin/sh\ncase "$2" in\n'
                    '  */.c300x-qml-transaction.*/MainApp.qml) exit 1;;\nesac\n'
                    f'exec "{shutil.which("mv")}" "$@"\n')
    move.chmod(0o700)
    result = _run_qml_patch_raw(tmp_path, gui, backup, "apply", env_overrides=env)
    assert result.returncode != 0
    assert "recovery files retained" in result.stderr
    recovery = list(gui.glob(".c300x-qml-transaction.*/MainApp.qml"))
    assert len(recovery) == 1
    assert recovery[0].read_bytes() == before["MainApp.qml"][0]


def test_original_backup_ignores_preseeded_predictable_temp_symlink(tmp_path):
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    backup.mkdir()
    _write_original_gui(gui)
    original = (gui / "MainApp.qml").read_bytes()
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"must remain unchanged")
    result = subprocess.run(
        ["sh", "-c", 'ln -s "$1" "$2/MainApp.qml.tmp.$$"; exec "$3" apply',
         "backup-test", str(sentinel), str(backup), str(SCRIPT)],
        env={**os.environ, "C300X_QML_GUI_DIR": str(gui),
             "C300X_QML_SOURCE_DIR": str(SOURCE_DIR), "C300X_QML_BACKUP_DIR": str(backup),
             "C300X_QML_NO_REMOUNT": "1", "C300X_QML_RELOAD_GUI": "0"},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert sentinel.read_bytes() == b"must remain unchanged"
    assert not (backup / "MainApp.qml").is_symlink()
    assert (backup / "MainApp.qml").read_bytes() == original
    assert all(path.is_symlink() for path in backup.glob("*.tmp.*"))
