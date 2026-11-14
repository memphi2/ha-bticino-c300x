"""Removal admission and real label-only GUI restore without an agent/device."""

import os
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
def test_unavailable_patch_script_keeps_backups_and_never_reboots(local_device, tmp_path, unavailable):
    env = local_device
    label_patch(env)
    Path(env["CALL_LOG"]).write_text("")
    missing = tmp_path / "unavailable-script"
    if unavailable == "nonexecutable":
        missing.write_text("#!/bin/sh\nexit 0\n")
        missing.chmod(0o600)
    env["C300X_QML_PATCH_SCRIPT"] = str(missing)
    result = subprocess.run(["sh", str(REMOVE), "--run-from-tmp"], env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "keeping agent files and backups" in result.stderr
    assert Path(env["C300X_AGENT_DIR"]).is_dir()
    assert Path(env["C300X_QML_BACKUP_DIR"], "Components/Settings/CallBlockPopup.qml").is_file()
    assert Path(env["C300X_INIT_SCRIPT"]).is_file()
    assert Path(env["CALL_LOG"]).read_text().splitlines() == ["ssh-init"]


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
