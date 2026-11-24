"""The firewall writer never chmods the script path by name after the rename."""

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("sanitize", [False, True], ids=["host", "asan-ubsan"])
def test_firewall_write_sets_the_mode_before_the_rename(tmp_path: Path, sanitize: bool) -> None:
    native = Path(__file__).resolve().parents[1] / "native_agent"
    binary = tmp_path / "firewall-file"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else []
    include = os.environ.get("CURL_INCLUDE_DIR")
    if include:
        flags += ["-idirafter", include]
    sources = sorted(str(path) for path in (native / "src").glob("*.c")
                     if path.name not in {"http.c", "main.c"})
    build = subprocess.run(
        ["cc", "-std=c11", "-O1", "-g", "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
         "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections", "-Wl,--wrap=rename", *flags,
         str(native / "test/firewall_file_test.c"), *sources, "-pthread", "-ldl", "-o", str(binary)],
        capture_output=True, text=True, timeout=120,
    )
    assert build.returncode == 0, build.stderr
    work = tmp_path / "work"
    work.mkdir()

    result = subprocess.run([str(binary), str(work)], capture_output=True, text=True, timeout=10,
                            env={**os.environ, "C300X_AUDIO_NO_REMOUNT": "1"})

    assert result.returncode == 0, result.stderr
