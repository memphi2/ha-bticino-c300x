"""The text memo staging never follows a name in the world-writable records path."""

import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


@pytest.mark.parametrize("sanitize", [False, True], ids=["host", "asan-ubsan"])
def test_text_memo_stage_follows_no_symlink(tmp_path: Path, sanitize: bool) -> None:
    binary = tmp_path / "text-memo-stage"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else ["-O2"]
    build = subprocess.run(
        ["cc", "-std=c11", "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L", "-g", "-Wall", "-Wextra",
         "-Werror", *flags, str(NATIVE / "test/text_memo_stage_test.c"), str(NATIVE / "src/memo_store.c"),
         str(NATIVE / "src/string_util.c"), "-o", str(binary)],
        capture_output=True, text=True, timeout=60,
    )
    assert build.returncode == 0, build.stderr
    work = tmp_path / "work"
    work.mkdir()

    result = subprocess.run([str(binary), str(work)], capture_output=True, text=True, timeout=10)

    assert result.returncode == 0, result.stderr
