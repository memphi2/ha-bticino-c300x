"""Qt5 label setup/restore must run and must not confirm inactive content."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_native_device_user_routes import route_binary as route_binary
from tests.test_qml_patch_qt5_overlay import Device
from tests.test_qml_patch_qt5_overlay import programs as programs

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


def route(binary, script, operation, env=None):
    result = subprocess.run([str(binary), "report", str(script), operation],
                            env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
                                 "UBSAN_OPTIONS": "halt_on_error=1", **(env or {})},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("operation", ["ensure", "restore"])
@pytest.mark.parametrize("state", ["active", "failed", "incomplete", "off", "reload_failed"])
def test_label_outcome_is_confirmed(route_binary, tmp_path, operation, state):
    applying = operation == "ensure"
    response = {"ok": state != "reload_failed", "qt5_overlay": state, "gui_running": True,
                "media_user_label_patched": applying,
                "media_user_label_state": "patched" if applying else "original"}
    script = tmp_path / "qml-patch"
    script.write_text("#!/bin/sh\nprintf '%s\\n' '" + json.dumps(response) + "'\n")
    script.chmod(0o700)
    result = route(route_binary, script, operation)
    # Removing a label may keep an unrelated core overlay quarantined.
    accepted = state == "active" or (not applying and state in {"off", "failed"})
    assert result["status"] == (200 if accepted else 500), result
    assert result["restored"] == int(accepted and not applying)
    if state == "failed" and accepted:
        assert result["body"]["media_user_label_applied"] is False


def test_a_display_the_agent_does_not_know_does_not_block_the_media_user(route_binary, programs, tmp_path):
    """The real script on an unknown display program: the user is set up without a label."""

    device = Device(tmp_path, programs)
    device.program = tmp_path / "BtClass-unknown"
    device.program.write_bytes(b"\x7fELF other")
    env = {
        "C300X_QML_QT5_MARKER": str(tmp_path / "libQt5Core.so.5"),
        "C300X_QML_QT5_ROOT": str(device.qt5_root), "C300X_QML_GUI_DIR": str(device.gui),
        "C300X_QML_BACKUP_DIR": str(device.backup), "C300X_QML_SOURCE_DIR": str(NATIVE.parent / "device_qml"),
        "C300X_QML_QT5_RCC": str(device.rcc), "C300X_QML_QT5_OVERLAY_LIB": str(device.lib),
        "C300X_QML_QT5_WRAPPER_BACKUP": str(device.wrapper_backup), "C300X_QML_GUI_WRAPPER": str(device.wrapper),
        "C300X_QML_AGENT_BIN": str(programs["agent"]), "C300X_QT5_GUI_BINARY": str(device.program),
        "C300X_QML_NO_REMOUNT": "1", "C300X_QML_RELOAD_GUI": "0",
        "C300X_QML_BOOT_ID": str(device.boot_id),
    }
    result = route(route_binary, NATIVE / "scripts/qml_patch.sh", "ensure", env)
    assert result["status"] == 200, result
    assert result["body"]["media_user_label_applied"] is False
    assert not device.rcc.exists()


@pytest.mark.parametrize("state", ["failed", "incomplete", "off"])
def test_status_does_not_advertise_quarantined_label(route_binary, tmp_path, state):
    script = tmp_path / "status"
    script.write_text("#!/bin/sh\nprintf '%s\\n' '" + json.dumps({
        "ok": True, "media_user_label_state": "patched", "media_user_label_patched": True,
        "qt5_overlay": state, "gui_running": True,
    }) + "'\n")
    script.chmod(0o700)
    result = route(route_binary, script, "status")
    assert result["status"] == 200
    assert result["body"]["media_user_label_applied"] is False


@pytest.mark.parametrize("quarantined", [False, True])
def test_real_qt5_label_restore_is_not_skipped(route_binary, programs, tmp_path, quarantined):
    rootfs = os.environ.get("C300X_QT5_FIRMWARE")
    if not rootfs:
        pytest.skip("Private Qt5 firmware not supplied")
    device = Device(tmp_path, programs)
    device.program = Path(rootfs) / "home/bticino/bin/gui/BtClass"
    shutil.copy2(Path(rootfs) / "home/bticino/bin/BtClass_qws", device.wrapper)
    assert device.ok("core-apply")["core_patched"] is True
    assert device.ok("media-user-label-apply")["media_user_label_patched"] is True
    failed = device.rcc.with_name(device.rcc.name + ".failed")
    if quarantined:
        # A quarantine of this boot; a mark of an earlier boot would not count.
        failed.write_text("boot-1\n")
    # Isolated process-presence stand-in; no GUI or device is started.
    pidof = tmp_path / "bin/pidof"
    pidof.write_text("#!/bin/sh\necho 123\n")
    pidof.chmod(0o700)
    env = {
        "PATH": str(pidof.parent) + os.pathsep + os.environ["PATH"],
        "C300X_QML_QT5_MARKER": str(tmp_path / "libQt5Core.so.5"),
        "C300X_QML_QT5_ROOT": str(device.qt5_root), "C300X_QML_GUI_DIR": str(device.gui),
        "C300X_QML_BACKUP_DIR": str(device.backup), "C300X_QML_SOURCE_DIR": str(NATIVE.parent / "device_qml"),
        "C300X_QML_QT5_RCC": str(device.rcc), "C300X_QML_QT5_OVERLAY_LIB": str(device.lib),
        "C300X_QML_QT5_WRAPPER_BACKUP": str(device.wrapper_backup), "C300X_QML_GUI_WRAPPER": str(device.wrapper),
        "C300X_QML_AGENT_BIN": str(programs["agent"]), "C300X_QT5_GUI_BINARY": str(device.program),
        "C300X_QML_NO_REMOUNT": "1", "C300X_QML_RELOAD_GUI": "0",
        "C300X_QML_BOOT_ID": str(device.boot_id),
    }
    result = route(route_binary, NATIVE / "scripts/qml_patch.sh", "restore", env)
    assert result["status"] == 200 and result["restored"] == 1, result
    status = device.ok("status")
    assert status["media_user_label_patched"] is False
    assert status["core_patched"] is True
    assert status["qt5_overlay"] == ("failed" if quarantined else "active")
    assert failed.exists() is quarantined
    assert device.packed("Components/Settings/CallBlockPopup.qml") is None


@pytest.mark.parametrize("operation", ["ensure", "restore"])
def test_a_label_write_whose_display_restart_still_runs_is_accepted(route_binary, tmp_path, operation):
    """The label is written; the restart in flight shows it, its outcome shows in the status."""

    applying = operation == "ensure"
    response = {"ok": True, "qt5_overlay": "active", "gui_running": False, "gui_restart": "pending",
                "media_user_label_patched": applying,
                "media_user_label_state": "patched" if applying else "original"}
    script = tmp_path / "qml-patch"
    script.write_text("#!/bin/sh\nprintf '%s\\n' '" + json.dumps(response) + "'\n")
    script.chmod(0o700)
    result = route(route_binary, script, operation)
    assert result["status"] == 200, result
    assert result["restored"] == int(not applying)


def test_a_label_write_without_a_display_and_no_restart_is_refused(route_binary, tmp_path):
    response = {"ok": True, "qt5_overlay": "active", "gui_running": False, "gui_restart": "idle",
                "media_user_label_patched": True, "media_user_label_state": "patched"}
    script = tmp_path / "qml-patch"
    script.write_text("#!/bin/sh\nprintf '%s\\n' '" + json.dumps(response) + "'\n")
    script.chmod(0o700)
    assert route(route_binary, script, "ensure")["status"] == 500
