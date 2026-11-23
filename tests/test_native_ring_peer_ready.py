"""Ring UDP readiness is queried for a real HTTP peer, not inferred from counters."""

import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


@pytest.fixture(scope="module", params=[False, True], ids=["host", "asan-ubsan"])
def peer_ready_binary(request, tmp_path_factory):
    binary = tmp_path_factory.mktemp("ring-peer-ready") / "probe"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if request.param else []
    result = subprocess.run([
        "cc", "-std=c11", "-O2", "-g", "-Wall", "-Wextra", "-Werror",
        "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
        "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections", *flags,
        str(NATIVE / "test/media_ring_peer_ready_test.c"), str(NATIVE / "src/time_util.c"),
        "-pthread", "-ldl", "-o", str(binary),
    ], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize("case", [
    "ready", "preplay", "inactive", "parked", "stale", "disconnected", "pending_data",
    "http_mapped", "rtsp_mapped", "http_ipv6", "rtsp_ipv6", "other_http_ip", "other_rtsp_ip",
    "stopped_listener", "missing_listener", "closed_listener", "unbound_listener", "tcp_listener",
    "inactive_ring", "unanswered", "no_audio", "ring_stopping", "receiver_stopping",
    "bridge_stopping", "proxy_stopping", "proxy_joining", "no_srtp", "no_srtp_audio",
    "no_output", "no_target", "wrong_video", "null_video", "invalid_peer", "unconnected_peer",
])
def test_ring_peer_ready(peer_ready_binary, case):
    result = subprocess.run([str(peer_ready_binary), case], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
