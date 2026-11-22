"""Actual removal, generated payload and firmware-copy display restoration."""

from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from test_native_agent_removal import (  # noqa: F401
    ROOT, device, removal_binary, _remove, _assert_kept, _assert_removed,
)
from test_native_routing_firmware_restore import FIRMWARE_ROOT, original

sys.path.insert(0, str(ROOT / "scripts"))
from c100x_bundle_builder import build  # noqa: E402


@pytest.fixture
def c100x(device, tmp_path):
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
