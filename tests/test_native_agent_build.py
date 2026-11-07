"""Exercise the production Makefile with a tiny, isolated native program."""

import shutil
import subprocess
import sys
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


@pytest.mark.parametrize("symbols,code,ok", [
    ("GLIBC_2.4 GLIBC_2.26", 0, True),
    ("GLIBC_2.2.5 GLIBC_2.17", 0, True),
    ("GLIBC_2.27", 0, False),
    ("GLIBC_2.100", 0, False),
    ("GLIBC_3.0", 0, False),
    ("GLIBC_2.4 GLIBC_ABI_DT_RELR", 0, False),
    ("", 0, False),
    ("GLIBC_2.4", 1, False),
])
def test_abi_gate_rejects_tool_errors_and_incompatible_versions(tmp_path, symbols, code, ok):
    native = tmp_path / "native_agent"
    native.mkdir()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(ROOT / "native_agent/Makefile", native)
    shutil.copy(ROOT / "scripts/check_agent_abi.py", scripts)
    tool = tmp_path / "readelf"
    tool.write_text(f"#!{sys.executable}\nprint({symbols!r})\nraise SystemExit({code})\n")
    tool.chmod(0o700)
    result = make(native, "-o", "build/armhf/c300x-agent-native", "armhf-abi-check",
                  f"ARMHF_READELF={tool}", f"PYTHON={sys.executable}")
    assert (result.returncode == 0) is ok, result.stdout + result.stderr
    assert ("ARMHF ABI check passed" in result.stdout) is ok


def test_abi_gate_rejects_missing_tool(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_agent_abi.py"), "unused",
         "--readelf", str(tmp_path / "missing-readelf")],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    assert "ARMHF ABI check passed" not in result.stdout
