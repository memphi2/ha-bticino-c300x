"""Device writers leave / as they found it, also when their writes nest."""

import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


@pytest.mark.parametrize("sanitize", [False, True], ids=["host", "asan-ubsan"])
def test_root_is_left_as_found(tmp_path, sanitize):
    binary = tmp_path / "root-mount"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else ["-O2"]
    result = subprocess.run(
        ["cc", "-std=c11", "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L", "-Wall", "-Wextra", "-Werror", *flags,
         str(NATIVE / "test/root_mount_test.c"),
         *(str(NATIVE / "src" / name) for name in (
             "root_mount.c", "device_file.c", "device_patch_io.c", "sha256.c", "string_util.c")),
         "-pthread", "-Wl,--wrap=statvfs,--wrap=system", "-o", str(binary)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
