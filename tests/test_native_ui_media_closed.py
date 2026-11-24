"""The GUI call-end hook never ends HA media (stream startup, answered ring)."""

import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("sanitize", [False, True], ids=["host", "asan-ubsan"])
def test_ui_media_closed_during_startup(tmp_path: Path, sanitize: bool) -> None:
    native = Path(__file__).resolve().parents[1] / "native_agent"
    sources = sorted(
        str(path) for path in (native / "src").glob("*.c")
        if path.name not in {"http.c", "main.c"}
    )
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else []
    binary = tmp_path / "ui-media-closed"
    build = subprocess.run(
        [
            "cc", "-std=c11", "-O1", "-g",
            "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
            "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
            "-Wl,--wrap=c300x_monotonic_ms", *flags,
            str(native / "test/ui_media_closed_test.c"), *sources,
            "-pthread", "-ldl", "-o", str(binary),
        ],
        capture_output=True, text=True, timeout=120,
    )
    assert build.returncode == 0, build.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
