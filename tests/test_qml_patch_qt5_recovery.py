"""Full Qt5 removal must not depend on disposable extraction/packing state."""

import os
import shutil
from pathlib import Path

import pytest

from tests import test_qml_patch_qt5_overlay as overlay
from tests.test_qml_patch_qt5_overlay import Device
from tests.test_qml_patch_qt5_overlay import programs as programs
from tests.test_qml_patch_qt5_transactions import artifacts, command_failure, snapshot


@pytest.fixture(params=["fixture", "firmware"])
def device(request, tmp_path, programs):
    device = Device(tmp_path, programs)
    if request.param == "firmware":
        firmware = os.environ.get("C300X_QT5_FIRMWARE")
        if not firmware:
            pytest.skip("Private original Qt5 firmware not supplied")
        device.program = Path(firmware) / "home/bticino/bin/gui/BtClass"
        shutil.copy2(Path(firmware) / "home/bticino/bin/BtClass_qws", device.wrapper)
    device.ok("apply")
    device.ok("media-user-label-apply")
    return device


@pytest.mark.parametrize("fault", ["missing-cache", "missing-file", "changed-file", "packer-failure"])
@pytest.mark.parametrize("quarantined", [False, True])
def test_restore_all_removes_overlay_without_extraction_cache(device, fault, quarantined):
    original_wrapper = device.wrapper_backup.read_bytes()
    if quarantined:
        artifacts(device)["failed"].write_bytes(b"original failure\n")
    cached = device.qt5_root / "vendor"
    env = {}
    if fault == "missing-cache":
        shutil.rmtree(cached)
    elif fault == "missing-file":
        (cached / "MainApp.qml").unlink()
    elif fault == "changed-file":
        with (cached / "MainApp.qml").open("ab") as stream:
            stream.write(b"\n// damaged extraction cache\n")
    else:
        env["QT5_TEST_PACK_FAILS"] = "1"
        # With no comparison cache, the old path unnecessarily invokes pack.
        shutil.rmtree(cached)
    result = device.ok("restore-all", **env)
    assert result["qt5_overlay"] == "off", result
    assert result["state"] == result["core_state"] == result["media_user_label_state"] == "original"
    assert device.wrapper.read_bytes() == original_wrapper
    assert not any(artifacts(device)[name].exists() for name in ("rcc", "library", "failed"))
    assert device.ok("restore-all", **env)["changed_files"] == 0


def test_cache_independent_restore_still_rolls_back_on_reload_failure(device, monkeypatch):
    artifacts(device)["failed"].write_bytes(b"keep quarantine\n")
    shutil.rmtree(device.qt5_root / "vendor")
    before = snapshot(device)
    source = overlay.SCRIPT.read_text()
    start, end = source.index("reload_gui() {"), source.index("\nremount_rw() {")
    script = device.root / "reload-fails.sh"
    script.write_text(source[:start] + "reload_gui() { return 1; }\n" + source[end:])
    script.chmod(0o700)
    monkeypatch.setattr(overlay, "SCRIPT", script)
    assert device.ok("restore-all")["state"] == "reload_failed"
    assert snapshot(device) == before


@pytest.mark.parametrize("fault", ["missing", "empty", "no-launch", "syntax", "patched", "same-size",
                                  "mode-0644", "mode-0600"])
def test_unusable_original_wrapper_cannot_discard_recovery(device, fault):
    if fault == "missing":
        device.wrapper_backup.unlink()
    elif fault == "empty":
        device.wrapper_backup.write_bytes(b"")
    elif fault == "no-launch":
        device.wrapper_backup.write_text("#!/bin/sh\nexit 0\n")
    elif fault == "syntax":
        with device.wrapper_backup.open("a") as stream:
            stream.write("\nif then\n")
    elif fault == "patched":
        device.wrapper_backup.write_bytes(device.wrapper.read_bytes())
    elif fault.startswith("mode-"):
        device.wrapper_backup.chmod(int(fault[5:], 8))
    else:
        # Still executable shell with its launch marker, but not the original.
        device.wrapper_backup.write_bytes(device.wrapper_backup.read_bytes().replace(b"eglfs", b"other", 1))
    artifacts(device)["failed"].write_bytes(b"retain failure\n")
    before = snapshot(device)
    identities = {name: (path.stat().st_ino, path.stat().st_mtime_ns)
                  for name, path in artifacts(device).items() if path.exists()}
    result = device.run("restore-all")
    assert result.returncode != 0, result.stdout
    assert snapshot(device) == before
    assert {name: (path.stat().st_ino, path.stat().st_mtime_ns)
            for name, path in artifacts(device).items() if path.exists()} == identities


@pytest.mark.parametrize("fault", ["copy", "rename", "remount-rw", "remount-ro"])
def test_restore_io_failure_never_reports_success(device, fault):
    before = snapshot(device)
    if fault in {"copy", "rename"}:
        command = "cp" if fault == "copy" else "mv"
        argument = "$3" if fault == "copy" else "$2"
        env = command_failure(device, command, f'[ "{argument}" = "{device.wrapper}.c300x.tmp" ]')
    else:
        env = command_failure(device, "mount", f'[ "$2" = "remount,{fault[-2:]}" ]',
                              effect="exit 1")
        # All other mount invocations are local no-ops, never real remounts.
        mount = device.root / "commands/mount"
        mount.write_text(mount.read_text().split('exec "')[0] + "exit 0\n")
        env["C300X_QML_NO_REMOUNT"] = "0"
    result = device.run("restore-all", **env)
    assert result.returncode != 0, result.stdout
    assert '"ok":true' not in result.stdout
    if fault == "remount-ro":
        # The new state is committed before the final remount. Recovery material
        # is retained, but a read-only remount error must not be called success.
        assert device.wrapper_backup.read_bytes() == before["original"][0]
        assert device.ok("status")["qt5_overlay"] == "off"
    else:
        assert snapshot(device) == before


@pytest.mark.parametrize("command", ["cp", "mv"])
def test_successful_but_corrupt_wrapper_copy_rolls_back(device, command):
    before = snapshot(device)
    argument = "$3" if command == "cp" else "$2"
    env = command_failure(device, command, f'[ "{argument}" = "{device.wrapper}.c300x.tmp" ]',
                          effect='printf corrupted > "$3"; chmod 755 "$3"; exit 0')
    result = device.run("restore-all", **env)
    assert result.returncode != 0, result.stdout
    assert snapshot(device) == before


def test_corrupt_current_wrapper_uses_verified_original(device):
    original = device.wrapper_backup.read_bytes()
    device.wrapper.write_text("#!/bin/sh\nexit 0\n")
    assert device.ok("restore-all")["qt5_overlay"] == "off"
    assert device.wrapper.read_bytes() == original
