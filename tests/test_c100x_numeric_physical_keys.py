"""A number is edited and sent with the stock navigation keys only; the keymap has no back key."""

import importlib.util
import json
import os
import struct
import subprocess
import sys

import pytest
from test_c100x_qml_adapter import ROOT, builder
from test_native_routing_firmware_restore import FIRMWARE_ROOT, original


def test_numeric_edit_and_commit_with_firmware_keymap(tmp_path):
    if importlib.util.find_spec("PyQt5") is None:
        pytest.skip("Optional host PyQt5 absent; not a hardware acceptance test")
    original("c100x-1.5.8")
    keymap = (FIRMWARE_ROOT / "rootfs-c100x-1.5.8/home/bticino/bin/gui/keymap.qmap").read_bytes()
    magic, version, count, compose = struct.unpack(">4I", keymap[:16])
    assert (magic, version, compose) == (0x514D4150, 1, 0)
    assert len(keymap) == 16 + count * 12
    keys = [struct.unpack(">HHIBBH", keymap[16 + index * 12:28 + index * 12])[2]
            for index in range(count)]
    source = tmp_path / "source"
    builder.build(source)
    result = subprocess.run(
        [sys.executable, str(ROOT / "tests/fixtures/c100x_numeric_keys_probe.py"), str(source), json.dumps(keys)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
