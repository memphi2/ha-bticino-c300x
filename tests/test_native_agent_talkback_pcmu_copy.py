"""PCMU talkback reaches a PCMU device without being decoded and encoded again."""

from __future__ import annotations

import subprocess
from pathlib import Path

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


def test_pcmu_talkback_is_copied_and_pcma_is_still_converted(tmp_path: Path) -> None:
    binary = tmp_path / "talkback-pcmu-copy-test"
    subprocess.run(
        [
            "gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
            "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
            "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
            str(NATIVE / "test/talkback_pcmu_copy_test.c"),
            "-pthread", "-ldl", "-o", str(binary),
        ],
        check=True, capture_output=True, text=True,
    )
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
