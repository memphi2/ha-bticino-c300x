"""Offline codec temporary-file permissions and failure cleanup."""

import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


@pytest.mark.parametrize("sanitize", [False, True], ids=["host", "asan-ubsan"])
def test_private_codec_writes(tmp_path: Path, sanitize: bool) -> None:
    binary = tmp_path / "codec-write"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else []
    subprocess.run(
        ["cc", "-std=c11", "-O2", "-g", "-Wall", "-Wextra", "-Werror",
         "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L", *flags,
         str(NATIVE / "test/audio_codec_write_test.c"), str(NATIVE / "src/root_mount.c"),
         str(NATIVE / "src/device_file_sync.c"), "-o", str(binary)],
        check=True, capture_output=True, text=True, timeout=30,
    )
    work = tmp_path / "work"
    work.mkdir()
    result = subprocess.run([str(binary), str(work)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
