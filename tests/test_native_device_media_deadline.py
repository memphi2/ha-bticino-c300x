"""Device-media command deadlines with simulated sockets and clocks only."""

import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


@pytest.fixture(scope="module", params=[False, True], ids=["host", "asan-ubsan"])
def deadline_binary(request, tmp_path_factory):
    binary = tmp_path_factory.mktemp("device-media-deadline") / "test"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if request.param else []
    result = subprocess.run(
        ["cc", "-std=c11", "-O2", "-g", "-Wall", "-Wextra", "-Werror",
         "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L", *flags,
         str(NATIVE / "test/device_media_deadline_test.c"), "-o", str(binary)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize("case", range(24), ids=[
    "protocol", "connect-timeout", "connect-error", "send-timeout", "read-timeout",
    "interrupted", "partial-retries", "nack", "clock-error", "socket-error",
    "poll-error", "send-error", "read-error", "socket-option-error",
    "fragmented-ack", "fragmented-nack", "fragmented-timeout", "reply-full", "eof",
    "takeover-stream-at-once", "takeover-stream-late", "takeover-no-stream",
    "takeover-refused", "takeover-cancelled",
])
def test_device_media_deadline(deadline_binary, case):
    result = subprocess.run([str(deadline_binary), str(case)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
