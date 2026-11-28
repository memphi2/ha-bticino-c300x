"""Exercise the real update/file code without running an agent or touching a device."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("legacy_file_set", [False, True])
def test_update_paths_hashes_and_unchanged_file_writes(tmp_path, sanitize, legacy_file_set):
    binary = tmp_path / "update-test"
    root = ROOT / "native_agent"
    if legacy_file_set:
        root = tmp_path / "file-set-3"
        (root / "src").mkdir(parents=True)
        (root / "test").mkdir()
        for source in (ROOT / "native_agent/src").glob("*.[ch]"):
            shutil.copyfile(source, root / "src" / source.name)
        shutil.copyfile(ROOT / "native_agent/test/agent_update_test.c", root / "test/agent_update_test.c")
        header = root / "src/agent_update_paths.h"
        before = header.read_text()
        after = "\n".join(line for line in before.splitlines() if "C300XEnergyConsumers.qml" not in line) + "\n"
        assert before != after
        header.write_text(after)
    flags = ["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else ["-O2"]
    sources = ["test/agent_update_test.c", "src/file_io.c", "src/string_util.c", "src/json_util.c", "src/json_parse.c", "src/sha256.c"]
    result = subprocess.run(
        ["cc", "-std=c11", "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
         "-Wall", "-Wextra", "-Werror", *flags,
         *(str(root / source) for source in sources), "-o", str(binary)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(binary), str(tmp_path)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
