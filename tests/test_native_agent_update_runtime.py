"""Exercise the real update/file code without running an agent or touching a device."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("sanitize", [False, True])
def test_update_paths_hashes_and_unchanged_file_writes(tmp_path, sanitize):
    binary = tmp_path / "update-test"
    flags = ["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else ["-O2"]
    sources = ["test/agent_update_test.c", "src/file_io.c", "src/string_util.c", "src/json_util.c", "src/sha256.c"]
    result = subprocess.run(
        ["cc", "-std=c11", "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
         "-Wall", "-Wextra", "-Werror", *flags,
         *(str(ROOT / "native_agent" / source) for source in sources), "-o", str(binary)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(binary), str(tmp_path)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
