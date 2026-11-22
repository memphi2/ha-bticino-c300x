"""Shared native JSON decoding and atomic secret-file persistence."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "native_agent"


@pytest.mark.parametrize("sanitize", [False, True])
def test_json_decoding_and_private_config_creation(tmp_path, sanitize):
    binary = tmp_path / "json-config-test"
    flags = ["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else ["-O2"]
    result = subprocess.run(
        ["cc", "-std=c11", "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
         "-Wall", "-Wextra", "-Werror", *flags,
         *(str(ROOT / source) for source in [
             "test/json_config_test.c", "src/json_util.c", "src/json_parse.c", "src/string_util.c",
         ]), "-o", str(binary)], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(binary), str(tmp_path)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
