"""Signal wakeups stay nonblocking and reuse one process-lifetime pipe."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "native_agent"


@pytest.mark.parametrize("sanitize", [False, True])
def test_signal_wakeup_pipe(tmp_path, sanitize):
    binary = tmp_path / "signal-wakeup"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else []
    built = subprocess.run(
        ["cc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", *flags,
         str(ROOT / "test/signal_wakeup_test.c"), str(ROOT / "src/signal_wakeup.c"),
         "-o", str(binary)], capture_output=True, text=True, timeout=30,
    )
    assert built.returncode == 0, built.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
