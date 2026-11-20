"""Display callback deadlines through the production queue and completion path."""

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("sanitize", [False, True], ids=["host", "asan-ubsan"])
def test_display_deadline_releases_pending_command(tmp_path: Path, sanitize: bool) -> None:
    native = Path(__file__).resolve().parents[1] / "native_agent"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else []
    include = os.environ.get("CURL_INCLUDE_DIR")
    if include:
        flags += ["-idirafter", include]
    sources = [
        "callback_queue", "display_callback", "http_callback", "http_util",
        "http_response", "https_client", "openwebnet", "system_metrics", "time_util",
    ]
    binary = tmp_path / "display-deadline"
    build = subprocess.run(
        ["cc", "-std=c11", "-O1", "-g", "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
         "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections", *flags,
         str(native / "test/display_deadline_test.c"),
         *(str(native / f"src/{source}.c") for source in sources),
         "-pthread", "-ldl", "-o", str(binary)],
        capture_output=True, text=True, timeout=60,
    )
    assert build.returncode == 0, build.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
