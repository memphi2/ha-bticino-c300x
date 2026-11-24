"""Commands the agent starts are bounded, get a clean process, and leave no zombie."""

import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


@pytest.mark.parametrize("sanitize", [False, True], ids=["host", "asan-ubsan"])
def test_detached_command(tmp_path, sanitize):
    binary = tmp_path / "detached"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else ["-O2"]
    result = subprocess.run(
        ["cc", "-std=c11", "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L", "-g", "-Wall", "-Wextra",
         "-Werror", *flags, "-DC300X_DETACHED_COMMAND_WAIT_MS=300",
         str(NATIVE / "test/detached_command_test.c"), str(NATIVE / "src/detached_command.c"),
         "-o", str(binary)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(binary), str(tmp_path)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
