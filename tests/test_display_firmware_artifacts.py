"""Private firmware evidence; never execute the vendor application or plugins.

Requires C300X_QT5_FIRMWARE, C300X_QT5_SKIN (extracted real resources), and
C300X_DEVICE_SYSROOT (1.7.19). Firmware bytes stay in temporary directories.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import sys
from pathlib import Path

import pytest

from tests.test_qml_patch_qt5_overlay import Device
from tests.test_qml_patch_qt5_overlay import programs as programs

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    not all(os.environ.get(key) for key in ("C300X_QT5_FIRMWARE", "C300X_QT5_SKIN", "C300X_DEVICE_SYSROOT")),
    reason="Private original firmware artifacts not supplied",
)


class ArmElf:
    """Read ELF32 load addresses and Qt 5 moc tables, not executable code."""

    def __init__(self, path: Path) -> None:
        self.data = path.read_bytes()
        assert self.data[:6] == b"\x7fELF\x01\x01"
        assert struct.unpack_from("<H", self.data, 18)[0] == 40  # EM_ARM
        start = struct.unpack_from("<I", self.data, 28)[0]
        stride, count = struct.unpack_from("<HH", self.data, 42)
        self.segments = [struct.unpack_from("<8I", self.data, start + i * stride) for i in range(count)]

    def offset(self, address: int) -> int:
        for kind, offset, virtual, _, size, *_ in self.segments:
            if kind == 1 and virtual <= address < virtual + size:
                return offset + address - virtual
        raise ValueError(f"Unmapped ELF address {address:x}")

    def address(self, offset: int) -> int:
        for kind, start, virtual, _, size, *_ in self.segments:
            if kind == 1 and start <= offset < start + size:
                return virtual + offset - start
        raise ValueError("Unmapped ELF offset")

    def words(self, offset: int, count: int) -> tuple[int, ...]:
        return struct.unpack_from(f"<{count}I", self.data, offset)

    def metaobject(self, name: str) -> dict:
        # moc's first QByteArrayData names the class. Its offset is relative
        # to that header; Qt 5's ARM header has four 32-bit fields.
        pattern = struct.pack("<iII", -1, len(name), 0)
        start = 0
        while (start := self.data.find(pattern, start)) >= 0:
            base = start
            start += 4
            text = base + self.words(base + 12, 1)[0]
            if self.data[text:text + len(name) + 1] != name.encode() + b"\0":
                continue
            pointer = struct.pack("<I", self.address(base))
            reference = 0
            while (reference := self.data.find(pointer, reference)) >= 0:
                here = reference
                reference += 4
                if here % 4:
                    continue
                try:
                    table = self.offset(self.words(here + 4, 1)[0])
                except ValueError:
                    continue
                header = self.words(table, 14)
                if header[:2] != (8, 0) or not 0 < header[4] < 100:
                    continue

                def string(index: int, base: int = base) -> str:
                    entry = base + index * 16
                    length, _, relative = self.words(entry + 4, 3)
                    return self.data[entry + relative:entry + relative + length].decode()

                methods = {}
                for i in range(header[4]):
                    method, argc, params, _, _ = self.words(table + (header[5] + i * 5) * 4, 5)
                    methods[string(method)] = [string(n) for n in self.words(table + (params + argc + 1) * 4, argc)]
                properties = [string(self.words(table + (header[7] + i * 3) * 4, 1)[0]) for i in range(header[6])]
                enums = {}
                for i in range(header[8]):
                    enum, _, _, count, values = self.words(table + (header[9] + i * 5) * 4, 5)
                    enums[string(enum)] = {string(self.words(table + (values + n * 2) * 4, 1)[0]):
                                           self.words(table + (values + n * 2 + 1) * 4, 1)[0] for n in range(count)}
                return {"class": name, "methods": methods, "properties": properties, "enums": enums}
        raise AssertionError(f"No Qt 5 metaobject for {name}")


def test_real_qt5_patch_restore_and_manifest(programs: dict[str, Path], tmp_path: Path) -> None:
    rootfs = Path(os.environ["C300X_QT5_FIRMWARE"])
    stock = rootfs / "home/bticino/bin"
    device = Device(tmp_path, programs)
    device.program = stock / "gui/BtClass"
    shutil.copy2(stock / "BtClass_qws", device.wrapper)
    before = device.wrapper.stat()
    assert device.ok("core-apply")["core_patched"] is True
    assert device.ok("media-user-label-apply")["media_user_label_patched"] is True
    assert device.ok("apply")["patched"] is True
    assert device.ok("apply")["changed_files"] == 0
    for path in (ROOT / "device_qml").rglob("*"):
        if path.suffix in {".qml", ".js"}:
            rel = str(path.relative_to(ROOT / "device_qml"))
            packed = device.packed(rel)
            assert packed is not None, rel
            if path.suffix == ".qml":
                assert packed.startswith(b"import QtQuick 2.7\n"), rel
    assert device.ok("restore")["core_patched"] is True
    assert device.ok("restore-all")["qt5_overlay"] == "off"
    assert device.wrapper.read_bytes() == (stock / "BtClass_qws").read_bytes()
    after = device.wrapper.stat()
    assert (after.st_mode, after.st_uid, after.st_gid) == (before.st_mode, before.st_uid, before.st_gid)
    sys.stdout.write("REAL_QT5_PATCH_RESTORE_OK\n")


def test_all_custom_page_literal_assets_exist_in_both_firmwares() -> None:
    skins = [Path(os.environ["C300X_QT5_SKIN"]),
             Path(os.environ["C300X_DEVICE_SYSROOT"]) / "home/bticino/bin/gui/skins/default"]
    references = set()
    for path in (ROOT / "device_qml").rglob("*"):
        if path.suffix in {".qml", ".js"}:
            references.update(re.findall(r'''["']((?:images|js)/[^"']+\.(?:svg|png|js))["']''', path.read_text()))
    for skin in skins:
        for rel in references:
            assert (skin / rel).is_file() or (ROOT / "device_qml" / rel).is_file(), (skin.name, rel)
        for module in ("Components", "Components/Styles"):
            text = (skin / module / "qmldir").read_text()
            for file in re.findall(r"(?m)^\w+\s+1\.0\s+(\S+\.qml)\s*$", text):
                assert (skin / module / file).is_file(), file
    sys.stdout.write(f"SHARED_LITERAL_ASSETS={len(references)}\n")


def test_original_qt5_screen_and_audio_metaobjects(tmp_path: Path) -> None:
    rootfs = Path(os.environ["C300X_QT5_FIRMWARE"])
    screen = ArmElf(rootfs / "usr/lib/libqtobjects.so.1.0.0").metaobject("ScreenState")
    audio = ArmElf(rootfs / "home/bticino/bin/gui/BtClass").metaobject("AudioState")
    assert screen["methods"]["stateChangedInt"] == ["old_state", "new_state"]
    assert {"simulateClick", "enableState", "disableState"} <= screen["methods"].keys()
    assert {"state", "screensaverInterval"} <= set(screen["properties"])
    assert {"enableState", "disableState", "isStateEnabled"} <= audio["methods"].keys()
    assert {"state", "audioAccess"} <= set(audio["properties"])
    assert {"Normal", "ScreenOff", "ForcedNormal"} <= screen["enums"]["State"].keys()
    assert {"Idle", "Beep", "RingtoneMute"} <= audio["enums"]["State"].keys()
    (tmp_path / "metaobjects.json").write_text(json.dumps([screen, audio], indent=2) + "\n")
    sys.stdout.write("FIRMWARE_METAOBJECT_CONTRACT_OK\n")


def test_normalized_vendor_signal_parameters_remain_available(tmp_path: Path) -> None:
    rootfs = Path(os.environ["C300X_QT5_FIRMWARE"])
    gui = ArmElf(rootfs / "home/bticino/bin/gui/BtClass")
    objects = ArmElf(rootfs / "usr/lib/libqtobjects.so.1.0.0")
    keys, av = gui.metaobject("HwKeys"), objects.metaobject("VdeAudioVideoController")
    answering = objects.metaobject("AnsweringMachine")
    global_properties = gui.metaobject("GlobalProperties")
    assert keys["methods"]["pressed"] == ["code"]
    assert keys["methods"]["released"] == ["code"]
    assert av["methods"]["ringtoneStarted"] == ["type"]
    assert av["methods"]["ringtoneFinished"] == ["type"]
    assert answering["methods"]["isAssaabloy"] == ["name", "where", "lkid", "brid"]
    assert "beep" in global_properties["methods"]
    (tmp_path / "signal-parameters.json").write_text(json.dumps([keys, av, answering, global_properties], indent=2) + "\n")
    sys.stdout.write("NORMALIZED_SIGNAL_PARAMETERS_OK\n")


def test_record_original_artifact_hashes(tmp_path: Path) -> None:
    roots = [Path(os.environ["C300X_QT5_FIRMWARE"]), Path(os.environ["C300X_DEVICE_SYSROOT"])]
    manifest = {}
    for root in roots:
        manifest[root.name] = {}
        for rel in ("home/bticino/bin/gui/BtClass", "home/bticino/bin/BtClass_qws", "home/bticino/bin/bt_daemon"):
            manifest[root.name][rel] = hashlib.sha256((root / rel).read_bytes()).hexdigest()
    (tmp_path / "firmware-artifacts.json").write_text(json.dumps(manifest, indent=2) + "\n")
    sys.stdout.write(json.dumps(manifest, sort_keys=True) + "\n")
