from __future__ import annotations

import subprocess
from pathlib import Path

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


def test_routing_restore_and_apply_check_the_backup(tmp_path: Path) -> None:
    """A truncated, foreign or patched backup must never replace the routing
    binary, and apply replaces such a backup instead of keeping it."""

    binary = tmp_path / "routing-backup-test"
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(
        [
            "gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
            "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
            str(NATIVE / "test/device_routing_backup_test.c"),
            str(NATIVE / "src/device_patch_io.c"),
            str(NATIVE / "src/root_mount.c"),
            str(NATIVE / "src/sha256.c"),
            str(NATIVE / "src/string_util.c"),
            "-o", str(binary),
        ], check=True, capture_output=True, text=True,
    )

    result = subprocess.run([str(binary), str(work)], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
