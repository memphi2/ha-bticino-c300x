"""Legacy exit-only jobs: bounded ownership, no invented deadline/output cap."""

import os
import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


@pytest.fixture(scope="module", params=[False, True], ids=["host", "asan-ubsan"])
def wait_binary(request, tmp_path_factory):
    binary = tmp_path_factory.mktemp("command-wait") / "test"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if request.param else []
    result = subprocess.run(
        ["cc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
         "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L", *flags,
         str(NATIVE / "test/command_job_wait_test.c"), str(NATIVE / "src/command_job.c"),
         "-o", str(binary)], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize("case", ["ok", "fail", "cancel"])
def test_wait_job_contract(wait_binary, tmp_path, case):
    script = tmp_path / "job.sh"
    script.write_text(
        "#!/bin/sh\n"
        "for fd in /proc/$$/fd/*; do readlink \"$fd\"; done > descriptors\n"
        "head -c 100000 /dev/zero\nexec 1>&-\n"
        "while [ ! -e release ]; do sleep 0.01; done\n"
        '[ "$1" != fail ]\n'
    )
    script.chmod(0o700)
    result = subprocess.run([str(wait_binary), str(script), case], cwd=tmp_path,
                            capture_output=True, text=True, timeout=10,
                            env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
                                 "UBSAN_OPTIONS": "halt_on_error=1"})
    assert result.returncode == 0, result.stderr
    assert "socket:" not in (tmp_path / "descriptors").read_text()
