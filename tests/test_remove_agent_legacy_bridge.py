"""Removing the agent gives fquinto's legacy MQTT bridge its start rights back."""

import subprocess
from pathlib import Path

import pytest
from test_remove_agent_script_safety import REMOVE, _command_double, _original_busybox
from test_remove_agent_script_safety import local_device as local_device


def _remove(env):
    return subprocess.run(["sh", str(REMOVE), "--run-from-tmp"], env=env,
                          capture_output=True, text=True, timeout=10)


def _legacy(env, mode, record):
    """The bridge as legacy MQTT off left it, and the agent's record of its mode."""
    bridge = Path(env["C300X_LEGACY_MQTT_BRIDGE"])
    bridge.parent.mkdir(parents=True)
    bridge.write_text("#!/bin/sh\nexec sleep 30\n")
    bridge.chmod(mode)
    path = Path(env["C300X_BACKUP_ROOT"], "legacy-mqtt/bridge-mode")
    if record is not None:
        path.parent.mkdir(parents=True)
        path.write_text(record)
    return bridge


def _calls(env):
    return Path(env["CALL_LOG"]).read_text().splitlines()


@pytest.mark.parametrize(("mode", "record", "restored"), [
    (0o640, "0750\n", 0o750),
    (0o600, "0700\n", 0o700),
    (0o4640, "4750", 0o4750),
    # A record that does not belong to the file: its read bits become execute bits.
    (0o640, "0700\n", 0o750),
    (0o640, "junk\n", 0o750),
])
def test_removal_gives_the_blocked_bridge_its_mode_back(local_device, mode, record, restored):
    env = local_device
    bridge = _legacy(env, mode, record)
    result = _remove(env)
    assert result.returncode == 0, result.stderr
    assert bridge.stat().st_mode & 0o7777 == restored
    assert not Path(env["C300X_BACKUP_ROOT"]).exists()
    assert not Path(env["C300X_AGENT_DIR"]).exists()
    # Inside its own root remount, after the media restore and before the startup goes.
    calls = _calls(env)
    media = calls.index("media-restore")
    assert calls[media + 1:media + 3] == ["mount", "mount"]
    assert calls.count("mount") == 8


@pytest.mark.parametrize("state", ["no_legacy", "record_without_bridge", "executable", "no_record",
                                   "link"])
def test_removal_without_a_blocked_bridge_does_nothing_extra(local_device, tmp_path, state):
    """2.0.2, 3.0.6 and C100X stations have no /etc/tcpdump2mqtt: no extra remount, nothing changed."""
    env = local_device
    bridge = Path(env["C300X_LEGACY_MQTT_BRIDGE"])
    target = tmp_path / "bridge-target"
    if state == "record_without_bridge":
        _legacy(env, 0o640, "0750\n").unlink()
    elif state == "executable":
        _legacy(env, 0o700, "0750\n")
    elif state == "no_record":
        _legacy(env, 0o640, None)
    elif state == "link":
        _legacy(env, 0o640, "0750\n").unlink()
        target.write_text("#!/bin/sh\n")
        target.chmod(0o640)
        bridge.symlink_to(target)
    result = _remove(env)
    assert result.returncode == 0, result.stderr
    calls = _calls(env)
    media = calls.index("media-restore")
    # The next remount is the startup removal: rw, then ro. The reboot runs in
    # the background and may not be logged yet.
    assert calls[media + 1:media + 4] == ["mount", "mount", "ssh-init"]
    assert calls.count("mount") == 6
    if state == "no_legacy":
        assert not bridge.parent.exists()
    elif state == "executable":
        assert bridge.stat().st_mode & 0o7777 == 0o700
    elif state == "no_record":
        assert bridge.stat().st_mode & 0o7777 == 0o640
    elif state == "link":
        assert target.stat().st_mode & 0o7777 == 0o640
        assert bridge.is_symlink()


@pytest.mark.parametrize("failure", ["chmod", "rw", "ro"])
def test_a_bridge_that_cannot_get_its_mode_back_keeps_the_record(local_device, tmp_path, failure):
    env = local_device
    bridge = _legacy(env, 0o640, "0750\n")
    if failure == "chmod":
        _command_double(tmp_path, "chmod", 'case "$2" in */TcpDump2Mqtt) exit 1 ;; esac')
    else:
        mount = tmp_path / "commands/mount"
        mount.write_text(f'#!/bin/sh\nprintf "mount\\n" >> "$CALL_LOG"\n'
                         f'grep -q "^media-restore$" "$CALL_LOG" || exit 0\n'
                         f'case "$*" in *remount,{failure}*) exit 1 ;; esac\nexit 0\n')
        mount.chmod(0o700)
    result = _remove(env)
    assert result.returncode != 0
    assert "Failed to give the legacy MQTT bridge its execute bits back" in result.stderr
    assert "keeping agent files and backups in place" in result.stderr
    assert Path(env["C300X_BACKUP_ROOT"], "legacy-mqtt/bridge-mode").read_text() == "0750\n"
    assert Path(env["C300X_AGENT_DIR"]).is_dir()
    assert Path(env["C300X_INIT_SCRIPT"]).is_file()
    assert "reboot" not in _calls(env)
    if failure != "ro":
        assert bridge.stat().st_mode & 0o7777 == 0o640


@pytest.mark.parametrize("firmware", ["1.7.19", "2.0.2"])
def test_the_firmware_shell_computes_the_bridge_mode(tmp_path, firmware):
    """Octal arithmetic and printf of the station's own busybox sh."""
    busybox = _original_busybox(firmware)
    prefix = tmp_path / "loader-root"
    prefix.mkdir()
    (prefix / "lib").symlink_to(Path(busybox[2]) / "lib", target_is_directory=True)
    busybox[2] = str(prefix)
    text = REMOVE.read_text()
    start = text.index("restore_legacy_bridge() {")
    function = text[start:text.index("\n}\n", start) + 3]
    cases = [(0o640, "0750\n", 0o750), (0o4600, "4700", 0o4700), (0o640, "0700\n", 0o750)]
    for number, (mode, record, restored) in enumerate(cases):
        bridge = tmp_path / f"bridge-{number}"
        bridge.write_text("#!/bin/sh\n")
        bridge.chmod(mode)
        (tmp_path / f"record-{number}").write_text(record)
        script = (f"LEGACY_BRIDGE={bridge}\nLEGACY_BRIDGE_MODE={tmp_path}/record-{number}\n"
                  "remount_root_rw() { :; }\nremount_root_ro() { :; }\n"
                  f"{function}restore_legacy_bridge\n")
        result = subprocess.run([*busybox, "sh", "-c", script], capture_output=True, text=True,
                                timeout=10, env={"PATH": "/usr/bin:/bin"})
        assert result.returncode == 0, result.stderr
        assert bridge.stat().st_mode & 0o7777 == restored, (firmware, oct(mode), record)
