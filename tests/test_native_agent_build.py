"""Exercise the production Makefile with a tiny, isolated native program."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def build_tree(tmp_path):
    shutil.copy(ROOT / "native_agent/Makefile", tmp_path)
    (tmp_path / "VERSION").write_text("1.0.0\n")
    source = tmp_path / "src"
    source.mkdir()
    (source / "main.c").write_text(
        '#include <stdio.h>\nint main(void) { puts(C300X_NATIVE_AGENT_VERSION); return 0; }\n'
    )
    return tmp_path


def make(tree, *args):
    return subprocess.run(
        ["make", "--no-print-directory", *args], cwd=tree,
        capture_output=True, text=True, timeout=30,
    )


def test_incremental_build_tracks_version_and_flags_without_rebuilding_unchanged(build_tree):
    binary = build_tree / "build/host/c300x-agent-native"

    def build(expected, *args):
        result = make(build_tree, "all", *args)
        assert result.returncode == 0, result.stdout + result.stderr
        assert subprocess.check_output([binary], text=True).strip() == expected

    build("1.0.0")
    stamp = binary.stat().st_mtime_ns
    build("1.0.0")
    assert binary.stat().st_mtime_ns == stamp
    (build_tree / "VERSION").write_text("2.0.0\n")
    build("2.0.0")
    build("3.0.0", "AGENT_VERSION=3.0.0")
    stamp = binary.stat().st_mtime_ns
    build("3.0.0", "AGENT_VERSION=3.0.0", "LDFLAGS=-pthread -ldl -Wl,--as-needed")
    assert binary.stat().st_mtime_ns != stamp
