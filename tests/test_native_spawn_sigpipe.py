"""Scripts started by the agent must not inherit its ignored SIGPIPE."""

import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


@pytest.mark.parametrize("sanitize", [False, True], ids=["host", "asan-ubsan"])
def test_spawned_scripts_get_default_sigpipe(tmp_path, sanitize):
    binary = tmp_path / "spawn-sigpipe"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else ["-O2"]
    result = subprocess.run(
        ["cc", "-std=c11", "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L", "-g", "-Wall", "-Wextra",
         "-Werror", *flags, str(NATIVE / "test/spawn_sigpipe_test.c"),
         *(str(NATIVE / "src" / name) for name in ("command_job.c", "command_transaction.c", "time_util.c")),
         "-o", str(binary)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(binary), str(tmp_path)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
