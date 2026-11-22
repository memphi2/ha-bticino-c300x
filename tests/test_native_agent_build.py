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


def _abi_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_agent_abi", ROOT / "scripts/check_agent_abi.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_firmware(tmp_path, *, drop=(), lacks_runtime=None):
    """Build a root file system and a readelf that reports its symbols."""

    abi = _abi_module()
    root = tmp_path / "rootfs"
    (root / "lib").mkdir(parents=True)
    (root / "usr/lib").mkdir(parents=True)
    tables = {}
    for name in abi.SYSTEM_LIBRARIES:
        (root / "lib" / name).write_bytes(b"")
        tables[str(root / "lib" / name)] = []
    tables[str(root / "lib/libc.so.6")] = [
        name for name in ("pthread_create@GLIBC_2.4", "memcpy@GLIBC_2.4") if name not in drop
    ]
    for library, functions in abi.RUNTIME_SYMBOLS.items():
        (root / "usr/lib" / library).write_bytes(b"")
        tables[str(root / "usr/lib" / library)] = [
            name for name in functions if name != lacks_runtime
        ]
    tables["agent"] = ["UND pthread_create@GLIBC_2.4", "UND memcpy@GLIBC_2.4", "UND free"]
    tool = tmp_path / "readelf"
    tool.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        f"tables = {tables!r}\n"
        "args = sys.argv[1:]\n"
        "if args[0] == '-d':\n"
        "    print(' 0x1 (NEEDED) Shared library: [libpthread.so.0]')\n"
        "    print(' 0x1 (NEEDED) Shared library: [libc.so.6]')\n"
        "    raise SystemExit(0)\n"
        "for index, entry in enumerate(tables[args[-1]]):\n"
        "    where, _, name = entry.rpartition(' ')\n"
        "    print(f'   {index}: 00000000 0 FUNC GLOBAL DEFAULT {where or 11} {name}')\n"
    )
    tool.chmod(0o700)
    return abi, root, str(tool)


def test_the_agent_is_checked_against_every_firmware_it_runs_on(tmp_path):
    abi, root, tool = _fake_firmware(tmp_path)
    abi.check_sysroot("agent", tool, root)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"drop": ("memcpy@GLIBC_2.4",)}, "lacks memcpy@GLIBC_2.4"),
        ({"lacks_runtime": "srtp_protect"}, "libsrtp.so.1 lacks srtp_protect"),
    ],
)
def test_a_firmware_without_a_symbol_the_agent_uses_fails_the_check(tmp_path, change, message):
    abi, root, tool = _fake_firmware(tmp_path, **change)
    with pytest.raises(ValueError, match=message):
        abi.check_sysroot("agent", tool, root)


def test_a_firmware_without_a_library_the_agent_needs_fails_the_check(tmp_path):
    abi, root, tool = _fake_firmware(tmp_path)
    (root / "usr/lib/libspeex.so.1").unlink()
    with pytest.raises(ValueError, match="lacks libspeex.so.1"):
        abi.check_sysroot("agent", tool, root)


def test_the_checked_runtime_functions_are_the_ones_the_agent_loads():
    import re

    sources = "".join(path.read_text(encoding="utf-8") for path in (ROOT / "native_agent/src").glob("*.c"))
    loaded = set(re.findall(r'"((?:srtp|speex)_[a-z_]+)"', sources))
    # The curl names come from a macro; its own definition is no function.
    loaded |= {f"curl_{name}" for name in re.findall(r"\bLOAD\(([a-z_]+)\)", sources) if name != "name"}
    checked = {name for functions in _abi_module().RUNTIME_SYMBOLS.values() for name in functions}
    assert checked == loaded


def test_the_abi_check_covers_the_newer_firmware_when_it_is_there():
    makefile = (ROOT / "native_agent/Makefile").read_text(encoding="utf-8")
    assert "C300X_ABI_SYSROOTS ?= $(wildcard ../../c300x-fwpatch/work/rootfs-3.0.6 ../../c300x-fwpatch/work/rootfs-c100x-1.5.8)" in makefile
    assert "$(foreach root,$(C300X_DEVICE_SYSROOT) $(C300X_ABI_SYSROOTS),--sysroot $(root))" in makefile
