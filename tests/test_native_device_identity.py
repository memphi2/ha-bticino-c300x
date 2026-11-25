"""What the station says about itself: model, board, article number."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native_agent"

PROBE = r"""
#include <stdio.h>
#include "device_detect.h"
int main(void)
{
    struct c300x_device_profile profile = c300x_device_profile();
    char board[C300X_DEVICE_BOARD_LEN] = "?", article[C300X_DEVICE_ARTICLE_LEN] = "?";
    c300x_device_board(board, sizeof(board));
    c300x_device_article(article, sizeof(article));
    printf("%s\n%s\n%s\n%d\n%d\n%s\n%s\n", c300x_device_model_name(profile.model),
        c300x_device_model_check_name(profile.model_check), c300x_display_kind_name(profile.display),
        profile.camera_fixed, c300x_device_display_files_patchable(), board, article);
    return 0;
}
"""
FILES = {
    "C300X_QT5_DISPLAY_MARKER": "libQt5Core.so.5",
    "C300X_C100X_DISPLAY_MARKER": "BtClass100",
    "C300X_DEVICE_INFO_XML": "dbfiles_ws.xml",
    "C300X_DEVICE_CPUINFO": "cpuinfo",
    "C300X_DEVICE_TREE_MODEL": "model",
    "C300X_DEVICE_ARTICLE_FILE": "codename",
}
XML = ("<?xml version='1.0'?>\n<root>\n<webserver_type>{}</webserver_type>\n"
       "<ver_webserver>1.7.19</ver_webserver>\n</root>\n")
CPUINFO = ("processor\t: 0\nmodel name\t: ARMv7 Processor rev 10 (v7l)\n\n"
           "Hardware\t: {}\nRevision\t: 0000\nSerial\t\t: 0000000000000000\n")
ZIA = "BTicino ZIA board HW Rev 3"
SHARK = "BTicino SHARK board (Dig-D/Car-C)"


@pytest.fixture(scope="module")
def station(tmp_path_factory):
    folder = tmp_path_factory.mktemp("identity")
    (folder / "probe.c").write_text(PROBE, encoding="utf-8")
    subprocess.run(
        ["gcc", "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror", "-D_DEFAULT_SOURCE",
         "-D_POSIX_C_SOURCE=200809L", f"-I{NATIVE / 'src'}",
         *(f"-D{name}={json.dumps(str(folder / file))}" for name, file in FILES.items()),
         str(folder / "probe.c"), str(NATIVE / "src/device_detect.c"), "-o", str(folder / "probe")],
        check=True, capture_output=True, text=True,
    )

    def run(**files: bytes | str | None) -> dict[str, str]:
        for file in FILES.values():
            (folder / file).unlink(missing_ok=True)
        for file, content in files.items():
            name = {"qt5": "libQt5Core.so.5", "c100x": "BtClass100", "xml": "dbfiles_ws.xml"}.get(file, file)
            if content is not None:
                (folder / name).write_bytes(content.encode() if isinstance(content, str) else content)
        lines = subprocess.run([str(folder / "probe")], check=True, capture_output=True, text=True).stdout.split("\n")
        return dict(zip(("model", "check", "display", "camera_fixed", "patchable", "board", "article"), lines[:7], strict=True))

    return run


@pytest.mark.parametrize(("xml", "qt5", "c100x", "expected"), [
    # The four stations as their firmware files name them.
    ("C300X", False, False, ("C300X", "ok", "qt4_ondisk", "0", "1")),
    ("C300X", True, False, ("C300X", "ok", "qt5_rcc", "1", "1")),
    ("C100X", True, True, ("C100X", "ok", "qt5_ondisk", "1", "0")),
    (" C100X\n", False, True, ("C100X", "ok", "qt5_ondisk", "1", "0")),
    # The station names no known model: the display program decides, as before.
    (None, False, False, ("C300X", "unread", "qt4_ondisk", "0", "1")),
    (None, True, False, ("C300X", "unread", "qt5_rcc", "1", "1")),
    (None, True, True, ("C100X", "unread", "qt5_ondisk", "1", "0")),
    ("C500X", False, False, ("C300X", "unread", "qt4_ondisk", "0", "1")),
    ("", False, True, ("C100X", "unread", "qt5_ondisk", "1", "0")),
    # They disagree: the display program decides model and display, as in
    # 2.10.0, and the disagreement is reported.
    ("C300X", True, True, ("C100X", "mismatch", "qt5_ondisk", "1", "0")),
    ("C100X", False, False, ("C300X", "mismatch", "qt4_ondisk", "0", "1")),
    ("C100X", True, False, ("C300X", "mismatch", "qt5_rcc", "1", "1")),
])
def test_the_station_names_its_model_and_the_display_program_checks_it(station, xml, qt5, c100x, expected):
    answer = station(
        xml=None if xml is None else XML.format(xml),
        qt5="" if qt5 else None, c100x="" if c100x else None,
    )
    assert tuple(answer[key] for key in ("model", "check", "display", "camera_fixed", "patchable")) == expected


@pytest.mark.parametrize(("firmware", "qt5", "c100x", "expected"), [
    ("1.7.19", False, False, ("C300X", "ok", "qt4_ondisk")),
    ("2.0.2", False, False, ("C300X", "ok", "qt4_ondisk")),
    ("3.0.6", True, False, ("C300X", "ok", "qt5_rcc")),
    ("c100x-1.5.8", True, True, ("C100X", "ok", "qt5_ondisk")),
])
def test_the_firmware_files_name_their_model(station, firmware, qt5, c100x, expected):
    work = Path(os.environ.get("C300X_FIRMWARE_WORK", ROOT.parent / "c300x-fwpatch/work"))
    root = work / f"rootfs-{firmware}"
    if not root.is_dir():
        pytest.skip("Private firmware files unavailable")
    # The markers are the firmware's own too.
    assert (root / "usr/lib/libQt5Core.so.5").exists() is qt5
    assert (root / "home/bticino/bin/gui/BtClass100").exists() is c100x
    answer = station(
        xml=(root / "home/bticino/sp/dbfiles_ws.xml").read_bytes(),
        qt5="" if qt5 else None, c100x="" if c100x else None,
    )
    assert (answer["model"], answer["check"], answer["display"]) == expected


def test_a_model_file_without_the_field_or_cut_off_counts_as_unread(station):
    assert station(xml="<root><ver_webserver>1.7.19</ver_webserver></root>")["check"] == "unread"
    assert station(xml="<root><webserver_type>C100X")["check"] == "unread"
    assert station(xml=b"")["check"] == "unread"
    # Only the start of the file is read; the firmware files have the field there.
    assert station(xml="<root>" + " " * 5000 + "<webserver_type>C100X</webserver_type>")["check"] == "unread"


@pytest.mark.parametrize(("files", "board"), [
    ({"cpuinfo": CPUINFO.format(ZIA)}, ZIA),
    ({"cpuinfo": CPUINFO.format(SHARK)}, SHARK),
    ({"cpuinfo": CPUINFO.format(f"  {ZIA} \t")}, ZIA),
    ({"cpuinfo": f"Hardware: {ZIA}"}, ZIA),
    # Without the kernel's line the device tree names the board, NUL-terminated.
    ({"cpuinfo": "processor\t: 0\n", "model": ZIA.encode() + b"\0"}, ZIA),
    ({"model": SHARK.encode() + b"\0"}, SHARK),
    ({"cpuinfo": "Hardware\t: \n", "model": f"{ZIA}\n"}, ZIA),
    ({"cpuinfo": CPUINFO.format(ZIA), "model": SHARK}, ZIA),
    # Missing, empty, not printable or too long: no board is shown.
    ({}, ""),
    ({"cpuinfo": "", "model": b""}, ""),
    ({"cpuinfo": "Hardware\t: café\n"}, ""),
    ({"cpuinfo": "Hardware\t: " + "x" * 96 + "\n"}, ""),
    ({"cpuinfo": "Hardware\t: " + "x" * 95 + "\n"}, "x" * 95),
    ({"cpuinfo": "HardwareRev\t: 1\n"}, ""),
])
def test_the_board_is_the_kernels_full_name(station, files, board):
    assert station(**files)["board"] == board


@pytest.mark.parametrize(("content", "article"), [
    ("344642$$", "344642"),
    ("344642$$\n", "344642"),
    ("  $344643$ \n", "344643"),
    ("344642", "344642"),
    (None, ""),
    ("", ""),
    ("$$$$\n", ""),
    (b"3446\xff42$$", ""),
    ("3" * 40, ""),
])
def test_the_article_number_is_read_without_its_padding(station, content, article):
    assert station(codename=content)["article"] == article


def test_the_identity_files_are_the_stations_own():
    detect = (NATIVE / "src/device_detect.c").read_text(encoding="utf-8")
    firmware = (NATIVE / "src/firmware_version.c").read_text(encoding="utf-8")
    # The same file the firmware version comes from.
    assert '"/home/bticino/sp/dbfiles_ws.xml"' in detect and '"/home/bticino/sp/dbfiles_ws.xml"' in firmware
    for path in ("/proc/cpuinfo", "/sys/firmware/devicetree/base/model", "/var/tmp/flags/codename"):
        assert f'"{path}"' in detect
    # Board and article are shown, never decided from.
    profile = detect[detect.index("struct c300x_device_profile c300x_device_profile(void)"):]
    profile = profile[:profile.index("\n}\n")]
    assert "board" not in profile and "article" not in profile
