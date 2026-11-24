"""Real script jobs and sanitizers; device writes are C stubs, never host writes."""

import os
import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


@pytest.fixture(scope="module", params=[False, True], ids=["host", "asan-ubsan"])
def route_binary(request, tmp_path_factory):
    binary = tmp_path_factory.mktemp("device-user-routes") / "test"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if request.param else []
    result = subprocess.run(
        ["cc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
         "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L", *flags,
         str(NATIVE / "test/http_device_user_test.c"),
         *[str(NATIVE / "src" / name) for name in (
             "http_device_user.c", "device_user_label.c", "http_maintenance.c", "http_auth.c",
             "command_job.c", "command_transaction.c", "string_util.c", "json_util.c", "json_parse.c")],
         "-o", str(binary)], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize("operation,case", [
    (operation, case)
    for operation in ("status", "ensure", "restore")
    for case in ("success", "failure", "overflow", "missing", "timeout", "shutdown")
    if operation == "status" or case not in ("timeout", "shutdown")
] + [
    (operation, case)
    for operation in ("ensure", "restore")
    for case in ("unauthorized", "unconfirmed")
] + [("ensure", case) for case in ("routing-failure", "user-failure", "invalid", "false")]
  + [("restore", "restore-failure")])
def test_route_state_machine(route_binary, tmp_path, operation, case):
    script = tmp_path / "job.sh"
    body = ('case "$1" in\n'
            'status) printf \'{"media_user_label_state":"patched"}\';;\n'
            'media-user-label-apply) printf \'{"ok":true}\';;\n'
            'media-user-label-restore) printf "non-json success";;\n'
            'esac\n')
    if case in ("timeout", "shutdown"):
        body = "exec sleep 30\n"
    elif case == "failure":
        body = "exit 1\n"
    elif case == "invalid":
        body = "printf invalid\n"
    elif case == "false":
        body = 'printf \'{"ok":false}\'\n'
    elif case == "overflow":
        body += "head -c 12000 /dev/zero | tr '\\000' ' '\n"
    if case != "missing":
        script.write_text("#!/bin/sh\n" + body)
        script.chmod(0o700)
    result = subprocess.run([str(route_binary), case, str(script), operation],
                            capture_output=True, text=True, timeout=10,
                            env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
                                 "UBSAN_OPTIONS": "halt_on_error=1"})
    assert result.returncode == 0, result.stderr
