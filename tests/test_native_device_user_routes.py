"""Real script jobs and sanitizers; device writes are C stubs, never host writes."""

import os
import subprocess
from pathlib import Path

import pytest
from test_native_routing_firmware_restore import FIRMWARE_ROOT, original

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
             "command_job.c", "string_util.c", "json_util.c", "json_parse.c")],
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
] + [("ensure", case) for case in ("routing-failure", "user-failure", "user-failure-patched", "invalid", "false")]
  + [("restore", "restore-failure"), ("restore", "false"),
     ("restore", "invalid-json"), ("ensure", "invalid-json"), ("status", "c100x"), ("ensure", "c100x"),
     ("restore", "c100x"),
     ("ensure", "busy-root"), ("restore", "busy-root"),
     # A label write that hangs: SIGTERM at the write deadline, the script's
     # rollback, then 504; one that ignores the signal is killed after the grace.
     ("ensure", "label-timeout"), ("restore", "label-timeout"),
     ("ensure", "label-kill"), ("restore", "label-kill")])
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
    elif case == "c100x":
        # A C100X has no Display patch: the script must not be run for the label.
        body = f"touch {tmp_path / 'ran'}\nexit 1\n"
    elif case == "invalid":
        body = "printf invalid\n"
    elif case == "false":
        body = 'printf \'{"ok":false}\'\n'
    elif case == "invalid-json":
        body = 'printf \'{"ok":true\'\n'
    elif case in ("label-timeout", "label-kill"):
        # Ends by itself, so a run against a route that waits leaves no stand-in.
        trap = "trap 'sleep 0.2; : > \"$0.rolled\"; exit 130' TERM\n" if case == "label-timeout" else "trap '' TERM\n"
        body = trap + ': > "$0.started"\ni=0\nwhile [ $i -lt 600 ]; do sleep 0.02; i=$((i + 1)); done\n'
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
    assert not (tmp_path / "ran").exists()


def test_c100x_restore_with_real_detector_and_rejecting_stock_script(tmp_path):
    original("c100x-1.5.8")  # Skip only when the read-only firmware input is absent.
    rootfs = FIRMWARE_ROOT / "rootfs-c100x-1.5.8"
    binary = tmp_path / "route"
    result = subprocess.run([
        "cc", "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror",
        "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
        str(NATIVE / "test/http_device_user_stock_test.c"),
        *[str(NATIVE / "src" / name) for name in (
            "http_device_user.c", "http_maintenance.c", "http_auth.c", "command_job.c",
            "string_util.c", "json_util.c", "json_parse.c", "file_io.c",
            "sha256.c", "device_user_label.c")],
        "-o", str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    env = {**os.environ,
           "C300X_QML_C100X_MARKER": str(rootfs / "home/bticino/bin/gui/BtClass100"),
           "C300X_QML_QT5_MARKER": str(rootfs / "usr/lib/libQt5Core.so.5"),
           "C300X_QML_GUI_DIR": str(tmp_path / "no-gui")}
    script = NATIVE / "scripts/qml_patch.sh"
    rejected = subprocess.run([str(script), "media-user-label-restore"], env=env,
                              capture_output=True, text=True, timeout=10)
    assert rejected.returncode == 3 and "unsupported_display" in rejected.stdout
    # The handler must still return 200 and invoke routing restore exactly once.
    result = subprocess.run([str(binary), "c100x", str(script), "restore"], env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("sanitize", [False, True], ids=["host", "asan-ubsan"])
def test_remove_route_target_keeps_an_unparsable_last_line(tmp_path, sanitize):
    """A last line without a newline once overflowed the size check.

    It kept an HA mention that cannot be parsed, so nothing was removed and
    the newline that was never there was counted: ensure answered
    route_too_large on every try.
    """
    binary = tmp_path / "route-target"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else []
    result = subprocess.run(
        ["cc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
         "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L", *flags,
         str(NATIVE / "test/device_user_route_target_test.c"),
         *[str(NATIVE / "src" / name) for name in ("string_util.c", "json_util.c", "json_parse.c", "time_util.c",
                                                   "device_detect.c")],
         "-o", str(binary)], capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
