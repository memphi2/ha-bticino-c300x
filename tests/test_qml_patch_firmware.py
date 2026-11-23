"""Optional patch round-trip against a private, read-only local firmware tree."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import test_qml_patch_script as patch
from test_qml_patch_script import ROOT, _run_qml_patch


def test_private_firmware_patch_round_trip(tmp_path: Path) -> None:
    sysroot = os.environ.get("C300X_DEVICE_SYSROOT")
    if not sysroot:
        pytest.skip("Private C300X firmware sysroot not configured")
    source = Path(sysroot) / "home/bticino/bin/gui/skins/default"
    stock_files = (
        "Settings.qml", "MainApp.qml", "HomePage.qml", "MemoPage.qml", "EventManager.qml",
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
    assert (gui / "Components/Settings/GeneralsChoice.qml").read_bytes() == originals["Components/Settings/GeneralsChoice.qml"]
    assert 'sourceUrl: "C300XSettings.qml"' in (gui / "Settings.qml").read_text()
    assert _run_qml_patch(tmp_path, gui, backups, "apply")["changed_files"] == 0
    assert _run_qml_patch(tmp_path, gui, backups, "restore-all")["state"] == "original"
    assert {name: (gui / name).read_bytes() for name in stock_files} == originals
    assert {name: (source / name).read_bytes() for name in stock_files} == originals


def test_packaged_settings_compile_with_firmware_qt4(monkeypatch):
    sysroot = os.environ.get("C300X_DEVICE_SYSROOT")
    probe = os.environ.get("C300X_QT4_COMPILE_PROBE")
    if not (sysroot and probe):
        pytest.skip("Private firmware and Qt4 compile probe required")
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    from stage_device_agent_bundle import stage_bundle

    with tempfile.TemporaryDirectory(dir="/var/tmp") as directory:
        work = Path(directory)
        gui = work / "skin"
        shutil.copytree(Path(sysroot) / "home/bticino/bin/gui/skins/default", gui)
        # These types are registered by BtClass, not by the standalone Qt engine.
        for module, version in (("BtClass", "1.0"), ("BtObjects", "2.0")):
            target = gui / module
            target.mkdir()
            (target / "qmldir").write_text(f"module {module}\nObjectModel {version} ObjectModel.qml\n"
                                            if module == "BtObjects" else f"module {module}\n")
        (gui / "BtObjects/ObjectModel.qml").write_text(
            "import QtQuick 1.1\nQtObject { property variant filters; property int count }\n"
        )
        stage_bundle(work, version="test", skip_build=True, agent_binary=ROOT / "project-versions.json")
        monkeypatch.setattr(patch, "SCRIPT", work / "device_agent/scripts/qml_patch.sh")
        _run_qml_patch(work, gui, work / "backup", "apply", source_dir=work / "device_agent/qml")
        for name in ("Settings.qml", "C300XSettings.qml"):
            result = subprocess.run([
                os.environ.get("C300X_QT4_QEMU", "qemu-arm"), "-L", sysroot,
                "-E", f"LD_LIBRARY_PATH={sysroot}/usr/lib:{sysroot}/lib",
                probe, str(gui / name), str(gui),
            ], capture_output=True, text=True, timeout=30)
            assert "compile_failed=0" in result.stdout, result.stdout + result.stderr
