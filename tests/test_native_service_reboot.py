"""Shared reboot continuation: failed scheduling is a result, not a new HTTP error."""

import os
import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


@pytest.fixture(scope="module", params=[False, True], ids=["host", "asan-ubsan"])
def reboot_binary(request, tmp_path_factory):
    binary = tmp_path_factory.mktemp("reboot-continuation") / "test"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if request.param else []
    result = subprocess.run(
        ["cc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
         "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
         '-DC300X_SSH_INIT_SCRIPT="./ssh.sh"', *flags,
         str(NATIVE / "test/http_service_reboot_test.c"),
         *[str(NATIVE / "src" / name) for name in (
             "http_service_commands.c", "ssh_status.c", "foreign_services.c", "gui_peer.c",
             "http_maintenance.c", "http_auth.c",
             "command_job.c", "string_util.c", "json_util.c", "json_parse.c")],
         "-o", str(binary)], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize("case", ["success", "failure", "immediate-failure", "cancel"])
def test_reboot_completion_ownership(reboot_binary, tmp_path, case):
    script = tmp_path / "ssh.sh"
    script.write_text("#!/bin/sh\n" + ("exec sleep 30\n" if case == "cancel" else "exit 9\n"))
    script.chmod(0o700)
    result = subprocess.run(
        [str(reboot_binary), case], cwd=tmp_path, capture_output=True, text=True, timeout=10,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
             "UBSAN_OPTIONS": "halt_on_error=1"},
    )
    assert result.returncode == 0, result.stderr
