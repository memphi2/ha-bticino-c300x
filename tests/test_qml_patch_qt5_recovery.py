"""Full Qt5 removal must not depend on disposable extraction/packing state."""

import os
import shutil
from pathlib import Path

import pytest

from tests import test_qml_patch_qt5_overlay as overlay
from tests.test_qml_patch_qt5_overlay import Device
from tests.test_qml_patch_qt5_overlay import programs as programs
from tests.test_qml_patch_qt5_transactions import artifacts, snapshot


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
