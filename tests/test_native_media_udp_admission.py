"""Production UDP admission and all protected forwarding modes, loopback only."""

import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


@pytest.fixture(scope="module", params=[False, True], ids=["host", "asan-ubsan"])
def udp_binary(request, tmp_path_factory):
    binary = tmp_path_factory.mktemp("media-udp-admission") / "probe"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if request.param else []
    result = subprocess.run(
        ["cc", "-std=c11", "-O2", "-g", "-Wall", "-Wextra", "-Werror",
         "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
         "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections", *flags,
         str(NATIVE / "test/media_udp_admission_test.c"),
         str(NATIVE / "src/time_util.c"), "-pthread", "-ldl", "-o", str(binary)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize("mode", ["ring", "home", "ondemand"])
@pytest.mark.parametrize("case", [
    "authorized", "pcmu", "csrc", "idle", "empty", "unregistered", "before_play",
    "parked", "stopping", "unanswered", "session_stopped", "stale", "disconnected",
    "untrusted", "zero", "short", "header_only", "version", "extension", "csrc_short", "oversize",
])
def test_udp_admission(udp_binary, mode, case):
    result = subprocess.run([str(udp_binary), mode, case], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
