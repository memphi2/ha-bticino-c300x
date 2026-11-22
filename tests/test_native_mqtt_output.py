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


@pytest.mark.parametrize("sanitize", [False, True], ids=["host", "asan-ubsan"])
def test_mqtt_poll_state(tmp_path, sanitize):
    binary = tmp_path / "mqtt-poll"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else []
    result = subprocess.run(
        ["cc", "-std=c11", "-D_DEFAULT_SOURCE", "-g", "-O1", "-Wall", "-Wextra", "-Werror",
         *flags, str(NATIVE / "test/mqtt_poll_test.c"), str(NATIVE / "src/mqtt_output.c"),
         str(NATIVE / "src/string_util.c"), "-Wl,--wrap=send", "-o", str(binary)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run(
        [str(binary)], capture_output=True, text=True, timeout=5,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
             "UBSAN_OPTIONS": "halt_on_error=1"},
    )
    assert result.returncode == 0, result.stderr
