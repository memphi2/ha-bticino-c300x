"""Actual firmware QtQml compile only, with explicit vendor-type substitutes."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_device_file_strip import strip
from tests.test_device_qt5_runtime import skin as skin

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    not (os.environ.get("C300X_QT5_FIRMWARE") and os.environ.get("C300X_QT5_SKIN")),
    reason="Private firmware Qt 5 artifacts not supplied",
)


def test_delivered_pages_compile_with_original_firmware_qtqml(skin: Path, tmp_path: Path) -> None:
    rootfs = Path(os.environ["C300X_QT5_FIRMWARE"])
    probe = tmp_path / "compile-probe"
    subprocess.run([
        "arm-linux-gnueabihf-gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-D_DEFAULT_SOURCE",
        str(ROOT / "tests/qml/qt5_compile_probe.c"), str(ROOT / "native_agent/src/arm_start.S"), "-nostartfiles",
        f"-Wl,-rpath-link,{rootfs}/lib", f"-L{rootfs}/lib", "-l:libpthread.so.0", "-l:libdl.so.2", "-l:libc.so.6",
        "-l:ld-linux-armhf.so.3", "-o", str(probe),
    ], check=True, capture_output=True)
    # Imported vendor types are substitutes, never the hardware plugins.
    imports = tmp_path / "imports"
    shutil.copytree(ROOT / "tests/qt5_runtime", imports)
    for relative in strip.DEVICE_SOURCE_FILES:
        destination = skin / relative
        strip.strip_device_file(strip.DEVICE_SOURCE_DIR / relative, destination)
        if destination.suffix == ".qml":
            destination.write_text(destination.read_text().replace("import QtQuick 1.1\n", "import QtQuick 2.7\n", 1))
    files = [skin / path.name for path in sorted((ROOT / "device_qml").glob("*.qml"))]
    result = subprocess.run([
        "qemu-arm", "-L", str(rootfs), "-E", f"LD_LIBRARY_PATH={rootfs}/usr/lib:{rootfs}/lib",
        "-E", "QML_DISABLE_DISK_CACHE=1", "-E", "QT_QPA_PLATFORM=offscreen",
        str(probe), str(rootfs / "usr/lib/qml"), str(skin), str(imports), *(str(path) for path in files),
    ], capture_output=True, text=True, timeout=120)
    (tmp_path / "compile.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "FIRMWARE_QT_VERSION=5.15.7" in result.stdout
    assert "COMPILE_FAILURES=0" in result.stdout
    assert result.stdout.count("COMPILE_STATUS=1 ") == len(files)
