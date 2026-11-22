"""C100X text-only memo display; never writes the vendor store or plays audio."""

import importlib.util
import os
import subprocess
import sys

import pytest
from test_c100x_qml_adapter import ROOT, builder
from test_native_routing_firmware_restore import FIRMWARE_ROOT, original


def test_original_firmware_has_text_memo_store_and_metadata():
    original("c100x-1.5.8")
    root = FIRMWARE_ROOT / "rootfs-c100x-1.5.8/home/bticino"
    binary = (root / "bin/bt_answering_machine").read_bytes()
    for marker in (b"/home/bticino/cfg/extra/47/memos_text", b"msg_info.ini", b"Message Information",
                   b"MediaType", b"Read", b"Date", b"UnixTime", b"/var/tmp/records/message.txt"):
        assert marker in binary
    assert b"getMemos" in (root / "lib/BtObjects/libbtobjects.so").read_bytes()
    assert not (root / "bin/gui/skins/default/MemoPage.qml").exists()


def test_memo_protocol_bounds_cancel_errors_and_read_only_transport():
    result = subprocess.run(["node", str(ROOT / "tests/fixtures/c100x_memos_probe.js"),
                             str(ROOT / "device_qml/c100x/js/c100x_memos.js")],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


def test_memo_full_list_detail_scroll_and_call_preemption_in_host_qt5(tmp_path):
    if importlib.util.find_spec("PyQt5") is None:
        pytest.skip("Optional host PyQt5 absent")
    source = tmp_path / "source"
    builder.build(source)
    result = subprocess.run([sys.executable, str(ROOT / "tests/fixtures/c100x_memos_probe.py"),
                             str(source), str(tmp_path / "screenshots")],
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
