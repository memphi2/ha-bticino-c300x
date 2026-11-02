from __future__ import annotations

import subprocess
from pathlib import Path


def test_slow_callbacks_are_bounded_and_do_not_block_submit(tmp_path):
    root = Path(__file__).resolve().parents[1] / "native_agent"
    binary = tmp_path / "callback-queue-test"
    result = subprocess.run(
        [
            "cc",
            "-std=c11",
            "-O2",
            "-D_DEFAULT_SOURCE",
            "-D_POSIX_C_SOURCE=200809L",
            "-pthread",
            "-o",
            str(binary),
            str(root / "test/callback_queue_test.c"),
            str(root / "src/callback_queue.c"),
            str(root / "src/http_util.c"),
            str(root / "src/system_metrics.c"),
            str(root / "src/string_util.c"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    subprocess.run([str(binary)], check=True, timeout=10)
