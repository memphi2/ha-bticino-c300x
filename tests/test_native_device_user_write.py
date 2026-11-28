from __future__ import annotations

import subprocess
from pathlib import Path

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


def test_device_user_files_are_written_private_and_synced(tmp_path: Path) -> None:
    """The flexisip files hold SIP credentials: the temporary file must be
    private from its creation and complete on disk before it replaces the
    original."""

    binary = tmp_path / "device-user-write-test"
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(
        [
            "gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
            "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
            str(NATIVE / "test/device_user_write_test.c"),
            str(NATIVE / "src/string_util.c"),
            str(NATIVE / "src/device_detect.c"),
            str(NATIVE / "src/file_io.c"),
            str(NATIVE / "src/sha256.c"),
            "-o", str(binary),
        ], check=True, capture_output=True, text=True,
    )

    result = subprocess.run([str(binary), str(work)], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
