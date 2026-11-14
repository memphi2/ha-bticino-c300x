from __future__ import annotations

import subprocess
from pathlib import Path

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


def test_installed_and_staged_files_are_synced_before_they_are_published(
    tmp_path: Path,
) -> None:
    """A file that replaces an agent file must be on the disk first: after a
    power cut the renamed binary would otherwise be empty or truncated."""

    binary = tmp_path / "file-io-sync-test"
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(
        [
            "gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
            "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
            str(NATIVE / "test/file_io_sync_test.c"),
            str(NATIVE / "src/sha256.c"),
            str(NATIVE / "src/string_util.c"),
            "-o", str(binary),
        ], check=True, capture_output=True, text=True,
    )

    result = subprocess.run([str(binary), str(work)], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
