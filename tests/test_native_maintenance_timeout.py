"""A QML write past its deadline gets SIGTERM and time for its rollback trap."""

import os
import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"
SOURCES = ("http_maintenance.c", "http_auth.c", "command_job.c", "string_util.c",
           "json_util.c", "json_parse.c")
ROLLBACK = "trap 'sleep 1; : > rolled; exit 130' TERM\n"
IGNORE = "trap '' TERM\n"


@pytest.fixture(scope="module", params=[False, True], ids=["host", "asan-ubsan"])
def timeout_binary(request, tmp_path_factory):
    binary = tmp_path_factory.mktemp("maintenance-timeout") / "test"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if request.param else []
    result = subprocess.run(
        ["cc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
         "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L", *flags,
         str(NATIVE / "test/maintenance_timeout_test.c"),
         *(str(NATIVE / "src" / name) for name in SOURCES),
         "-o", str(binary)], capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize("mode,trap", [
    # Past the deadline: SIGTERM, the trap rolls back, the answer says so.
    ("rollback", ROLLBACK),
    # A script that ignores SIGTERM is killed when the grace period ends.
    ("ignore", IGNORE),
    # Agent shutdown during a write waits for the rollback trap.
    ("shutdown", ROLLBACK),
    # A status read has no rollback: killed and answered at its deadline.
    ("status", IGNORE),
])
def test_qml_write_deadline_terminates_gently(timeout_binary, tmp_path, mode, trap):
    script = tmp_path / "job.sh"
    script.write_text("#!/bin/sh\n" + trap + ": > started\nwhile :; do sleep 0.02; done\n")
    script.chmod(0o700)
    result = subprocess.run(
        [str(timeout_binary), str(script), mode], cwd=tmp_path,
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
             "UBSAN_OPTIONS": "halt_on_error=1"},
    )
    assert result.returncode == 0, result.stderr
