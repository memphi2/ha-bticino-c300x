"""Compile the injected hook fragments with the original Qt, without instances."""

import os
from pathlib import Path

import pytest
from test_c100x_firmware_compile import firmware_case as firmware_case
from test_c100x_firmware_compile import firmware_probe as firmware_probe
from test_c100x_firmware_compile import firmware_workspace as firmware_workspace

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("fixture", ["c100x_hook_probe.qml", "c100x_menu_hook_probe.qml"])
def test_stock_hooks_compile_with_original_qt5101(firmware_probe, firmware_case, fixture):
    stock = Path(os.environ.get(
        "C100X_QT5_FIRMWARE", Path(os.environ.get("C300X_FIRMWARE_WORK", ROOT.parent / "c300x-fwpatch/work"))
        / "rootfs-c100x-1.5.8",
    )) / "home/bticino/bin/gui/skins/default/main.qml"
    lines = stock.read_text().splitlines()
    document = (ROOT / "tests/fixtures" / fixture).read_bytes()
    document = document.replace(b"@MAIN_HOOK@", (ROOT / "device_qml/c100x/hooks/main.inc").read_bytes()
                                .replace(b"@RELEASE@", b"unused-compile-only"))
    document = document.replace(b"@MENU_HOOK@", (ROOT / "device_qml/c100x/hooks/menu.inc").read_bytes())
    for token, anchor in (
        (b"@VENDOR_ARRIVAL@", "                        if (!mainStackView.currentItem.hasOwnProperty('menuVisible') ||"),
        (b"@VENDOR_POP_ARRIVAL@", "                        if(!vctModel.vct.callInProgress)"),
    ):
        start = lines.index(anchor)
        end = lines.index("                    }", start)
        document = document.replace(token, "\n".join(lines[start:end]).encode())
    path = firmware_case / "Hook.qml"
    path.write_bytes(document)
    result = firmware_probe([path], firmware_case)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "COMPILE_FAILURES=0\n" in result.stdout
