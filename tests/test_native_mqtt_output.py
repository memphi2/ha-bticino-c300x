"""Bounded MQTT framing and nonblocking output ownership."""

import os
import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


@pytest.mark.parametrize("sanitize", [False, True], ids=["host", "asan-ubsan"])
def test_mqtt_output_boundaries(tmp_path, sanitize):
    binary = tmp_path / "mqtt-output"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else []
    result = subprocess.run(
        ["cc", "-std=c11", "-g", "-O1", "-Wall", "-Wextra", "-Werror", *flags,
         str(NATIVE / "test/mqtt_output_test.c"), str(NATIVE / "src/mqtt_output.c"),
         "-Wl,--wrap=send", "-o", str(binary)], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run(
        [str(binary)], capture_output=True, text=True, timeout=5,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
             "UBSAN_OPTIONS": "halt_on_error=1"},
    )
    assert result.returncode == 0, result.stderr


MQTT_CONNECT_SOURCES = [str(NATIVE / "src" / name) for name in (
    "mqtt_connect.c", "mqtt_packet.c", "openwebnet_waiters.c", "request_queue.c")]


@pytest.mark.parametrize("case", ["slow_dns", "cancel", "deadline"])
@pytest.mark.parametrize("sanitize", [False, True], ids=["host", "asan-ubsan"])
def test_mqtt_connect_runs_beside_the_loop(tmp_path, sanitize, case):
    """getaddrinfo and connect once ran on the loop thread at every retry."""
    binary = tmp_path / "mqtt-connect"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else []
    result = subprocess.run(
        ["cc", "-std=c11", "-D_DEFAULT_SOURCE", "-g", "-O1", "-Wall", "-Wextra", "-Werror", *flags,
         "-DMQTT_RESOLVE_CONNECT_TIMEOUT_MS=2000", str(NATIVE / "test/mqtt_connect_test.c"),
         *(str(NATIVE / "src" / name) for name in (
             "mqtt_bridge.c", "mqtt_output.c", "string_util.c", "http_util.c", "time_util.c")),
         *MQTT_CONNECT_SOURCES, "-pthread", "-Wl,--wrap=getaddrinfo", "-o", str(binary)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(binary), case], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("sanitize", [False, True], ids=["host", "asan-ubsan"])
def test_mqtt_poll_state(tmp_path, sanitize):
    binary = tmp_path / "mqtt-poll"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else []
    result = subprocess.run(
        ["cc", "-std=c11", "-D_DEFAULT_SOURCE", "-g", "-O1", "-Wall", "-Wextra", "-Werror",
         *flags, str(NATIVE / "test/mqtt_poll_test.c"), str(NATIVE / "src/mqtt_output.c"),
         str(NATIVE / "src/string_util.c"), *MQTT_CONNECT_SOURCES, "-pthread",
         "-Wl,--wrap=send", "-o", str(binary)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run(
        [str(binary)], capture_output=True, text=True, timeout=5,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
             "UBSAN_OPTIONS": "halt_on_error=1"},
    )
    assert result.returncode == 0, result.stderr
