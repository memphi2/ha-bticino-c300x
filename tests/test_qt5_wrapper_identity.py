"""Whole-file identity of a Qt5 wrapper, independently of path or syntax."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.test_qml_patch_qt5_overlay import programs as programs


@pytest.mark.parametrize("fault", ["none", "empty", "truncated", "same-size", "appended",
                                  "symlink", "directory", "fifo", "missing"])
def test_original_firmware_wrapper_identity(programs, tmp_path, fault):
    firmware = os.environ.get("C300X_QT5_FIRMWARE")
    if not firmware:
        pytest.skip("Private original Qt5 wrapper not supplied")
    original = Path(firmware) / "home/bticino/bin/BtClass_qws"
    target = tmp_path / "arbitrary-name"
    target.write_bytes(original.read_bytes())
    if fault == "empty":
        target.write_bytes(b"")
    elif fault == "truncated":
        target.write_bytes(target.read_bytes()[:-1])
    elif fault == "same-size":
        target.write_bytes(target.read_bytes().replace(b"eglfs", b"other", 1))
    elif fault == "appended":
        with target.open("ab") as stream:
            stream.write(b"\n# changed\n")
    elif fault in {"symlink", "directory", "fifo", "missing"}:
        target.unlink()
        if fault == "symlink":
            target.symlink_to(original)
        elif fault == "directory":
            target.mkdir()
        elif fault == "fifo":
            os.mkfifo(target)
    result = subprocess.run([str(programs["agent"]), "--display-qt5", "wrapper-check", str(target)],
                            capture_output=True, text=True, timeout=5)
    body = json.loads(result.stdout)
    assert result.returncode == (0 if fault == "none" else 1), result.stdout + result.stderr
    assert body["ok"] is (fault == "none")
    if fault != "none":
        assert body["error"] == "display_wrapper_unknown"
