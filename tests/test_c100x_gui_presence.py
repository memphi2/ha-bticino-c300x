"""Generation-bound live connections, not PID/marker-based GUI readiness."""

from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("sanitize", [False, True])
def test_native_presence_policy_and_socket_lifetime(tmp_path, sanitize):
    binary = tmp_path / "presence"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else []
    subprocess.run([
        "cc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-D_DEFAULT_SOURCE",
        "-D_POSIX_C_SOURCE=200809L", "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
        "-Wl,--wrap=c300x_http_send_json", "-Wl,--wrap=close_agent_socket", *flags,
        str(ROOT / "tests/fixtures/c100x_presence.c"),
        *(str(ROOT / "native_agent/src" / name) for name in
          ("c100x_gui_presence.c", "http_auth.c", "http_util.c", "string_util.c")),
        "-o", str(binary),
    ], check=True, capture_output=True, text=True, timeout=30)
    subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=10)


def test_qml_presence_cancels_on_guard_or_generation_change():
    subprocess.run(["node", str(ROOT / "tests/fixtures/c100x_presence_probe.js"),
                    str(ROOT / "device_qml/c100x/js/c100x_presence.js")], check=True, timeout=10)
