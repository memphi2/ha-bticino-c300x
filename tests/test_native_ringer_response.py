"""Bounded ringer JSON through production readback and HTTP response code."""

import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="module", params=[False, True], ids=["host", "asan-ubsan"])
def ringer_response_binary(request, tmp_path_factory):
    native = Path(__file__).resolve().parents[1] / "native_agent"
    binary = tmp_path_factory.mktemp("ringer-response") / "ringer-response"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if request.param else []
    include = os.environ.get("CURL_INCLUDE_DIR")
    if include:
        flags += ["-idirafter", include]
    sources = sorted(str(path) for path in (native / "src").glob("*.c")
                     if path.name not in {"http.c", "main.c"})
    build = subprocess.run(
        ["cc", "-std=c11", "-O1", "-g", "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
         "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
         "-Wl,--wrap=nanosleep", "-Wl,--wrap=c300x_device_display_files_patchable",
         *flags, str(native / "test/ringer_response_test.c"),
         *sources, "-pthread", "-ldl", "-o", str(binary)],
        capture_output=True, text=True, timeout=120,
    )
    assert build.returncode == 0, build.stderr
    return binary


@pytest.mark.parametrize("case", [
    "malformed", "mismatch", "volume", "combined",
    "normal-volume", "normal-combined", "normal-muted",
    "short-malformed", "short-mismatch", "unpatchable",
])
def test_ringer_response_is_bounded_json(ringer_response_binary, case):
    result = subprocess.run([str(ringer_response_binary), case],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
