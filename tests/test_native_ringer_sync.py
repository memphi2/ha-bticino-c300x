"""An unmute on the bus that the C100X GUI cannot follow is pushed to it."""

import os
import subprocess
from pathlib import Path

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


def test_unsolicited_unmute_is_pushed_to_the_gui_once(tmp_path):
    binary = tmp_path / "ringer_sync_test"
    result = subprocess.run(
        ["cc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
         "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
         "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
         str(NATIVE / "test/ringer_sync_test.c"),
         *[str(NATIVE / "src" / name) for name in ("ringer_control.c", "time_util.c", "http_util.c")],
         "-o", str(binary)], capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run(
        [str(binary)], capture_output=True, text=True, timeout=30,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1", "UBSAN_OPTIONS": "halt_on_error=1"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
