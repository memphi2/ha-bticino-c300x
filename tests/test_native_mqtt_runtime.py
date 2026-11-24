"""Production MQTT command ordering without a broker or device."""

import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("sanitize", [False, True])
def test_coalesced_mqtt_commands(tmp_path, sanitize):
    native = Path(__file__).resolve().parents[1] / "native_agent"
    executable = tmp_path / "mqtt-commands"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else []
    subprocess.run(
        ["cc", "-std=c11", "-D_DEFAULT_SOURCE", "-Wall", "-Wextra", "-Werror",
         "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections", *flags,
         str(native / "test/mqtt_commands_test.c"), str(native / "src/string_util.c"),
         str(native / "src/mqtt_packet.c"),
         "-o", str(executable)], check=True, capture_output=True, text=True,
    )
    subprocess.run([str(executable)], check=True, timeout=5)
