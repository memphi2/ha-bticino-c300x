"""Execute delivered alert JS with original firmware QtQml, substituted IO."""

import os
import subprocess
from pathlib import Path

import pytest

from tests.test_device_file_strip import strip

ROOT = Path(__file__).resolve().parents[1]


def test_alert_lifecycle_on_original_qt5(tmp_path):
    firmware = os.environ.get("C300X_QT5_FIRMWARE")
    if not firmware:
        pytest.skip("Private original firmware QtQml not supplied")
    rootfs = Path(firmware)
    probe = tmp_path / "js-probe"
    subprocess.run([
        "arm-linux-gnueabihf-gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-D_DEFAULT_SOURCE",
        str(ROOT / "tests/qml/qt5_js_probe.c"), str(ROOT / "native_agent/src/arm_start.S"), "-nostartfiles",
        f"-Wl,-rpath-link,{rootfs}/lib", f"-L{rootfs}/lib", "-l:libpthread.so.0", "-l:libdl.so.2", "-l:libc.so.6",
        "-l:ld-linux-armhf.so.3", "-o", str(probe),
    ], check=True, capture_output=True)
    delivered = tmp_path / "alerts.js"
    strip.strip_device_file(ROOT / "device_qml/js/c300x_alerts.js", delivered)
    source = delivered.read_text().replace(".pragma library", "", 1)
    delivered.write_text(source + "\n" + (ROOT / "tests/qml/alerts_firmware.js").read_text())
    result = subprocess.run([
        "qemu-arm", "-L", str(rootfs), "-E", f"LD_LIBRARY_PATH={rootfs}/usr/lib:{rootfs}/lib",
        str(probe), str(delivered),
    ], capture_output=True, text=True, timeout=30)
    (tmp_path / "runtime.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "FIRMWARE_QT_VERSION=5.15.7" in result.stdout
    assert "JS_RESULT=ALERT_LIFECYCLE_OK" in result.stdout
    assert "JS_ERROR=0" in result.stdout
