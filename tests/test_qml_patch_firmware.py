"""Optional patch round-trip against a private, read-only local firmware tree."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from test_qml_patch_script import _run_qml_patch


def test_private_firmware_patch_round_trip(tmp_path: Path) -> None:
    sysroot = os.environ.get("C300X_DEVICE_SYSROOT")
    if not sysroot:
        pytest.skip("Private C300X firmware sysroot not configured")
    source = Path(sysroot) / "home/bticino/bin/gui/skins/default"
    stock_files = (
        "MainApp.qml", "HomePage.qml", "MemoPage.qml", "EventManager.qml",
        "Components/Settings/GeneralsChoice.qml",
        "Components/Settings/CallBlockPopup.qml",
    )
    originals = {name: (source / name).read_bytes() for name in stock_files}
    gui = tmp_path / "gui"
    for name in stock_files:
        target = gui / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target)
    backups = tmp_path / "backups"
    assert _run_qml_patch(tmp_path, gui, backups, "apply")["state"] == "patched"
    assert _run_qml_patch(tmp_path, gui, backups, "apply")["changed_files"] == 0
    assert _run_qml_patch(tmp_path, gui, backups, "restore-all")["state"] == "original"
    assert {name: (gui / name).read_bytes() for name in stock_files} == originals
    assert {name: (source / name).read_bytes() for name in stock_files} == originals
