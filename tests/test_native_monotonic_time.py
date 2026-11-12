"""Device clock corrections must not expire or extend native runtime deadlines."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ringer_and_command_deadlines_ignore_wall_clock_changes(tmp_path):
    binary = tmp_path / "monotonic-time-test"
    result = subprocess.run(
        [
            "cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
            "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
            "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
            str(ROOT / "native_agent/test/monotonic_time_test.c"),
            str(ROOT / "native_agent/src/ringer_control.c"),
            str(ROOT / "native_agent/src/command_job.c"),
            "-o", str(binary),
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
