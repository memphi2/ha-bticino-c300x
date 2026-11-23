"""Production UDP admission and all protected forwarding modes, loopback only."""

import errno
import socket
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
         "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections,--wrap=bind,--wrap=sendto", *flags,
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


def test_udp_fixture_does_not_use_service_ports(udp_binary):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as proxy, \
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as legacy:
        # An already occupied port is equally suitable for this isolation test.
        for sock, port in ((proxy, 40004), (legacy, 4000)):
            try:
                sock.bind(("127.0.0.1", port))
            except OSError as err:
                if err.errno != errno.EADDRINUSE:
                    raise
        workers = []
        try:
            for mode in ("ring", "home", "ondemand"):
                for case in ("authorized", "untrusted", "idle"):
                    workers.append(subprocess.Popen(
                        [str(udp_binary), mode, case], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True,
                    ))
            for worker in workers:
                _, stderr = worker.communicate(timeout=5)
                assert worker.returncode == 0, stderr
        finally:
            for worker in workers:
                if worker.poll() is None:
                    worker.terminate()
                    worker.communicate(timeout=5)
