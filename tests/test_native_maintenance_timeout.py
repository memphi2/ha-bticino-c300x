"""A QML write past its deadline gets SIGTERM and time for its rollback trap."""

import os
import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"
SOURCES = ("http_maintenance.c", "qml_recovery.c", "http_auth.c", "command_job.c", "string_util.c",
           "json_util.c", "json_parse.c")
ROLLBACK = "trap 'echo t >> terms; sleep 1; : > rolled; exit 130' TERM\n"
# The output pipe stays open after the deadline, so a trap that prints lives.
ROLLBACK_PRINTS = ("trap 'echo t >> terms; printf \"rolling back\\n\"; sleep 1; "
                   "printf \"done\\n\"; : > rolled; exit 130' TERM\n")
FAILED_ROLLBACK = "trap 'echo t >> terms; sleep 1; exit 131' TERM\n"
IGNORE = "trap '' TERM\n"
LOOP = "while :; do sleep 0.02; done\n"
AFTER_FINISH = "while [ ! -e finish ]; do sleep 0.02; done\n"


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


@pytest.mark.parametrize("mode,trap,body", [
    # Past the deadline: SIGTERM, the trap rolls back, the answer says so.
    ("rollback", ROLLBACK, LOOP),
    ("rollback", ROLLBACK_PRINTS, LOOP),
    # A trap that cannot finish its rollback exits 131: rolled_back false.
    ("failed-rollback", FAILED_ROLLBACK, LOOP),
    # A script that ignores SIGTERM is killed when the grace period ends.
    ("ignore", IGNORE, LOOP),
    # Agent shutdown during a write waits for the rollback trap.
    ("shutdown", ROLLBACK, LOOP),
    # Shutdown during the deadline's grace period sends no second SIGTERM.
    ("shutdown-grace", ROLLBACK, LOOP),
    # A status read has no rollback: killed and answered at its deadline.
    ("status", IGNORE, LOOP),
    # A write that ended by itself is answered with its own output, even when
    # it is reaped only on the deadline tick.
    ("deadline-exit", "", 'printf \'{"ok":true,"changed_files":1}\\n\'\n' + AFTER_FINISH),
    # A write that fails before its deadline is no timeout.
    ("exit131", "", AFTER_FINISH + "exit 131\n"),
    # An output overflow fails the write; it still gets SIGTERM and its grace.
    ("overflow", ROLLBACK, AFTER_FINISH + "head -c 5000 /dev/zero | tr '\\0' x\n" + LOOP),
    # Agent start: the recovery job holds the slot, with the write deadline.
    ("recover", ROLLBACK, LOOP),
    # A GUI reload keeps 2.9.2's 10 s limit on Qt 4 (firmware 1.7.x/2.0.2);
    # on the Qt 5 display it waits for the old program, up to the write limit.
    ("reload-qt4", "", LOOP),
    ("reload-qt5", "", LOOP),
])
def test_qml_write_deadline_terminates_gently(timeout_binary, tmp_path, mode, trap, body):
    script = tmp_path / "job.sh"
    script.write_text("#!/bin/sh\n" + trap + ": > started\n" + body)
    script.chmod(0o700)
    result = subprocess.run(
        [str(timeout_binary), str(script), mode], cwd=tmp_path,
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
             "UBSAN_OPTIONS": "halt_on_error=1"},
    )
    assert result.returncode == 0, result.stderr
