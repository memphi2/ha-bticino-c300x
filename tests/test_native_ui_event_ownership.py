"""UI waiter slot replacement must invalidate an old socket's poll result."""

import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="module", params=[False, True], ids=["host", "asan-ubsan"])
def ui_event_binary(request, tmp_path_factory):
    native = Path(__file__).resolve().parents[1] / "native_agent"
    binary = tmp_path_factory.mktemp("ui-event-ownership") / "ui-events"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if request.param else []
    build = subprocess.run(
        ["cc", "-std=c11", "-O2", "-g", "-Wall", "-Wextra", "-Werror",
         "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
         "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections", *flags,
         str(native / "test/ui_event_ownership_test.c"),
         *(str(native / f"src/{name}.c") for name in ["ui_events", "http_util", "json_util", "time_util"]),
         "-o", str(binary)],
        capture_output=True, text=True, timeout=30,
    )
    assert build.returncode == 0, build.stderr
    return binary


@pytest.mark.parametrize("case", ["overflow", "notify"])
def test_stale_ui_waiter_poll_result(ui_event_binary, case):
    result = subprocess.run([str(ui_event_binary), case],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
