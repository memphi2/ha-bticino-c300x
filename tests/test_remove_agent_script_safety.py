"""Removal admission and real label-only GUI restore without an agent/device."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from test_qml_patch_script import (
    ORIGINAL_CALL_BLOCK_POPUP,
    SCRIPT,
    SOURCE_DIR,
    _write_original_gui,
)

REMOVE = Path(__file__).resolve().parents[1] / "native_agent/scripts/remove_agent.sh"


@pytest.fixture
def local_device(tmp_path):
    agent, backup, gui, commands = [tmp_path / name for name in ("agent", "backup", "gui", "commands")]
    for path in (agent, backup, gui, commands):
        path.mkdir()
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    _write_original_gui(gui)
    binary = agent / "c300x-agent-native"
    binary.write_text('#!/bin/sh\nprintf "media-restore\\n" >> "$CALL_LOG"\nexit 0\n')
    binary.chmod(0o700)
    for command in ("mount", "start-stop-daemon", "pidof", "killall", "ssh-init", "reboot"):
        path = commands / command
        path.write_text(f'#!/bin/sh\nprintf "{command}\\n" >> "$CALL_LOG"\n'
                        f'exit {1 if command == "pidof" else 0}\n')
        path.chmod(0o700)
    env = {**os.environ, "PATH": str(commands) + os.pathsep + os.environ["PATH"],
           "TMPDIR": str(temporary),
           "CALL_LOG": str(tmp_path / "calls"), "C300X_AGENT_DIR": str(agent),
           "C300X_BACKUP_ROOT": str(backup), "C300X_QML_PATCH_SCRIPT": str(SCRIPT),
           "C300X_QML_GUI_DIR": str(gui), "C300X_QML_SOURCE_DIR": str(SOURCE_DIR),
           "C300X_QML_BACKUP_DIR": str(backup / "original/gui/skins/default"),
           "C300X_QML_NO_REMOUNT": "1", "C300X_QML_RELOAD_GUI": "0",
           "C300X_SSH_INIT": str(commands / "ssh-init"), "C300X_REBOOT": str(commands / "reboot")}
    for key in ("C300X_INIT_SCRIPT", "C300X_INIT_LINK", "C300X_IPTABLES", "C300X_IPTABLES6"):
        path = tmp_path / key
        path.write_text("original\n")
        env[key] = str(path)
    return env


def label_patch(env):
    result = subprocess.run([str(SCRIPT), "media-user-label-apply"], env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("unavailable", ["missing", "nonexecutable"])
@pytest.mark.parametrize("action", ["remove", "--run-from-tmp"])
def test_unavailable_patch_script_keeps_backups_and_never_reboots(local_device, tmp_path, unavailable, action):
    env = local_device
    label_patch(env)
    Path(env["CALL_LOG"]).write_text("")
    missing = tmp_path / "unavailable-script"
    if unavailable == "nonexecutable":
        missing.write_text("#!/bin/sh\nexit 0\n")
        missing.chmod(0o600)
    env["C300X_QML_PATCH_SCRIPT"] = str(missing)
    result = subprocess.run(["sh", str(REMOVE), action], env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "keeping agent files and backups" in result.stderr
    assert Path(env["C300X_AGENT_DIR"]).is_dir()
    assert Path(env["C300X_QML_BACKUP_DIR"], "Components/Settings/CallBlockPopup.qml").is_file()
    assert Path(env["C300X_INIT_SCRIPT"]).is_file()
    assert Path(env["CALL_LOG"]).read_text().splitlines() == ["ssh-init"]
    assert not list(Path(env["TMPDIR"]).iterdir())


def test_label_only_removal_restores_original_before_deleting_backups(local_device):
    env = local_device
    label_patch(env)
    assert not Path(env["C300X_QML_BACKUP_DIR"], "EventManager.qml").exists()
    popup = Path(env["C300X_QML_GUI_DIR"], "Components/Settings/CallBlockPopup.qml")
    assert popup.read_text() != ORIGINAL_CALL_BLOCK_POPUP
    result = subprocess.run(["sh", str(REMOVE), "--run-from-tmp"], env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert popup.read_text() == ORIGINAL_CALL_BLOCK_POPUP
    assert not Path(env["C300X_BACKUP_ROOT"]).exists()
    assert not Path(env["C300X_AGENT_DIR"]).exists()


@pytest.mark.parametrize("action", ["remove", "--run-from-tmp"])
def test_predictable_temp_symlinks_do_not_modify_sentinel(local_device, tmp_path, action):
    env = local_device
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("untouched\n")
    # Preseed both historical paths using the PID that will execute the script.
    process = subprocess.Popen(
        ["sh", "-c", 'ln -s "$1" /tmp/c300x-remove-agent.$$; '
         'ln -s "$1" /tmp/c300x-managed-block.$$; exec sh "$2" "$3"',
         "removal-test", str(sentinel), str(REMOVE), action],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        _, errors = process.communicate(timeout=10)
        assert process.returncode == 0, errors
        assert sentinel.read_text() == "untouched\n"
        assert not Path(env["C300X_AGENT_DIR"]).exists()
        assert not list(Path(env["TMPDIR"]).iterdir())
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
        for name in ("c300x-remove-agent", "c300x-managed-block"):
            Path(f"/tmp/{name}.{process.pid}").unlink(missing_ok=True)


@pytest.mark.parametrize("failure", ["mktemp", "cp", "chmod"])
def test_staging_failure_keeps_device_files_and_cleans_workspace(local_device, tmp_path, failure):
    env = local_device
    command = tmp_path / "commands" / failure
    command.write_text("#!/bin/sh\n" + ('printf partial > "$2"\n' if failure == "cp" else "") + "exit 1\n")
    command.chmod(0o700)
    before = {key: Path(env[key]).read_bytes() for key in
              ("C300X_INIT_SCRIPT", "C300X_INIT_LINK", "C300X_IPTABLES", "C300X_IPTABLES6")}
    result = subprocess.run(["sh", str(REMOVE), "remove"], env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "keeping agent files and backups" in result.stderr
    assert not Path(env["CALL_LOG"]).exists()
    assert Path(env["C300X_AGENT_DIR"]).is_dir()
    assert Path(env["C300X_BACKUP_ROOT"]).is_dir()
    assert all(Path(env[key]).read_bytes() == data for key, data in before.items())
    assert not list(Path(env["TMPDIR"]).iterdir())


def test_self_copy_uses_private_workspace_even_with_open_umask(local_device, tmp_path):
    env = local_device
    copy = tmp_path / "commands/cp"
    copy.write_text('#!/bin/sh\n'
                    'case "$2" in */remove_agent.sh)\n'
                    '  [ "$(stat -c %a "$(dirname "$2")")" = 700 ] || exit 91;;\nesac\n'
                    f'exec "{shutil.which("cp")}" "$@"\n')
    copy.chmod(0o700)
    result = subprocess.run(["sh", "-c", 'umask 000; exec sh "$1" remove',
                             "removal-test", str(REMOVE)], env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert not list(Path(env["TMPDIR"]).iterdir())
