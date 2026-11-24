"""Agent removal with the real script and CLI on C300X 1.7.19/2.0.2 and C100X 1.5.8 routing copies.

Device commands are stand-ins. Firmware roots are read-only inputs; every
modified executable and backup is temporary.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
from test_native_agent_removal import ROOT, _assert_kept, _assert_removed, _remove
from test_native_agent_removal import device as device
from test_native_routing_firmware_restore import (
    FIRMWARE_ROOT,
    PATCH_OFFSETS,
    original,
    routing_run,
)
from test_native_routing_firmware_restore import routing_binary as routing_binary

C300X_FIRMWARES = ("1.7.19", "2.0.2")
C100X_FIRMWARE = "c100x-1.5.8"
FIRMWARES = (*C300X_FIRMWARES, C100X_FIRMWARE)
FAULTS = (
    "corrupt_backup", "foreign_model", "foreign_firmware", "missing_backup",
    "unknown_target", "missing_target", "target_symlink", "backup_symlink", "remount",
)


@pytest.fixture(scope="module")
def removal_binary(tmp_path_factory):
    """The agent with the real stock routing identities."""
    build = tmp_path_factory.mktemp("stock-removal-build")
    result = subprocess.run([
        "make", "-C", str(ROOT / "native_agent"), f"BUILD_DIR={build}", "-j2", "all",
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return build / "host/c300x-agent-native"


def _patched_device(env, routing_binary, firmware):
    target = Path(env["C300X_ROUTING_TARGET_DIR"], "bt_answering_machine")
    backup = Path(env["C300X_ROUTING_BACKUP_DIR"], "bt_answering_machine")
    backup.parent.mkdir(parents=True)
    shutil.copy2(original(firmware), target)
    target.chmod(0o751)
    applied = routing_run(routing_binary, target, backup, "apply")
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert target.read_bytes() != backup.read_bytes()
    env["GUI_CALL_LOG"] = str(target.parent / "gui-calls")
    if firmware == C100X_FIRMWARE:
        env["C100X_GUI_DIR"] = env["C300X_QML_GUI_DIR"]
        gui_source = FIRMWARE_ROOT / "rootfs-c100x-1.5.8/home/bticino/bin/gui/skins/default"
        for name in ("main.qml", "MainPage.qml", "EventManager.qml"):
            shutil.copy2(gui_source / name, Path(env["C300X_QML_GUI_DIR"]) / name)
        env["C300X_QML_C100X_MARKER"] = str(
            FIRMWARE_ROOT / "rootfs-c100x-1.5.8/home/bticino/bin/gui/BtClass100"
        )
        # Exact stock C100X files need no payload or Qt4 patch-script calls.
        script = target.parent / "qml-not-supported"
        script.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$GUI_CALL_LOG"\nexit 99\n')
        script.chmod(0o700)
        env["C300X_QML_PATCH_SCRIPT"] = str(script)
    return target, backup


@pytest.mark.parametrize("firmware", FIRMWARES)
@pytest.mark.parametrize("state", ["patched", "stock", "stock_stale_backup", "partial"])
def test_removal_restores_verified_original(device, routing_binary, firmware, state):
    target, backup = _patched_device(device, routing_binary, firmware)
    stock = original(firmware).read_bytes()
    if state in {"stock", "stock_stale_backup"}:
        target.write_bytes(stock)
        if state == "stock":
            backup.unlink()
        else:
            backup.write_bytes(b"old unusable backup")
    elif state == "partial":
        data = bytearray(target.read_bytes())
        data[PATCH_OFFSETS[firmware]] ^= 1
        target.write_bytes(data)
    result = _remove(device)
    _assert_removed(device, result)
    assert target.read_bytes() == stock
    assert target.stat().st_mode & 0o7777 == 0o751
    assert not list(target.parent.glob("*.restore.*"))
    if firmware == C100X_FIRMWARE:
        assert not Path(device["GUI_CALL_LOG"]).exists()


@pytest.mark.parametrize(("firmware", "fault"), [
    (firmware, fault)
    for firmware in FIRMWARES
    for fault in FAULTS
    # The C100X has a single supported firmware.
    if not (firmware == C100X_FIRMWARE and fault == "foreign_firmware")
])
def test_failed_removal_keeps_native_agent_and_backups(device, routing_binary, firmware, fault):
    target, backup = _patched_device(device, routing_binary, firmware)
    if fault == "corrupt_backup":
        backup.write_bytes(b"\0" + backup.read_bytes()[1:])
    elif fault == "foreign_model":
        shutil.copy2(original("2.0.2" if firmware == C100X_FIRMWARE else C100X_FIRMWARE), backup)
    elif fault == "foreign_firmware":
        shutil.copy2(original(C300X_FIRMWARES[1 - C300X_FIRMWARES.index(firmware)]), backup)
    elif fault == "missing_backup":
        backup.unlink()
    elif fault == "unknown_target":
        target.write_bytes(b"\0" + target.read_bytes()[1:])
    elif fault == "missing_target":
        target.unlink()
    elif fault.endswith("symlink"):
        path = target if fault == "target_symlink" else backup
        sentinel = path.with_suffix(".sentinel")
        path.rename(sentinel)
        path.symlink_to(sentinel)
    else:
        device["C300X_DEVICE_PATCH_NO_REMOUNT"] = "ro_busy"
    before = target.read_bytes() if target.exists() else None
    saved = backup.read_bytes() if backup.exists() else None
    result = _remove(device)
    _assert_kept(device, result)
    assert "Failed to restore device routing" in result.stderr
    assert (backup.read_bytes() if backup.exists() else None) == saved
    assert (target.read_bytes() if target.exists() else None) == (saved if fault == "remount" else before)
    if firmware == C100X_FIRMWARE:
        assert not Path(device["GUI_CALL_LOG"]).exists()
    if fault == "remount":
        # A failed remount leaves a verified target and retryable uninstall.
        device["C300X_DEVICE_PATCH_NO_REMOUNT"] = "1"
        _assert_removed(device, _remove(device))
