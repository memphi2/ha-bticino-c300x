"""Real label transactions, stubbed native writes/GUI/mounts, temporary files only."""

import json
import os
import subprocess
import time

import pytest
from test_native_device_user_routes import route_binary as route_binary
from test_qml_patch_script import (
    SCRIPT,
    SOURCE_DIR,
    _run_qml_patch_raw,
    _write_original_gui,
)
from test_qml_patch_startup_rollback import startup_env
from test_qml_patch_transactions import snapshot


def wait_for(path, process):
    deadline = time.monotonic() + 5
    while not path.exists():
        assert process.poll() is None, "route exited before the script reached its probe"
        assert time.monotonic() < deadline, "script did not reach its probe"
        time.sleep(0.01)


def transaction_env(tmp_path, *, succeeds_on, hold_on):
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    env, observations = startup_env(tmp_path, succeeds_on=succeeds_on)
    commands = tmp_path / "startup-commands"
    pidof = commands / "pidof"
    probe = pidof.read_text().removeprefix("#!/bin/sh\n")
    pidof.write_text(
        '#!/bin/sh\n'
        'if [ "$(cat "$C300X_TEST_OBSERVATIONS/count")" = "$C300X_TEST_HOLD_ON" ]; then\n'
        '  touch "$C300X_TEST_OBSERVATIONS/held"\n'
        '  while [ ! -e "$C300X_TEST_OBSERVATIONS/release" ]; do sleep 0.02; done\n'
        'fi\n' + probe
    )
    mount = commands / "mount"
    mount.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$C300X_TEST_OBSERVATIONS/mounts"\n')
    mount.chmod(0o700)
    env.update({
        "C300X_TEST_HOLD_ON": str(hold_on),
        "C300X_QML_GUI_DIR": str(gui), "C300X_QML_BACKUP_DIR": str(backup),
        "C300X_QML_SOURCE_DIR": str(SOURCE_DIR), "C300X_QML_NO_REMOUNT": "0",
        "C300X_QML_GUI_ROOT": str(tmp_path), "C300X_QML_STAGING_DIR": str(tmp_path / "stage"),
        "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1", "UBSAN_OPTIONS": "halt_on_error=1",
    })
    return gui, backup, env, observations


@pytest.mark.parametrize("operation", ["ensure", "restore"])
@pytest.mark.parametrize("outcome,hold_on", [("success", 1), ("rollback", 1), ("rollback", 2)])
def test_label_shutdown_finishes_commit_or_rollback(route_binary, tmp_path, operation, outcome, hold_on):
    gui, backup, env, observations = transaction_env(
        tmp_path, succeeds_on=1 if outcome == "success" else 2, hold_on=hold_on,
    )
    if operation == "restore":
        _run_qml_patch_raw(tmp_path, gui, backup, "media-user-label-apply").check_returncode()
    before = snapshot(gui)
    process = subprocess.Popen([str(route_binary), "transaction", str(SCRIPT), operation],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               env={**os.environ, **env})
    try:
        wait_for(observations / "held", process)
        assert (observations / "mounts").read_text().splitlines()[0] == "-o remount,rw /"
        if hold_on == 1:
            assert list(gui.glob(".c300x-qml-transaction.*"))
        process.terminate()
        time.sleep(0.1)
        assert process.poll() is None, "shutdown interrupted the label transaction"
        (observations / "release").touch()
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0, stderr
        result = json.loads(stdout)
        assert result["writes"] == int(operation == "restore" or outcome == "success")
        assert result["restored"] == int(operation == "restore")
        if outcome == "rollback":
            assert snapshot(gui) == before
            assert snapshot(observations / "2", gui_only=True) == before
        else:
            assert snapshot(gui) != before
        assert not list(gui.glob(".c300x-qml-transaction.*"))
        assert not (tmp_path / "stage").exists()
        assert (observations / "mounts").read_text().splitlines() == [
            "-o remount,rw /", "-o remount,ro /",
        ]
    finally:
        (observations / "release").touch()
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=5)


def test_label_write_has_no_ten_second_kill_deadline(route_binary, tmp_path):
    gui, _, env, observations = transaction_env(tmp_path, succeeds_on=2, hold_on=1)
    before = snapshot(gui)
    process = subprocess.Popen([str(route_binary), "transaction", str(SCRIPT), "ensure"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               env={**os.environ, **env})
    try:
        wait_for(observations / "held", process)
        time.sleep(10.2)
        # Shutdown must still find a live transaction, not an orphaned backup.
        process.terminate()
        time.sleep(0.1)
        assert process.poll() is None
        (observations / "release").touch()
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0, stderr
        assert json.loads(stdout)["writes"] == 0
        assert snapshot(gui) == before
        assert not list(gui.glob(".c300x-qml-transaction.*"))
        assert (observations / "mounts").read_text().splitlines()[-1] == "-o remount,ro /"
    finally:
        (observations / "release").touch()
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=5)
