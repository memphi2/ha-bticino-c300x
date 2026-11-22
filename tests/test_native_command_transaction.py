"""Blocking transaction capture must never cancel file cleanup or leak children."""

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


@pytest.fixture(scope="module", params=[False, True], ids=["host", "asan-ubsan"])
def transaction_binary(request, tmp_path_factory):
    binary = tmp_path_factory.mktemp("command-transaction") / "test"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if request.param else []
    subprocess.run([
        "cc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
        "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L", *flags,
        str(NATIVE / "test/command_transaction_test.c"),
        str(NATIVE / "src/command_transaction.c"), "-o", str(binary),
    ], check=True, capture_output=True, text=True, timeout=30)
    return binary


@pytest.mark.parametrize("case,capacity,expected_ok,expected_prefix", [
    ("success", 32, 1, "test"), ("overflow", 5, 1, "test"),
    ("overflow", 1, 1, ""), ("failure", 32, 0, "test"),
    ("missing", 32, 0, ""), ("noexec", 32, 0, ""),
])
def test_capture_bounds_errors_and_reaping(transaction_binary, tmp_path, case, capacity,
                                         expected_ok, expected_prefix):
    script = tmp_path / "script"
    if case != "missing":
        script.write_text('#!/bin/sh\nprintf "%s" "$1"\n'
                          + ("head -c 50000 /dev/zero | tr '\\000' x\n" if case == "overflow" else "")
                          + ("exit 1\n" if case == "failure" else ""))
        script.chmod(0o600 if case == "noexec" else 0o700)
    result = subprocess.run([str(transaction_binary), str(script), str(capacity)],
                            capture_output=True, text=True, timeout=5,
                            env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
                                 "UBSAN_OPTIONS": "halt_on_error=1"})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "ok": expected_ok, "length": len(expected_prefix), "prefix": expected_prefix, "signals": 0,
    }


@pytest.mark.parametrize("close_stdout", [False, True])
def test_shutdown_signal_does_not_interrupt_drain_or_reap(transaction_binary, tmp_path, close_stdout):
    script = tmp_path / "script"
    script.write_text('#!/bin/sh\nprintf test\n'
                      + ("exec 1>&-\n" if close_stdout else "")
                      + 'touch started\nwhile [ ! -e release ]; do sleep 0.02; done\ntouch finished\n')
    script.chmod(0o700)
    process = subprocess.Popen([str(transaction_binary), str(script), "32"], cwd=tmp_path,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 5
        while not (tmp_path / "started").exists():
            assert process.poll() is None and time.monotonic() < deadline
            time.sleep(0.01)
        process.terminate()
        time.sleep(0.1)
        assert process.poll() is None
        (tmp_path / "release").touch()
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0, stderr
        assert (tmp_path / "finished").exists()
        assert json.loads(stdout) == {"ok": 1, "length": 4, "prefix": "test", "signals": 1}
    finally:
        (tmp_path / "release").touch()
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=5)
