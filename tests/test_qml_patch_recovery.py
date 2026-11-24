"""Recovery of GUI write transactions left behind by a killed write.

Real qml_patch.sh against temporary GUI files; GUI restart, mount and the
file commands are logged stand-ins, and a held command lets a test SIGKILL
the recovery at one exact step.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest
import test_qml_patch_script as qml
from test_qml_patch_script import _gui_files, _killed_apply, _run_qml_patch_raw, _write_original_gui


def _commands(tmp_path: Path, hold: tuple[str, str] | None = None) -> dict[str, str]:
    """killall/pidof/mount log their calls and report a running GUI; every
    command named in ``hold`` blocks at its first call whose arguments match
    the shell pattern until the test kills it."""

    commands = tmp_path / "recovery-commands"
    shutil.rmtree(commands, ignore_errors=True)
    commands.mkdir()
    log = tmp_path / "calls.log"
    held = tmp_path / "held"
    held.unlink(missing_ok=True)
    for name in ("killall", "pidof", "mount", "mv", "rm"):
        real = {"mv": shutil.which("mv"), "rm": shutil.which("rm")}.get(name)
        body = f'#!/bin/sh\nprintf "%s\\n" "{name} $*" >> "{log}"\n'
        if hold is not None and hold[0] == name:
            pattern = hold[1].replace(" ", "\\ ")
            body += (f'case "$*" in\n  {pattern})\n'
                     f'    if [ ! -e "{held}" ]; then : > "{held}"; while :; do sleep 0.02; done; fi\n'
                     '    ;;\nesac\n')
        body += f'exec "{real}" "$@"\n' if real else "exit 0\n"
        (commands / name).write_text(body)
        (commands / name).chmod(0o700)
    return {
        "PATH": str(commands) + os.pathsep + os.environ["PATH"],
        "TMPDIR": str(tmp_path),
        "C300X_QML_NO_REMOUNT": "0",
        "C300X_QML_RELOAD_GUI": "1",
        "C300X_QML_GUI_RELOAD_DELAY_SECONDS": "0",
        "C300X_QML_GUI_WRAPPER": str(tmp_path / "missing-wrapper"),
    }


def _calls(tmp_path: Path, name: str) -> list[str]:
    log = tmp_path / "calls.log"
    lines = log.read_text().splitlines() if log.exists() else []
    return [line for line in lines if line.split(" ", 1)[0] == name]


def _run(tmp_path: Path, gui: Path, backup: Path, action: str,
         env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    (tmp_path / "calls.log").unlink(missing_ok=True)
    return _run_qml_patch_raw(tmp_path, gui, backup, action, env_overrides=env)


def _kill_when_held(tmp_path: Path, gui: Path, backup: Path, action: str, env: dict[str, str]) -> None:
    (tmp_path / "calls.log").unlink(missing_ok=True)
    process = subprocess.Popen(
        [str(qml.SCRIPT), action], start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={**os.environ, "C300X_QML_GUI_DIR": str(gui), "C300X_QML_SOURCE_DIR": str(qml.SOURCE_DIR),
             "C300X_QML_BACKUP_DIR": str(backup), "C300X_QML_GUI_ROOT": str(tmp_path), **env})
    deadline = time.monotonic() + 20
    while not (tmp_path / "held").exists():
        assert process.poll() is None and time.monotonic() < deadline
        time.sleep(0.01)
    os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=10)


def _as_legacy(gui: Path) -> Path:
    """A 2.9.0 write used the same directory and copies, without the format
    marker and the file list."""

    leftover = next(gui.glob(".c300x-qml-transaction.*"))
    (leftover / ".c300x-v2").unlink()
    (leftover / ".c300x-files").unlink()
    return leftover


def test_a_legacy_leftover_with_verified_copies_is_restored_and_the_gui_restarted(tmp_path: Path) -> None:
    gui, backup, before = _killed_apply(tmp_path)
    leftover = _as_legacy(gui)
    env = _commands(tmp_path)
    status = _run(tmp_path, gui, backup, "status", env)
    assert json.loads(status.stdout)["transaction"] == "pending"
    assert leftover.is_dir() and _calls(tmp_path, "killall") == []
    result = _run(tmp_path, gui, backup, "recover", env)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["transaction"] == "recovered"
    after = _gui_files(gui)
    # Every file the write found is back; the files it added stay, since a
    # legacy transaction does not name them.
    assert {rel: after[rel] for rel in before} == before
    assert not list(gui.glob(".c300x-qml-transaction.*"))
    assert _calls(tmp_path, "killall") == ["killall BtClass"]
    assert _calls(tmp_path, "mount") == ["mount -o remount,rw /", "mount -o remount,ro /"]
    assert not (tmp_path / "c300x-qml-root-rw").exists()


def test_a_legacy_leftover_with_a_truncated_copy_is_kept_and_reported_stuck(tmp_path: Path) -> None:
    gui, backup, _before = _killed_apply(tmp_path)
    leftover = _as_legacy(gui)
    copy = leftover / "HomePage.qml"
    copy.write_bytes(copy.read_bytes()[:100])
    during = _gui_files(gui)
    env = _commands(tmp_path)
    result = _run(tmp_path, gui, backup, "recover", env)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["transaction"] == "stuck"
    assert _gui_files(gui) == {**during, **{
        str(p.relative_to(gui)): p.read_bytes() for p in leftover.glob(".c300x-stuck")}}
    assert copy.read_bytes() == during[str(copy.relative_to(gui))]
    assert _calls(tmp_path, "killall") == []
    status = _run(tmp_path, gui, backup, "status", env)
    assert json.loads(status.stdout)["transaction"] == "stuck"
    # The write rebuilds every file from the backups and sources, so a legacy
    # leftover does not block it; the leftover stays for a manual check and
    # is never restored over the new files later.
    write = _run(tmp_path, gui, backup, "apply", env)
    assert write.returncode == 0, write.stderr
    applied = json.loads(write.stdout)
    assert applied["patched"] is True and applied["transaction"] == "stuck"
    patched = _gui_files(gui)
    again = _run(tmp_path, gui, backup, "recover", env)
    assert json.loads(again.stdout)["transaction"] == "stuck"
    assert _gui_files(gui) == patched and leftover.is_dir()


def test_a_leftover_without_a_file_list_needs_no_gui_restart(tmp_path: Path) -> None:
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    before = _gui_files(gui)
    leftover = gui / f".c300x-qml-transaction.{qml._dead_pid()}"
    leftover.mkdir()
    (leftover / ".c300x-v2").write_text("")
    (leftover / "MainApp.qml").write_text("partial")
    env = _commands(tmp_path)
    result = _run(tmp_path, gui, backup, "recover", env)
    assert json.loads(result.stdout)["transaction"] == "recovered"
    assert _gui_files(gui) == before
    assert _calls(tmp_path, "killall") == []


@pytest.mark.parametrize(("hold", "restarts_again"), [
    (("mv", "*/.c300x-qml-transaction.*/MainApp.qml *"), True),
    (("killall", "*"), True),
    (("rm", "-f */.c300x-v2"), False),
    (("mount", "-o remount,ro /"), False),
])
def test_a_recovery_killed_at_any_step_is_finished_by_the_next_one(
    tmp_path: Path, hold: tuple[str, str], restarts_again: bool,
) -> None:
    gui, backup, before = _killed_apply(tmp_path)
    _kill_when_held(tmp_path, gui, backup, "recover", _commands(tmp_path, hold))
    env = _commands(tmp_path)
    result = _run(tmp_path, gui, backup, "recover", env)
    assert result.returncode == 0, result.stderr
    assert _gui_files(gui) == before
    assert not list(gui.glob(".c300x-qml-transaction.*"))
    assert _calls(tmp_path, "killall") == (["killall BtClass"] if restarts_again else [])
    assert _calls(tmp_path, "mount")[-1] == "mount -o remount,ro /"
    assert not (tmp_path / "c300x-qml-root-rw").exists()
    finished = _run(tmp_path, gui, backup, "recover", env)
    assert "transaction" not in json.loads(finished.stdout)
    assert _calls(tmp_path, "mount") == [] and _calls(tmp_path, "killall") == []


@pytest.mark.parametrize("write_first", [False, True])
def test_a_terminated_display_library_step_exits_131_and_finishes_root_and_gui(
    tmp_path: Path, write_first: bool,
) -> None:
    """SIGTERM while the agent swaps the display library, after the QML step:
    with nothing left to write there (the old 130 trap) and after a committed
    write (no trap at all). Exit 130 would claim a complete rollback."""

    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    if not write_first:
        _run_qml_patch_raw(tmp_path, gui, backup, "apply").check_returncode()
    agent = tmp_path / "agent" / "c300x-agent-native"
    agent.parent.mkdir()
    agent.write_text(f'#!/bin/sh\n: > "{tmp_path}/held"\nwhile :; do sleep 0.02; done\n')
    agent.chmod(0o700)
    env = _commands(tmp_path)
    # The GUI runs until the library step; then it is down.
    (tmp_path / "recovery-commands" / "pidof").write_text(f'#!/bin/sh\n[ ! -e "{tmp_path}/held" ]\n')
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "mounts").write_text("/dev/mmcblk2p6 / ext4 rw,relatime 0 0\n")
    env.update({"C300X_QML_AGENT_BIN": str(agent), "C300X_QML_PROC_DIR": str(proc)})
    result = qml._terminate_when_held(tmp_path, gui, backup, "apply", env)
    assert result.returncode == 131, result.stderr
    assert result.stdout == ""
    # The write's own GUI restart, then the one after the library step.
    assert _calls(tmp_path, "killall") == ["killall BtClass"] * (2 if write_first else 1)
    assert _calls(tmp_path, "mount")[-1] == "mount -o remount,ro /"
    assert json.loads(_run_qml_patch_raw(tmp_path, gui, backup, "status").stdout)["patched"] is True
