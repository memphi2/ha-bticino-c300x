"""Actual removal script/CLI on C300X firmware copies, including Qt5 RCC.

Device commands and GUI process presence are stand-ins. Firmware roots are
read-only inputs; all modified QML, executables and backups are temporary.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
from test_native_agent_removal import ROOT, _assert_kept, _assert_removed, _remove
from test_native_agent_removal import device as device
from test_native_routing_firmware_restore import (
    FIRMWARE_ROOT,
    FIRMWARES,
    PATCH_OFFSETS,
    original,
    routing_run,
)
from test_native_routing_firmware_restore import routing_binary as routing_binary


@pytest.fixture(scope="module")
def removal_binary(tmp_path_factory):
    build = tmp_path_factory.mktemp("stock-removal-build")
    result = subprocess.run([
        "make", "-C", str(ROOT / "native_agent"), f"BUILD_DIR={build}", "-j2", "all",
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return build / "host/c300x-agent-native"


def _firmware_device(env, routing_binary, firmware):
    target = Path(env["C300X_ROUTING_TARGET_DIR"], "bt_answering_machine")
    backup = Path(env["C300X_ROUTING_BACKUP_DIR"], "bt_answering_machine")
    backup.parent.mkdir(parents=True)
    shutil.copy2(original(firmware), target)
    target.chmod(0o751)
    applied = routing_run(routing_binary, target, backup, "apply")
    assert applied.returncode == 0, applied.stdout + applied.stderr
    rootfs = FIRMWARE_ROOT / f"rootfs-{firmware}"
    agent = Path(env["C300X_AGENT_DIR"])
    source = agent / "qml"
    shutil.copytree(ROOT / "device_qml", source)
    env["C300X_QML_SOURCE_DIR"] = str(source)
    env["C300X_QML_AGENT_BIN"] = str(agent / "c300x-agent-native")
    env["C300X_QML_QT5_MARKER"] = str(rootfs / "usr/lib/libQt5Core.so.5")
    wrapper = target.parent / "BtClass_qws"
    shutil.copy2(rootfs / "home/bticino/bin/BtClass_qws", wrapper)
    env["C300X_QML_GUI_WRAPPER"] = str(wrapper)
    if firmware == "3.0.6":
        env.update({
            "C300X_QML_QT5_ROOT": str(agent / "display-qt5"),
            "C300X_QML_GUI_DIR": str(agent / "display-qt5/skins/default"),
            "C300X_QML_BACKUP_DIR": str(Path(env["C300X_BACKUP_ROOT"]) / "original/qt5/skins/default"),
            "C300X_QML_QT5_RCC": str(agent / "display-qt5.rcc"),
            "C300X_QML_QT5_OVERLAY_LIB": str(agent / "c300x-qrc-overlay.so"),
            "C300X_QML_QT5_WRAPPER_BACKUP": str(Path(env["C300X_BACKUP_ROOT"]) / "original/bin/BtClass_qws"),
            "C300X_QML_QT5_LOG": str(agent / "qt5.log"),
            "C300X_QT5_GUI_BINARY": str(rootfs / "home/bticino/bin/gui/BtClass"),
        })
    else:
        gui = Path(env["C300X_QML_GUI_DIR"])
        for rel in ("MainApp.qml", "HomePage.qml", "MemoPage.qml", "EventManager.qml",
                    "Components/Settings/GeneralsChoice.qml", "Components/Settings/CallBlockPopup.qml"):
            shutil.copy2(rootfs / "home/bticino/bin/gui/skins/default" / rel, gui / rel)
    for action in ("apply", "media-user-label-apply"):
        result = subprocess.run([env["C300X_QML_PATCH_SCRIPT"], action], env=env,
                                capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stdout + result.stderr
    return target, backup


@pytest.mark.parametrize("firmware", FIRMWARES)
@pytest.mark.parametrize("state", ["patched", "stock", "stock_stale_backup", "partial"])
def test_removal_restores_verified_original(device, routing_binary, firmware, state):
    target, backup = _firmware_device(device, routing_binary, firmware)
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
    assert Path(device["C300X_QML_GUI_WRAPPER"]).read_bytes() == (
        FIRMWARE_ROOT / f"rootfs-{firmware}/home/bticino/bin/BtClass_qws"
    ).read_bytes()


@pytest.mark.parametrize("firmware", FIRMWARES)
@pytest.mark.parametrize("fault", [
    "corrupt_backup", "foreign_model", "foreign_firmware", "missing_backup",
    "unknown_target", "missing_target", "target_symlink", "backup_symlink", "remount",
])
def test_failed_removal_keeps_native_agent_and_backups(device, routing_binary, firmware, fault):
    target, backup = _firmware_device(device, routing_binary, firmware)
    if fault == "corrupt_backup":
        backup.write_bytes(b"\0" + backup.read_bytes()[1:])
    elif fault in {"foreign_model", "foreign_firmware"}:
        other = "c100x-1.5.8" if fault == "foreign_model" else FIRMWARES[(FIRMWARES.index(firmware) + 1) % len(FIRMWARES)]
        shutil.copy2(original(other), backup)
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
    if fault == "remount":
        device["C300X_DEVICE_PATCH_NO_REMOUNT"] = "1"
        _assert_removed(device, _remove(device))
