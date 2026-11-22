"""Actual removal, generated payload and firmware-copy display restoration."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from test_native_agent_removal import (  # noqa: F401
    ROOT,
    _assert_kept,
    _assert_removed,
    _remove,
    device,
    removal_binary,
)
from test_native_routing_firmware_restore import FIRMWARE_ROOT, original

sys.path.insert(0, str(ROOT / "scripts"))
from c100x_bundle_builder import build  # noqa: E402


@pytest.fixture
def c100x(device, tmp_path):  # noqa: F811 - imported pytest fixture
    original("c100x-1.5.8")
    firmware = FIRMWARE_ROOT / "rootfs-c100x-1.5.8/home/bticino"
    gui = Path(device["C300X_QML_GUI_DIR"])
    stock = {}
    for name in ("main.qml", "MainPage.qml", "EventManager.qml"):
        shutil.copyfile(firmware / "bin/gui/skins/default" / name, gui / name)
        (gui / name).chmod(0o640)
        stock[name] = (gui / name).read_bytes()
    binary, wrapper = tmp_path / "BtClass100", tmp_path / "BtClass100_qws"
    shutil.copyfile(firmware / "bin/gui/BtClass100", binary)
    shutil.copyfile(firmware / "bin/BtClass100_qws", wrapper)
    payload = build(Path(device["C300X_AGENT_DIR"]) / "qml/c100x_bundle.sh")
    sync = tmp_path / "commands/sync"
    sync.write_text('#!/bin/sh\nprintf "sync\\n" >> "$TEST_COMMAND_LOG"\n')
    sync.chmod(0o700)
    qt4 = tmp_path / "qt4-forbidden"
    qt4.write_text('#!/bin/sh\nprintf "qt4-forbidden\\n" >> "$TEST_COMMAND_LOG"\nexit 1\n')
    qt4.chmod(0o700)
    env = {**device, "C300X_QML_C100X_MARKER": str(binary), "C100X_GUI_BIN": str(binary),
           "C100X_GUI_WRAPPER": str(wrapper), "C100X_GUI_DIR": str(gui), "C100X_NO_REMOUNT": "1",
           "C100X_BACKUP_DIR": str(Path(device["C300X_BACKUP_ROOT"]) / "c100x-display"),
           "C300X_QML_PATCH_SCRIPT": str(qt4), "TMPDIR": str(tmp_path)}
    return env, payload, gui, stock


def install(c100x):
    env, payload, _, _ = c100x
    result = subprocess.run([str(payload), "apply"], env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def assert_stock(c100x):
    env, _, gui, stock = c100x
    for name, content in stock.items():
        assert (gui / name).read_bytes() == content
        assert (gui / name).stat().st_mode & 0o777 == 0o640
    log = Path(env["TEST_COMMAND_LOG"]).read_text().splitlines()
    assert "qt4-forbidden" not in log and "killall" not in log


@pytest.mark.parametrize("installed", [False, True])
def test_removal_restores_original_display_before_deleting_recovery(c100x, installed):
    env, payload, _, _ = c100x
    if installed:
        install(c100x)
        # Recovery must not need valid current page sources.
        data = payload.read_bytes()
        payload.write_bytes(data.replace(b"property bool c100xFullScreen: true", b"damaged current source"))
    else:
        payload.unlink()  # Clean uninstall of a pre-adapter package.
    result = _remove(env)
    _assert_removed(env, result)
    assert_stock(c100x)


@pytest.mark.parametrize("damage", ["missing-payload", "payload-link", "false-success", "backup", "target", "binary"])
def test_failed_display_restore_preserves_agent_and_recovery_without_reboot(c100x, damage):
    env, payload, gui, _ = c100x
    install(c100x)
    if damage == "missing-payload":
        payload.unlink()
    elif damage == "payload-link":
        moved = payload.with_suffix(".original")
        payload.rename(moved)
        payload.symlink_to(moved)
    elif damage == "false-success":
        payload.write_text('#!/bin/sh\nprintf \'{"ok":true,"state":"stock"}\\n\'\n')
    elif damage == "backup":
        (Path(env["C100X_BACKUP_DIR"]) / "main.qml").write_bytes(b"damaged backup")
    elif damage == "target":
        (gui / "main.qml").write_bytes((gui / "main.qml").read_bytes() + b"unknown edit")
    else:
        Path(env["C100X_GUI_BIN"]).write_bytes(b"damaged GUI binary")
    before = {name: (gui / name).read_bytes() for name in ("main.qml", "MainPage.qml")}
    result = _remove(env)
    _assert_kept(env, result)
    assert "Failed to restore C100X display" in result.stderr
    assert all((gui / name).read_bytes() == data for name, data in before.items())
    assert (Path(env["C100X_BACKUP_DIR"]) / "main.qml").exists()
    log = Path(env["TEST_COMMAND_LOG"]).read_text().splitlines()
    assert "qt4-forbidden" not in log and "killall" not in log and "start-stop-daemon" not in log


def test_unverified_stop_leaves_installed_c100x_display_untouched(c100x, tmp_path):
    env, _, gui, _ = c100x
    install(c100x)
    before = {name: (gui / name).read_bytes() for name in ("main.qml", "MainPage.qml")}
    for command, body in (("pidof", "printf '123\\n'\nexit 0"), ("killall", "exit 1")):
        path = tmp_path / "commands" / command
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o700)
    result = _remove(env)
    _assert_kept(env, result)
    assert "Cannot verify agent termination" in result.stderr
    assert all((gui / name).read_bytes() == data for name, data in before.items())
    assert (Path(env["C100X_BACKUP_DIR"]) / "main.qml").is_file()
    log = Path(env["TEST_COMMAND_LOG"]).read_text().splitlines()
    assert "mount" not in log and "qt4-forbidden" not in log


@pytest.mark.parametrize("partial", [False, True])
def test_c100x_final_cleanup_failure_retains_verified_startup_recovery(c100x, tmp_path, partial):
    env, payload, _, _ = c100x
    install(c100x)
    startup = {key: Path(env[key]).read_bytes() for key in ("C300X_INIT_SCRIPT", "C300X_INIT_LINK")}
    real_rm = shutil.which("rm")
    assert real_rm
    command = tmp_path / "commands/rm"
    command.write_text(
        '#!/bin/sh\nif [ "${2:-}" = "$C300X_AGENT_DIR" ] '
        '&& [ "${3:-}" = "$C300X_BACKUP_ROOT" ]; then\n'
        + ('    printf damaged > "$2/qml/c100x_bundle.sh"\n' if partial else "")
        + f'    exit 1\nfi\nexec "{real_rm}" "$@"\n'
    )
    command.chmod(0o700)
    result = _remove(env)
    assert result.returncode != 0
    assert "Final deletion did not complete" in result.stderr
    assert_stock(c100x)
    assert Path(env["C300X_AGENT_DIR"]).is_dir()
    assert Path(env["C300X_BACKUP_ROOT"]).is_dir()
    for key, content in startup.items():
        path = Path(env[key])
        if partial:
            assert not path.exists()
        else:
            assert path.read_bytes() == content
    recovery = list(tmp_path.glob("c300x-remove-agent.*/startup/script"))
    assert len(recovery) == 1
    assert recovery[0].read_bytes() == startup["C300X_INIT_SCRIPT"]
    if partial:
        assert payload.read_bytes() == b"damaged"
        assert "startup remains disabled" in result.stderr
    assert "reboot" not in Path(env["TEST_COMMAND_LOG"]).read_text().splitlines()
