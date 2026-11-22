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
    binary.write_text(
        '#!/bin/sh\nif [ "$1" = "--display-touch" ]; then\n'
        '    printf \'{"ok":true,"changed":false}\\n\'\n    exit 0\nfi\n'
        'printf "media-restore\\n" >> "$CALL_LOG"\nexit 0\n'
    )
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


def _firewall_fixture(env, family, backed_up):
    target = Path(env["C300X_IPTABLES6" if family == "ipv6" else "C300X_IPTABLES"])
    marker = "c300x-native-agent ipv6 firewall" if family == "ipv6" else "c300x-native-agent firewall"
    original = "#!/bin/sh\n# Firmware rules\niptables -P INPUT DROP\n"
    target.write_text(original + f"# {marker} begin\n# Agent rules\n# {marker} end\n")
    target.chmod(0o750)
    backup = Path(env["C300X_BACKUP_ROOT"], "original/etc/network/if-pre-up.d",
                  "iptables6" if family == "ipv6" else "iptables")
    if backed_up:
        backup.parent.mkdir(parents=True)
        backup.write_text(original)
        backup.chmod(0o600)
    return target, backup, original


def _command_double(tmp_path, name, body):
    command = tmp_path / "commands" / name
    command.write_text(f'#!/bin/sh\n{body}\nexec "{shutil.which(name)}" "$@"\n')
    command.chmod(0o700)


@pytest.mark.parametrize("family", ["ipv4", "ipv6"])
@pytest.mark.parametrize("backed_up", [False, True])
@pytest.mark.parametrize("failure", ["partial_write", "silent_partial", "copy", "rename", "signal", "stage"])
def test_failed_firewall_restore_keeps_live_file_and_all_recovery_material(
    local_device, tmp_path, family, backed_up, failure
):
    env = local_device
    target, backup, _original = _firewall_fixture(env, family, backed_up)
    before = target.read_bytes(), target.stat()
    env["FAULT_TARGET"] = str(target)
    if failure in {"partial_write", "silent_partial", "signal"}:
        outcome = {"partial_write": "exit 1", "silent_partial": "exit 0",
                   "signal": 'kill -TERM "$PPID"; exit 1'}[failure]
        _command_double(tmp_path, "cat", f'''
case "${{1:-}}" in
    */managed-block|*/original/etc/network/if-pre-up.d/iptables*)
        for staged in "$FAULT_TARGET".c300x-restore.*; do
            [ -d "$staged" ] || continue
            printf '# partial restore\\n'
            {outcome}
        done ;;
esac''')
    elif failure == "copy":
        _command_double(tmp_path, "cp", '''
if [ "${1:-}" = -p ] && [ "${2:-}" = "$FAULT_TARGET" ]; then
    printf partial > "$3"
    exit 1
fi''')
    elif failure == "rename":
        _command_double(tmp_path, "mv", '''
if [ "${3:-}" = "$FAULT_TARGET" ]; then exit 1; fi''')
    else:
        _command_double(tmp_path, "mktemp", '''
case "${2:-}" in "$FAULT_TARGET".c300x-restore.*) exit 1;; esac''')

    result = subprocess.run(["sh", str(REMOVE), "--run-from-tmp"], env=env,
                            capture_output=True, text=True, timeout=10)

    assert result.returncode == (130 if failure == "signal" else 1), result.stderr
    assert target.read_bytes() == before[0]
    assert target.stat().st_mode == before[1].st_mode
    assert target.stat().st_ino == before[1].st_ino
    assert Path(env["C300X_AGENT_DIR"]).is_dir()
    assert Path(env["C300X_BACKUP_ROOT"]).is_dir()
    if backed_up:
        assert backup.read_text() == _original
    assert Path(env["C300X_INIT_SCRIPT"]).is_file()
    assert Path(env["C300X_INIT_LINK"]).is_file()
    calls = Path(env["CALL_LOG"]).read_text().splitlines()
    assert not {"reboot", "killall", "start-stop-daemon", "media-restore"}.intersection(calls)
    assert not list(tmp_path.glob("*.c300x-restore.*"))
    assert not list(Path(env["TMPDIR"]).iterdir())


@pytest.mark.parametrize("family", ["ipv4", "ipv6"])
@pytest.mark.parametrize("backed_up", [False, True])
def test_successful_firewall_restore_preserves_live_metadata(local_device, tmp_path, family, backed_up):
    env = local_device
    target, _backup, original = _firewall_fixture(env, family, backed_up)
    before = target.stat()

    result = subprocess.run(["sh", str(REMOVE), "--run-from-tmp"], env=env,
                            capture_output=True, text=True, timeout=10)

    assert result.returncode == 0, result.stderr
    assert target.read_text() == original
    after = target.stat()
    assert (after.st_mode, after.st_uid, after.st_gid) == (before.st_mode, before.st_uid, before.st_gid)
    assert not Path(env["C300X_BACKUP_ROOT"]).exists()
    assert not Path(env["C300X_AGENT_DIR"]).exists()
    assert not list(tmp_path.glob("*.c300x-restore.*"))


@pytest.mark.parametrize("backed_up", [False, True])
def test_missing_firewall_is_only_recreated_from_a_backup(local_device, backed_up):
    env = local_device
    target, _backup, original = _firewall_fixture(env, "ipv6", backed_up)
    target.unlink()

    result = subprocess.run(["sh", str(REMOVE), "--run-from-tmp"], env=env,
                            capture_output=True, text=True, timeout=10)

    assert result.returncode == 0, result.stderr
    assert target.exists() is backed_up
    if backed_up:
        assert target.read_text() == original
        assert target.stat().st_mode & 0o777 == 0o755


@pytest.mark.parametrize("backed_up", [False, True])
def test_symlink_firewall_target_fails_closed(local_device, tmp_path, backed_up):
    env = local_device
    target, _backup, _original = _firewall_fixture(env, "ipv6", backed_up)
    sentinel = tmp_path / "sentinel"
    target.rename(sentinel)
    before = sentinel.read_bytes()
    target.symlink_to(sentinel)

    result = subprocess.run(["sh", str(REMOVE), "--run-from-tmp"], env=env,
                            capture_output=True, text=True, timeout=10)

    assert result.returncode != 0
    assert sentinel.read_bytes() == before
    assert target.is_symlink()
    assert Path(env["C300X_BACKUP_ROOT"]).is_dir()
    assert Path(env["C300X_AGENT_DIR"]).is_dir()
    assert "reboot" not in Path(env["CALL_LOG"]).read_text().splitlines()


@pytest.mark.parametrize(("phase", "failure"), [
    (phase, failure)
    for phase in ("firewall", "startup")
    for failure in ("rw", "ro_once", "ro_always", "remove")
    if failure != "remove" or phase == "startup"
])
def test_restore_and_startup_failures_block_deletion_and_reboot(local_device, tmp_path, phase, failure):
    env = local_device
    marker = Path(env["C300X_BACKUP_ROOT"], "keep")
    marker.write_text("recovery material\n")
    env["FAIL_PHASE"] = phase
    env["FAIL_MODE"] = failure
    env["RO_FAILED"] = str(tmp_path / "ro-failed")
    if failure == "remove":
        _command_double(tmp_path, "rm", '''
if [ "${2:-}" = "$C300X_INIT_LINK" ]; then exit 73; fi''')
    mount = tmp_path / "commands/mount"
    mount.write_text('''#!/bin/sh
printf 'mount %s\\n' "$*" >> "$CALL_LOG"
in_phase=0
if [ "$FAIL_PHASE" = firewall ] || grep -q '^media-restore$' "$CALL_LOG"; then in_phase=1; fi
if [ "$in_phase" = 1 ]; then
    case "$FAIL_MODE:$*" in
        rw:*remount,rw*|ro_always:*remount,ro*) exit 1 ;;
        ro_once:*remount,ro*)
            if [ ! -f "$RO_FAILED" ]; then touch "$RO_FAILED"; exit 1; fi ;;
    esac
fi
exit 0
''')
    mount.chmod(0o700)

    result = subprocess.run(["sh", str(REMOVE), "--run-from-tmp"], env=env,
                            capture_output=True, text=True, timeout=10)

    assert result.returncode != 0
    assert "keeping agent files and backups" in result.stderr
    assert marker.read_text() == "recovery material\n"
    assert Path(env["C300X_AGENT_DIR"]).is_dir()
    calls = Path(env["CALL_LOG"]).read_text().splitlines()
    assert "reboot" not in calls
    if phase == "firewall":
        assert "media-restore" not in calls
        assert Path(env["C300X_INIT_SCRIPT"]).is_file()
    if failure.startswith("ro_"):
        assert calls[-2:] == ["mount -o remount,ro /", "mount -o remount,ro /"]
    if failure in {"rw", "remove"}:
        assert Path(env["C300X_INIT_SCRIPT"]).is_file()
        assert Path(env["C300X_INIT_LINK"]).is_file()
    assert not list(Path(env["TMPDIR"]).iterdir())


def _display_library_restore(env, answer):
    """The agent answers its library restore with `answer`; the rest works."""

    binary = Path(env["C300X_AGENT_DIR"], "c300x-agent-native")
    binary.write_text(
        '#!/bin/sh\nif [ "$1" = "--display-touch" ]; then\n'
        f"    printf '%s\\n' '{answer}'\n    exit 1\nfi\n"
        'printf "media-restore\\n" >> "$CALL_LOG"\nexit 0\n'
    )
    binary.chmod(0o700)


def test_a_display_library_that_could_not_be_written_back_keeps_its_backup(local_device):
    env = local_device
    library = Path(env["C300X_BACKUP_ROOT"], "original/usr/lib/libQtGuiE.so.4.8.7")
    library.parent.mkdir(parents=True)
    library.write_text("stock\n")
    _display_library_restore(env, '{"ok":false,"error":"remount_rw_failed"}')

    result = subprocess.run(["sh", str(REMOVE), "--run-from-tmp"], env=env,
                            capture_output=True, text=True, timeout=10)

    assert result.returncode != 0
    assert "keeping agent files and backups" in result.stderr
    assert library.read_text() == "stock\n"
    assert Path(env["C300X_AGENT_DIR"]).is_dir()
    # Still before the agent is stopped: it keeps running as it was.
    assert Path(env["C300X_INIT_SCRIPT"]).is_file()
    assert "reboot" not in Path(env["CALL_LOG"]).read_text().splitlines()


def test_a_display_library_without_a_valid_backup_does_not_block_the_removal(local_device):
    env = local_device
    _display_library_restore(env, '{"ok":false,"error":"touch_backup_invalid"}')

    result = subprocess.run(["sh", str(REMOVE), "--run-from-tmp"], env=env,
                            capture_output=True, text=True, timeout=10)

    assert result.returncode == 0, result.stderr
    assert "wider tap tolerance" in result.stderr
    assert not Path(env["C300X_AGENT_DIR"]).exists()
