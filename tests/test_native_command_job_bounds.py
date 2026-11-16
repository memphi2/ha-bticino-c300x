"""Exact command-output limits for strict jobs and legacy prefix captures."""

import os
import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


@pytest.fixture(scope="module", params=[False, True], ids=["host", "asan-ubsan"])
def bounds_binary(request, tmp_path_factory):
    binary = tmp_path_factory.mktemp("command-bounds") / "test"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if request.param else []
    result = subprocess.run(
        ["cc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
         "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L", *flags,
         str(NATIVE / "test/command_job_bounds_test.c"),
         str(NATIVE / "src/command_job.c"), str(NATIVE / "src/time_util.c"),
         "-o", str(binary)], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize("capture,size,emitted", [
    (0, 4096, 0), (0, 4096, 4095), (0, 4096, 4096), (0, 4096, 100000),
    (1, 1, 0), (1, 1, 1000), (1, 4096, 4095), (1, 4096, 4096),
    (1, 8192, 8191), (1, 8192, 8192), (1, 8192, 100000),
])
def test_command_capture_boundaries(bounds_binary, tmp_path, capture, size, emitted):
    script = tmp_path / "job.sh"
    script.write_text(f"#!/bin/sh\nhead -c {emitted} /dev/zero | tr '\\000' x\n")
    script.chmod(0o700)
    result = subprocess.run(
        [str(bounds_binary), str(script), str(capture), str(size), str(emitted)],
        capture_output=True, text=True, timeout=10,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
             "UBSAN_OPTIONS": "halt_on_error=1"},
    )
    assert result.returncode == 0, result.stderr
