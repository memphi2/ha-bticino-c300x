"""Optional offline resource reads using the actual ARM firmware QtCore.

C300X_QT5_FIRMWARE selects a private extracted 3.0.6 rootfs. No vendor GUI,
device, display server, hardware plugin, or network connection is started.
Use --basetemp under /var/tmp: the firmware's /tmp symlink redirects QEMU.
"""

from __future__ import annotations

import hashlib
import os
import struct
import subprocess
from pathlib import Path

import pytest

from tests.test_display_qt5 import _vendor_tables

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not os.environ.get("C300X_QT5_FIRMWARE"), reason="Private Qt 5 firmware not supplied")


@pytest.fixture(scope="module")
def firmware_probe(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, Path]:
    rootfs = Path(os.environ["C300X_QT5_FIRMWARE"])
    out = tmp_path_factory.mktemp("firmware-resource")
    probe, overlay = out / "probe", out / "overlay.so"
    link = [f"-Wl,-rpath-link,{rootfs}/lib", f"-L{rootfs}/lib", "-l:libdl.so.2", "-l:libc.so.6"]
    flags = ["arm-linux-gnueabihf-gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-D_DEFAULT_SOURCE"]
    subprocess.run([*flags, str(ROOT / "tests/qml/qt5_resource_probe.c"), str(ROOT / "native_agent/src/arm_start.S"),
                    "-nostartfiles", *link, "-l:ld-linux-armhf.so.3", "-o", str(probe)], check=True, capture_output=True)
    subprocess.run([*flags, "-fPIC", "-shared", str(ROOT / "native_agent/qt5/qrc_overlay.c"),
                    *link, "-o", str(overlay)], check=True, capture_output=True)
    return rootfs, probe, Path(os.environ.get("C300X_QT5_TEST_OVERLAY", overlay))


def resource_bytes() -> bytearray:
    tree, names, data = _vendor_tables({"MainApp.qml": b"firmware-resource-probe"}, flags=0)
    return bytearray(b"qres" + struct.pack(">IIII", 2, 20, 20 + len(tree) + len(names), 20 + len(tree)) + tree + names + data)


def read_resource(firmware_probe: tuple[Path, Path, Path], path: Path, *, vendor: Path | None = None) -> subprocess.CompletedProcess[str]:
    rootfs, probe, overlay = firmware_probe
    return subprocess.run(["qemu-arm", "-L", str(rootfs), "-E", f"LD_LIBRARY_PATH={rootfs}/usr/lib:{rootfs}/lib",
                           "-E", f"C300X_QRC_OVERLAY={path}", str(probe), str(overlay), ":/skins/default/MainApp.qml",
                           *([str(vendor)] if vendor else [])],
                          capture_output=True, text=True, timeout=10)


def test_original_qtcore_reads_valid_overlay(firmware_probe: tuple[Path, Path, Path], tmp_path: Path) -> None:
    path = tmp_path / "valid.rcc"
    path.write_bytes(resource_bytes())
    result = read_resource(firmware_probe, path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "FIRMWARE_QT_VERSION=5.15.7" in result.stdout
    assert "RESOURCE_VALID=1" in result.stdout
    assert "RESOURCE_BYTES=23 FIRST=102 LAST=101" in result.stdout


@pytest.mark.parametrize("case", ["child", "name", "data", "length", "cycle", "short_tree"])
def test_original_qtcore_survives_damaged_overlay(
    firmware_probe: tuple[Path, Path, Path], tmp_path: Path, case: str,
) -> None:
    blob = resource_bytes()
    tree, data, names = struct.unpack_from(">III", blob, 8)
    if case == "child":
        struct.pack_into(">I", blob, tree + 10, 0x10000000)
    elif case == "name":
        struct.pack_into(">I", blob, tree + 22, 0x10000000)
    elif case == "data":
        struct.pack_into(">I", blob, tree + 3 * 22 + 10, 0x10000000)
    elif case == "length":
        struct.pack_into(">I", blob, data, 0x10000000)
    elif case == "cycle":
        struct.pack_into(">I", blob, tree + 10, 0)
    elif case == "short_tree":
        struct.pack_into(">I", blob, 8, names - 1)
    path = tmp_path / f"{case}.rcc"
    path.write_bytes(blob)
    result = read_resource(firmware_probe, path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "RESOURCE_VALID=0" in result.stdout, result.stdout


@pytest.mark.parametrize("damaged", [False, True])
def test_original_resources_are_shadowed_only_by_valid_overlay(
    firmware_probe: tuple[Path, Path, Path], tmp_path: Path, damaged: bool,
) -> None:
    vendor = firmware_probe[0] / "home/bticino/bin/gui/BtClass"
    assert hashlib.sha256(vendor.read_bytes()).hexdigest() == "6e114e7d9ce17d4c587a13082720bb6b5e66d5683bfd12047321b9694f2971f8"
    path = tmp_path / "precedence.rcc"
    blob = resource_bytes()
    path.write_bytes(blob[:30] if damaged else blob)
    result = read_resource(firmware_probe, path, vendor=vendor)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "VENDOR_RESOURCES_REGISTERED=1" in result.stdout
    assert "RESOURCE_VALID=1" in result.stdout
    assert ("RESOURCE_BYTES=23 FIRST=102 LAST=101" in result.stdout) is not damaged
