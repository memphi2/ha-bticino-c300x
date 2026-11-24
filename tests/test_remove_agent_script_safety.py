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
    assert Path(env["CALL_LOG"]).read_text().splitlines() == ["ssh-init", "pidof"]
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


@pytest.mark.parametrize("state", ["signal_failed", "ignores_term", "slow_exit", "exit_race",
                                   "probe_failed", "probe_inconsistent", "probe_missing",
                                   "probe_after_term", "probe_stderr", "sleep_failed"])
def test_stop_is_verified_before_any_restoration(local_device, tmp_path, state):
    env = local_device
    label_patch(env)
    before = _startup_entries(env, tmp_path, "relative")
    popup = Path(env["C300X_QML_GUI_DIR"], "Components/Settings/CallBlockPopup.qml")
    patched = popup.read_bytes()
    env["STOP_STATE"] = state
    pidof = tmp_path / "commands/pidof"
    pidof.write_text('''#!/bin/sh
printf 'pidof\\n' >> "$CALL_LOG"
case "$STOP_STATE" in
    probe_failed) exit 2 ;;
    probe_missing) exit 127 ;;
    probe_stderr) printf 'Cannot read process table\\n' >&2; exit 1 ;;
    probe_inconsistent) printf '12345\\n'; exit 1 ;;
    probe_after_term) ! grep -q '^killall$' "$CALL_LOG" || exit 2 ;;
    slow_exit) [ "$(grep -c '^sleep$' "$CALL_LOG")" -lt 2 ] || exit 1 ;;
    exit_race) ! grep -q '^killall$' "$CALL_LOG" || exit 1 ;;
esac
printf '12345\\n'
exit 0
''')
    killall = tmp_path / "commands/killall"
    killall.write_text('''#!/bin/sh
printf 'killall\\n' >> "$CALL_LOG"
case "$STOP_STATE" in signal_failed|exit_race) exit 1;; esac
exit 0
''')
    sleep = tmp_path / "commands/sleep"
    sleep.write_text('#!/bin/sh\nprintf "sleep\\n" >> "$CALL_LOG"\n'
                     '[ "$STOP_STATE" != sleep_failed ]\n')
    for path in (pidof, killall, sleep):
        path.chmod(0o700)
    Path(env["CALL_LOG"]).write_text("")
    result = subprocess.run(["sh", str(REMOVE), "remove"], env=env,
                            capture_output=True, text=True, timeout=10)
    calls = Path(env["CALL_LOG"]).read_text().splitlines()
    if state in {"slow_exit", "exit_race"}:
        assert result.returncode == 0, result.stderr
        assert calls.index("killall") < calls.index("media-restore")
        assert calls.index("pidof") < calls.index("mount")
        assert calls.count("sleep") == (2 if state == "slow_exit" else 0)
        assert popup.read_text() == ORIGINAL_CALL_BLOCK_POPUP
    else:
        assert result.returncode == 1, result.stderr
        assert "Cannot verify agent termination" in result.stderr
        assert popup.read_bytes() == patched
        assert {path: _startup_state(path) for path in before} == before
        assert Path(env["C300X_AGENT_DIR"]).is_dir()
        assert Path(env["C300X_BACKUP_ROOT"]).is_dir()
        assert not {"mount", "media-restore", "reboot"}.intersection(calls)
        assert calls.count("sleep") == {"ignores_term": 10, "sleep_failed": 1}.get(state, 0)
    assert not list(Path(env["TMPDIR"]).iterdir())


@pytest.mark.parametrize("damage", ["none", "config", "qml", "mode", "link", "content",
                                    "hidden", "backup_only", "agent_all", "all", "silent", "signal",
                                    "directory", "added", "identity_error"])
def test_final_delete_failure_retains_startup_recovery(local_device, tmp_path, damage):
    env = local_device
    before = _startup_entries(env, tmp_path, "relative")
    agent = Path(env["C300X_AGENT_DIR"])
    (agent / "config.json").write_text('{"enabled":true}\n')
    (agent / "qml").mkdir()
    (agent / "qml/page.qml").write_text("Item {}\n")
    (agent / ".hidden").write_text("retained\n")
    (agent / "empty-dir").mkdir()
    (agent / "config-link").symlink_to("config.json")
    remove = shutil.which("rm")
    mutation = {
        "none": ":", "config": f'"{remove}" -f "$2/config.json"',
        "qml": f'"{remove}" -f "$2/qml/page.qml"',
        "mode": 'chmod 600 "$2/c300x-agent-native"',
        "link": f'"{remove}" -f "$2/config-link"; ln -s .hidden "$2/config-link"',
        "content": 'printf changed > "$2/config.json"',
        "hidden": f'"{remove}" -f "$2/.hidden"',
        "directory": 'rmdir "$2/empty-dir"',
        "added": 'printf unexpected > "$2/added"',
        "identity_error": 'touch "$IDENTITY_ERROR"',
        "backup_only": f'"{remove}" -rf "$3"',
        "agent_all": f'"{remove}" -rf "$2"',
        "all": f'"{remove}" -rf "$2" "$3"',
        "silent": ":", "signal": f'"{remove}" -f "$2/config.json"; kill -TERM "$PPID"',
    }[damage]
    env["IDENTITY_ERROR"] = str(tmp_path / "identity-error")
    if damage == "identity_error":
        _command_double(tmp_path, "sha256sum", '[ ! -f "$IDENTITY_ERROR" ] || exit 1')
    _command_double(tmp_path, "rm", f'''
if [ "${{2:-}}" = "$C300X_AGENT_DIR" ] && [ "${{3:-}}" = "$C300X_BACKUP_ROOT" ]; then
    {mutation}
    exit {0 if damage == "silent" else 1}
fi''')
    result = subprocess.run(["sh", str(REMOVE), "remove"], env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == (130 if damage == "signal" else 1), result.stderr
    intact = damage in {"none", "backup_only", "silent"}
    for key in ("C300X_INIT_SCRIPT", "C300X_INIT_LINK"):
        assert _startup_state(Path(env[key])) == (before[Path(env[key])] if intact else None)
    workspaces = list(Path(env["TMPDIR"]).iterdir())
    assert len(workspaces) == 1
    for name, key in (("script", "C300X_INIT_SCRIPT"), ("link", "C300X_INIT_LINK")):
        assert _startup_state(workspaces[0] / "startup" / name) == before[Path(env[key])]
    assert str(workspaces[0]) in result.stderr
    if not intact:
        assert "Agent tree changed or cannot be verified" in result.stderr
        assert "Repair the agent installation before restoring startup" in result.stderr
    assert "reboot" not in Path(env["CALL_LOG"]).read_text().splitlines()


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


@pytest.mark.parametrize("family", ["ipv4", "ipv6"])
@pytest.mark.parametrize("backup_text", ["#!/bin/sh\n# Firmware ru", "", "#!/bin/sh\niptables -P INPUT ACCEPT\n"])
def test_an_unverified_firewall_backup_never_replaces_the_live_rules(local_device, family, backup_text):
    """A partial or stale backup (an interrupted old install) must not wipe the
    stock rules: removal strips the agent block from the live file instead."""
    env = local_device
    target, backup, original = _firewall_fixture(env, family, True)
    backup.write_text(backup_text)

    result = subprocess.run(["sh", str(REMOVE), "--run-from-tmp"], env=env,
                            capture_output=True, text=True, timeout=10)

    assert result.returncode == 0, result.stderr
    assert target.read_text() == original
    assert "does not match the stock rules" in result.stderr


def test_removal_strips_both_agent_blocks_from_the_live_file(local_device):
    env = local_device
    target, _backup, original = _firewall_fixture(env, "ipv4", True)
    target.write_text(original + "# c300x-native-agent ipv6 firewall begin\nip6tables -A INPUT\n"
                      "# c300x-native-agent ipv6 firewall end\n" + target.read_text()[len(original):])

    result = subprocess.run(["sh", str(REMOVE), "--run-from-tmp"], env=env,
                            capture_output=True, text=True, timeout=10)

    assert result.returncode == 0, result.stderr
    assert target.read_text() == original
    assert "does not match" not in result.stderr


@pytest.mark.parametrize("backed_up", [False, True])
def test_an_unterminated_agent_block_keeps_everything(local_device, backed_up):
    env = local_device
    target, _backup, original = _firewall_fixture(env, "ipv4", backed_up)
    damaged = original + "# c300x-native-agent firewall begin\n# Agent rules\niptables -A INPUT -p tcp --dport 22 -j ACCEPT\n"
    target.write_text(damaged)

    result = subprocess.run(["sh", str(REMOVE), "--run-from-tmp"], env=env,
                            capture_output=True, text=True, timeout=10)

    assert result.returncode == 1
    assert target.read_text() == damaged
    assert Path(env["C300X_AGENT_DIR"]).is_dir()
    assert Path(env["C300X_BACKUP_ROOT"]).is_dir()
    assert "reboot" not in Path(env["CALL_LOG"]).read_text().splitlines()


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
    if failure.startswith("ro_") and phase == "firewall":
        assert calls[-2:] == ["mount -o remount,ro /", "mount -o remount,ro /"]
    assert Path(env["C300X_INIT_SCRIPT"]).is_file()
    assert Path(env["C300X_INIT_LINK"]).is_file()
    assert not list(Path(env["TMPDIR"]).iterdir())


def _startup_state(path):
    if not path.exists() and not path.is_symlink():
        return None
    info = path.lstat()
    return (os.readlink(path) if path.is_symlink() else path.read_bytes(),
            info.st_mode, info.st_uid, info.st_gid, info.st_mtime_ns)


def _startup_entries(env, tmp_path, kind):
    script = Path(env["C300X_INIT_SCRIPT"])
    link = Path(env["C300X_INIT_LINK"])
    script.chmod(0o751)
    link.chmod(0o640)
    referent = tmp_path / "untouched-startup-referent"
    referent.write_text("#!/bin/sh\n# retained original\n")
    referent.chmod(0o750)
    if kind != "regular":
        link.unlink()
        if kind == "relative":
            link.symlink_to(script.name)
        elif kind == "absolute":
            link.symlink_to(script)
        elif kind == "dangling":
            link.symlink_to("not-installed")
        elif kind == "both_symlinks":
            script.unlink()
            script.symlink_to(referent)
            link.symlink_to(script.name)
        elif kind == "absent":
            script.unlink()
    return {path: _startup_state(path) for path in (script, link, referent)}


def _startup_failure(env, tmp_path, failure):
    env["STARTUP_RO_MARK"] = str(tmp_path / "startup-ro-failed")
    env["STARTUP_FAILURE"] = failure
    mount = tmp_path / "commands/mount"
    mount.write_text('''#!/bin/sh
printf 'mount %s\\n' "$*" >> "$CALL_LOG"
if grep -q '^media-restore$' "$CALL_LOG"; then
    case "$STARTUP_FAILURE:$*" in
        ro_always:*remount,ro*|rollback_rw:*remount,ro*)
            touch "$STARTUP_RO_MARK"; exit 1 ;;
        ro_once:*remount,ro*)
            if [ ! -f "$STARTUP_RO_MARK" ]; then touch "$STARTUP_RO_MARK"; exit 1; fi ;;
        rollback_rw:*remount,rw*) [ ! -f "$STARTUP_RO_MARK" ] || exit 1 ;;
    esac
fi
exit 0
''')
    mount.chmod(0o700)
    if failure in {"partial_remove", "late_remove", "signal", "silent_remove"}:
        finish = 'kill -TERM "$PPID"; exit 1' if failure == "signal" else "exit 73"
        remove = ('"$2"' if failure == "partial_remove" else '"$2" "$3"')
        body = "exit 0" if failure == "silent_remove" else f'"{shutil.which("rm")}" -f {remove}\n{finish}'
        _command_double(tmp_path, "rm", f'''
if [ "${{2:-}}" = "$C300X_INIT_LINK" ]; then
    {body}
fi''')


@pytest.mark.parametrize("kind,failure", [
    (kind, failure)
    for kind in ("regular", "relative", "absolute", "dangling", "both_symlinks", "absent")
    for failure in ("ro_once", "ro_always", "partial_remove", "late_remove", "signal", "silent_remove")
    if (kind, failure) != ("absent", "silent_remove")
])
def test_startup_rollback_preserves_exact_entries_and_never_reboots(local_device, tmp_path, kind, failure):
    env = local_device
    before = _startup_entries(env, tmp_path, kind)
    _startup_failure(env, tmp_path, failure)
    result = subprocess.run(["sh", str(REMOVE), "remove"], env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == (130 if failure == "signal" else 1), result.stderr
    assert {path: _startup_state(path) for path in before} == before
    assert Path(env["C300X_AGENT_DIR"]).is_dir()
    assert Path(env["C300X_BACKUP_ROOT"]).is_dir()
    assert "reboot" not in Path(env["CALL_LOG"]).read_text().splitlines()
    assert "Original startup entries restored" in result.stderr
    if failure.startswith("ro_"):
        assert "full device reboot before retrying removal" in result.stderr
    assert not list(Path(env["TMPDIR"]).iterdir())
    assert not list(tmp_path.glob("*.c300x-startup.*"))


@pytest.mark.parametrize("entry", ["C300X_INIT_SCRIPT", "C300X_INIT_LINK"])
@pytest.mark.parametrize("failure", ["copy", "silent_corruption", "wrong_mode", "stat", "directory", "fifo"])
def test_startup_backup_failure_never_deletes_live_entries(local_device, tmp_path, entry, failure):
    env = local_device
    target = Path(env[entry])
    if failure in {"directory", "fifo"}:
        target.unlink()
        if failure == "directory":
            target.mkdir()
        else:
            os.mkfifo(target)
        before = target.lstat()
    else:
        before = _startup_entries(env, tmp_path, "regular")
        env["FAIL_STARTUP_SOURCE"] = str(target)
        if failure == "stat":
            _command_double(tmp_path, "stat", '''
if [ "${3:-}" = "$FAIL_STARTUP_SOURCE" ]; then exit 1; fi''')
        else:
            body = {"copy": "exit 1", "silent_corruption": 'printf broken > "$3"; exit 0',
                    "wrong_mode": f'"{shutil.which("cp")}" "$@"; chmod 600 "$3"; exit 0'}[failure]
            _command_double(tmp_path, "cp", f'''
if [ "${{1:-}}" = -a ] && [ "${{2:-}}" = "$FAIL_STARTUP_SOURCE" ]; then {body}; fi''')
    result = subprocess.run(["sh", str(REMOVE), "--run-from-tmp"], env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 1, result.stderr
    if failure in {"directory", "fifo"}:
        assert target.lstat() == before
    else:
        assert {path: _startup_state(path) for path in before} == before
    assert Path(env["C300X_AGENT_DIR"]).exists()
    assert Path(env["C300X_BACKUP_ROOT"]).exists()
    assert "reboot" not in Path(env["CALL_LOG"]).read_text().splitlines()
    assert not list(Path(env["TMPDIR"]).iterdir())


@pytest.mark.parametrize("failure", ["copy", "silent_corruption", "rename", "rollback_rw"])
def test_failed_startup_rollback_keeps_verified_private_recovery(local_device, tmp_path, failure):
    env = local_device
    before = _startup_entries(env, tmp_path, "relative")
    _startup_failure(env, tmp_path, "rollback_rw" if failure == "rollback_rw" else "ro_always")
    if failure in {"copy", "silent_corruption"}:
        body = "exit 1" if failure == "copy" else 'printf broken > "$3"; exit 0'
        _command_double(tmp_path, "cp", f'''
case "${{2:-}}" in */startup/script) {body};; esac''')
    elif failure == "rename":
        _command_double(tmp_path, "mv", '''
case "${2:-}" in *.c300x-startup.*/entry) exit 1;; esac''')
    result = subprocess.run(["sh", str(REMOVE), "remove"], env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert "Startup rollback failed" in result.stderr
    assert "Do not reboot" in result.stderr
    workspaces = list(Path(env["TMPDIR"]).iterdir())
    assert len(workspaces) == 1
    assert workspaces[0].stat().st_mode & 0o777 == 0o700
    for name, key in (("script", "C300X_INIT_SCRIPT"), ("link", "C300X_INIT_LINK")):
        assert _startup_state(workspaces[0] / "startup" / name) == before[Path(env[key])]
    assert Path(env["C300X_AGENT_DIR"]).exists()
    assert Path(env["C300X_BACKUP_ROOT"]).exists()
    assert "reboot" not in Path(env["CALL_LOG"]).read_text().splitlines()


@pytest.mark.parametrize("kind", ["regular", "relative", "absolute", "dangling", "both_symlinks", "absent"])
def test_successful_startup_removal_keeps_symlink_referents_untouched(local_device, tmp_path, kind):
    env = local_device
    before = _startup_entries(env, tmp_path, kind)
    result = subprocess.run(["sh", str(REMOVE), "remove"], env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    for key in ("C300X_INIT_SCRIPT", "C300X_INIT_LINK"):
        assert _startup_state(Path(env[key])) is None
    referent = tmp_path / "untouched-startup-referent"
    assert _startup_state(referent) == before[referent]
    assert not Path(env["C300X_AGENT_DIR"]).exists()
    assert not Path(env["C300X_BACKUP_ROOT"]).exists()
    assert "reboot" in Path(env["CALL_LOG"]).read_text().splitlines()
    assert not list(Path(env["TMPDIR"]).iterdir())


def _media_restore_result(env, output, status=0):
    binary = Path(env["C300X_AGENT_DIR"], "c300x-agent-native")
    env["MEDIA_RESULT"] = output
    env["MEDIA_STATUS"] = str(status)
    binary.write_text('''#!/bin/sh
if [ "$1" = --display-touch ]; then printf '%s\\n' '{"ok":true}'; exit 0; fi
printf 'media-restore\\n' >> "$CALL_LOG"
printf '%s\\n' "$MEDIA_RESULT"
exit "$MEDIA_STATUS"
''')
    binary.chmod(0o700)


@pytest.mark.parametrize("output,status", [
    ('{"ok":true,"media_reboot_required":true}', 1),
    ('{"ok":false,"media_reboot_required":true}', 0),
    ('{"ok":true,"media_reboot_required":"true"}', 0),
    ('{"ok":true,"media_reboot_required":1}', 0),
    ('{"ok":true,"media_reboot_required":true,"error":"failed"}', 0),
    ('{"ok":true,"media_reboot_required":true}\n{"ok":false}', 0),
    ('not-json {"ok":true,"media_reboot_required":true}', 0),
    ('{"ok":true}', 0),
])
def test_unverified_pending_reboot_result_never_deletes_startup(local_device, tmp_path, output, status):
    env = local_device
    before = _startup_entries(env, tmp_path, "relative")
    _media_restore_result(env, output, status)
    result = subprocess.run(["sh", str(REMOVE), "remove"], env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert {path: _startup_state(path) for path in before} == before
    assert Path(env["C300X_BACKUP_ROOT"]).exists()
    assert Path(env["C300X_AGENT_DIR"]).exists()
    assert "reboot" not in Path(env["CALL_LOG"]).read_text().splitlines()


@pytest.mark.parametrize("output", ['', '{"ok":true,"media_reboot_required":false}'])
def test_legacy_or_false_pending_flag_never_excuses_busy_ro(local_device, tmp_path, output):
    env = local_device
    before = _startup_entries(env, tmp_path, "relative")
    _media_restore_result(env, output)
    _startup_failure(env, tmp_path, "ro_always")
    result = subprocess.run(["sh", str(REMOVE), "remove"], env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert {path: _startup_state(path) for path in before} == before
    assert Path(env["C300X_BACKUP_ROOT"]).exists()
    assert "full device reboot before retrying removal" in result.stderr
    assert "reboot" not in Path(env["CALL_LOG"]).read_text().splitlines()


@pytest.mark.parametrize("busy", [False, True])
def test_verified_pending_flag_explains_busy_abort_without_bypassing_rollback(local_device, tmp_path, busy):
    env = local_device
    before = _startup_entries(env, tmp_path, "relative")
    _media_restore_result(env, '{"ok":true,"media_reboot_required":true}')
    if busy:
        _startup_failure(env, tmp_path, "ro_always")
    reboot = tmp_path / "commands/reboot"
    # Successful removal keeps the existing cleanup-before-reboot ordering.
    reboot.write_text('''#!/bin/sh
[ ! -e "$C300X_BACKUP_ROOT" ] && [ ! -e "$C300X_AGENT_DIR" ] || exit 81
printf 'reboot\\n' >> "$CALL_LOG"
exit 0
''')
    reboot.chmod(0o700)
    result = subprocess.run(["sh", str(REMOVE), "remove"], env=env,
                            capture_output=True, text=True, timeout=10)
    calls = Path(env["CALL_LOG"]).read_text().splitlines()
    if busy:
        assert result.returncode == 1
        assert {path: _startup_state(path) for path in before} == before
        assert Path(env["C300X_BACKUP_ROOT"]).exists()
        assert Path(env["C300X_AGENT_DIR"]).exists()
        assert "full device reboot before retrying removal" in result.stderr
        assert "patched media process is still running" in result.stderr
        assert "reboot" not in calls
    else:
        assert result.returncode == 0, result.stderr
        assert not Path(env["C300X_BACKUP_ROOT"]).exists()
        assert not Path(env["C300X_AGENT_DIR"]).exists()
        assert not Path(env["C300X_INIT_SCRIPT"]).exists()
        assert not Path(env["C300X_INIT_LINK"]).is_symlink()
        assert calls.count("reboot") == 1
    assert not list(Path(env["TMPDIR"]).iterdir())


@pytest.mark.parametrize("pending", [False, True])
def test_busy_abort_can_be_retried_once_ro_is_available(local_device, tmp_path, pending):
    env = local_device
    before = _startup_entries(env, tmp_path, "relative")
    _media_restore_result(env, '{"ok":true,"media_reboot_required":' + str(pending).lower() + '}')
    _startup_failure(env, tmp_path, "ro_always")
    first = subprocess.run(["sh", str(REMOVE), "remove"], env=env,
                           capture_output=True, text=True, timeout=10)
    assert first.returncode == 1, first.stderr
    assert "Original startup entries restored" in first.stderr
    assert "full device reboot before retrying removal" in first.stderr
    assert {path: _startup_state(path) for path in before} == before
    assert Path(env["C300X_AGENT_DIR"]).is_dir()
    assert Path(env["C300X_BACKUP_ROOT"]).is_dir()
    assert "reboot" not in Path(env["CALL_LOG"]).read_text().splitlines()

    # Model the post-reboot conditions only; this test never reboots a device.
    env["STARTUP_FAILURE"] = ""
    _media_restore_result(env, '{"ok":true,"media_reboot_required":false}')
    second = subprocess.run(["sh", str(REMOVE), "remove"], env=env,
                            capture_output=True, text=True, timeout=10)
    assert second.returncode == 0, second.stderr
    for key in ("C300X_AGENT_DIR", "C300X_BACKUP_ROOT", "C300X_INIT_SCRIPT", "C300X_INIT_LINK"):
        assert not Path(env[key]).exists()
        assert not Path(env[key]).is_symlink()
    referent = tmp_path / "untouched-startup-referent"
    assert _startup_state(referent) == before[referent]
    assert Path(env["CALL_LOG"]).read_text().splitlines().count("reboot") == 1
    assert not list(Path(env["TMPDIR"]).iterdir())


@pytest.mark.parametrize("failure", ["partial_remove", "rollback_rw", "initial_rw"])
def test_pending_reboot_does_not_excuse_other_failures(local_device, tmp_path, failure):
    env = local_device
    before = _startup_entries(env, tmp_path, "relative")
    _media_restore_result(env, '{"ok":true,"media_reboot_required":true}')
    _startup_failure(env, tmp_path, failure if failure in {"partial_remove", "rollback_rw"} else "ro_always")
    if failure == "initial_rw":
        mount = tmp_path / "commands/mount"
        mount.write_text('''#!/bin/sh
printf 'mount %s\\n' "$*" >> "$CALL_LOG"
if grep -q '^media-restore$' "$CALL_LOG" && [ "$2" = remount,rw ]; then exit 1; fi
exit 0
''')
        mount.chmod(0o700)
    result = subprocess.run(["sh", str(REMOVE), "remove"], env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert Path(env["C300X_AGENT_DIR"]).exists()
    assert Path(env["C300X_BACKUP_ROOT"]).exists()
    if failure != "rollback_rw":
        assert {path: _startup_state(path) for path in before} == before
        assert not list(Path(env["TMPDIR"]).iterdir())
    else:
        assert "Startup rollback failed" in result.stderr
        assert list(Path(env["TMPDIR"]).glob("*/startup/script"))
    assert "reboot" not in Path(env["CALL_LOG"]).read_text().splitlines()


def _original_busybox(firmware):
    root = REMOVE.parents[2].parent / "c300x-fwpatch/work" / f"rootfs-{firmware}"
    busybox = root / "bin/busybox"
    qemu = shutil.which("qemu-arm")
    if not qemu or not busybox.exists():
        pytest.skip("Optional local original firmware and qemu-arm are unavailable")
    return [qemu, "-L", str(root), str(busybox)]


def _use_original_file_tools(tmp_path, firmware):
    qemu, _, root, busybox = _original_busybox(firmware)
    for name in ("cp", "stat", "cmp", "readlink", "mv", "sha256sum"):
        wrapper = tmp_path / "commands" / name
        wrapper.write_text(f'#!/bin/sh\nexec "{qemu}" -L "{root}" "{busybox}" {name} "$@"\n')
        wrapper.chmod(0o700)


@pytest.mark.parametrize("firmware", ["1.7.19", "3.0.6"])
def test_original_firmware_busybox_preserves_startup_metadata(local_device, tmp_path, firmware):
    env = local_device
    before = _startup_entries(env, tmp_path, "relative")
    _startup_failure(env, tmp_path, "ro_always")
    _use_original_file_tools(tmp_path, firmware)
    result = subprocess.run(["sh", str(REMOVE), "remove"], env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 1, result.stderr
    assert "Original startup entries restored" in result.stderr
    # Firmware cp -a preserves regular-file mtime to whole seconds, but creates
    # symlinks with a new timestamp. Their target, mode and owner must be exact.
    for path, expected in before.items():
        actual = _startup_state(path)
        assert actual[:4] == expected[:4]
        if not path.is_symlink():
            assert actual[4] // 1_000_000_000 == expected[4] // 1_000_000_000
    assert not list(Path(env["TMPDIR"]).iterdir())


@pytest.mark.parametrize("firmware", ["1.7.19", "3.0.6"])
@pytest.mark.parametrize("partial", [False, True])
def test_original_firmware_tools_validate_post_delete_identity(local_device, tmp_path, firmware, partial):
    env = local_device
    before = _startup_entries(env, tmp_path, "relative")
    agent = Path(env["C300X_AGENT_DIR"])
    (agent / "qml").mkdir()
    (agent / "qml/page.qml").write_text("Item {}\n")
    (agent / ".config\nbackup").write_text("original\n")
    (agent / "config-link").symlink_to(".config\nbackup")
    _use_original_file_tools(tmp_path, firmware)
    mutation = 'printf changed > "$2/qml/page.qml"' if partial else ":"
    _command_double(tmp_path, "rm", f'''
if [ "${{2:-}}" = "$C300X_AGENT_DIR" ] && [ "${{3:-}}" = "$C300X_BACKUP_ROOT" ]; then
    {mutation}
    exit 1
fi''')
    result = subprocess.run(["sh", str(REMOVE), "remove"], env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 1, result.stderr
    for key in ("C300X_INIT_SCRIPT", "C300X_INIT_LINK"):
        actual = _startup_state(Path(env[key]))
        if partial:
            assert actual is None
        else:
            assert actual[:4] == before[Path(env[key])][:4]
    assert len(list(Path(env["TMPDIR"]).glob("*/startup/script"))) == 1
    assert "reboot" not in Path(env["CALL_LOG"]).read_text().splitlines()


@pytest.mark.parametrize("firmware", ["1.7.19", "3.0.6"])
def test_original_busybox_pidof_matches_long_agent_name(tmp_path, firmware):
    busybox = _original_busybox(firmware)
    syntax = subprocess.run([*busybox, "sh", "-n", str(REMOVE)], capture_output=True, timeout=10)
    assert syntax.returncode == 0, syntax.stderr
    # A full extracted root redirects /proc to its empty directory under QEMU.
    # Retain the real firmware libraries without hiding the host process table.
    prefix = tmp_path / "loader-root"
    prefix.mkdir()
    (prefix / "lib").symlink_to(Path(busybox[2]) / "lib", target_is_directory=True)
    busybox[2] = str(prefix)
    # Only this local sleep process is created/terminated; no real agent is signalled.
    executable = tmp_path / "c300x-agent-native"
    compiler = shutil.which("cc")
    if not compiler:
        pytest.skip("Local C compiler is unavailable")
    built = subprocess.run([compiler, "-x", "c", "-o", str(executable), "-"],
                           input="#include <unistd.h>\nint main(void) { sleep(30); return 0; }\n",
                           capture_output=True, text=True, timeout=20)
    assert built.returncode == 0, built.stderr
    process = subprocess.Popen([str(executable)])
    try:
        result = subprocess.run([*busybox, "pidof", executable.name],
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        assert str(process.pid) in result.stdout.split()
    finally:
        process.terminate()
        process.wait(timeout=10)
    result = subprocess.run([*busybox, "pidof", "c300x-removal-no-such-process"],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert result.stdout == ""


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
    # The agent was stopped before restoration, but remains installed.
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
