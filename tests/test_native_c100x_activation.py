"""The C100X activation state machine: its jobs, its trial boot and its idle reboot."""

import os
import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"
SOURCES = ("c100x_activation.c", "c100x_boot_check.c", "c100x_payload.c", "c100x_reboot_gate.c",
           "command_job.c", "time_util.c", "json_util.c", "json_parse.c",
           "device_detect.c", "string_util.c")


def _build(tmp_path_factory, marker):
    binary = tmp_path_factory.mktemp("c100x-activation") / "c100x_activation_test"
    result = subprocess.run(
        ["cc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
         "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
         f'-DC300X_C100X_DISPLAY_MARKER="{marker}"',
         "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
         str(NATIVE / "test/c100x_activation_test.c"),
         *[str(NATIVE / "src" / name) for name in SOURCES],
         "-o", str(binary)], capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return binary


@pytest.fixture(scope="module")
def c100x_binary(tmp_path_factory):
    # Any existing file stands in for the C100X display program.
    return _build(tmp_path_factory, "/bin/sh")


@pytest.fixture(scope="module")
def c300x_binary(tmp_path_factory):
    return _build(tmp_path_factory, "/nonexistent/c100x-marker")


def _run(binary, case, cwd):
    result = subprocess.run(
        [str(binary), case], cwd=cwd, capture_output=True, text=True, timeout=120,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
             "UBSAN_OPTIONS": "halt_on_error=1"},
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_inert_on_a_c300x(c300x_binary, tmp_path):
    _run(c300x_binary, "inert", tmp_path)


@pytest.mark.parametrize("case", [
    "idle", "busy", "trial-fails", "trial-confirms", "no-display", "interrupted", "unknown", "requests",
    "features", "boot-check", "adapter-updated",
])
def test_c100x_activation(c100x_binary, tmp_path, case):
    _run(c100x_binary, case, tmp_path)


def test_the_update_route_has_the_adapter_read_again():
    """Without a new program the agent keeps running: only this call shows the new pages."""

    source = (NATIVE / "src/http.c").read_text(encoding="utf-8")
    applied = source.index('record_agent_write(config, runtime, "agent_update", "apply");')
    restart = source.index('c300x_run_detached_command(C300X_AGENT_INIT_SCRIPT, "restart", 500)', applied)
    assert "c100x_activation_payload_changed(&runtime->c100x_activation);" in source[applied:restart]
