"""Tests for the local C300X device routing setup helper."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "scripts" / "device_routing_builder.py"


def _load_patcher():
    spec = importlib.util.spec_from_file_location(
        "device_routing_builder", BUILDER_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_patch_routing_applies_expected_range_writes(tmp_path: Path) -> None:
    patcher = _load_patcher()
    data = bytearray(b"0123456789abcdef")
    expected = bytearray(data)
    expected[4:6] = b"XY"
    expected[9:12] = b"abc"
    patcher.PATCHES = (
        patcher.Patch(
            name="test_range_0",
            offset=4,
            range_len=8,
            expected_range_sha256=patcher.sha256(data[4:12]),
            patched_range_sha256=patcher.sha256(expected[4:12]),
            writes=(
                patcher.Write(0, b"XY"),
                patcher.Write(5, b"abc"),
            ),
        ),
    )

    source = tmp_path / "bt_answering_machine"
    target = tmp_path / "bt_answering_machine.routing"
    source.write_bytes(data)
    source.chmod(0o754)
    patcher.STOCK_SHA256 = patcher.sha256(data)

    assert patcher.patch_routing(source, target) == patcher.sha256(expected)
    assert target.read_bytes() == expected
    assert target.stat().st_mode & 0o777 == 0o754


def test_patch_routing_rejects_unexpected_range_hash(tmp_path: Path) -> None:
    patcher = _load_patcher()
    data = bytearray(b"0123456789abcdef")
    patcher.PATCHES = (
        patcher.Patch(
            name="test_range_0",
            offset=4,
            range_len=4,
            expected_range_sha256=patcher.sha256(b"wxyz"),
            patched_range_sha256=patcher.sha256(b"XY89"),
            writes=(patcher.Write(0, b"XY"),),
        ),
    )

    source = tmp_path / "bt_answering_machine"
    target = tmp_path / "bt_answering_machine.routing"
    source.write_bytes(data)
    patcher.STOCK_SHA256 = patcher.sha256(data)

    try:
        patcher.patch_routing(source, target)
    except patcher.PatchError as err:
        assert "Patch precondition failed" in str(err)
        assert "unexpected precheck hash" in str(err)
    else:
        raise AssertionError("patch_routing accepted unexpected precheck range")


def test_python_and_agent_patch_tables_match() -> None:
    patcher = _load_patcher()
    source = (ROOT / "native_agent" / "src" / "device_routing.c").read_text(
        encoding="utf-8"
    )

    for index, patch in enumerate(patcher.PATCHES):
        assert f'"{patch.name}"' in source
        assert f"0x{patch.offset:x}" in source
        assert f", {patch.range_len}, " in source
        assert patch.expected_range_sha256 in source
        assert patch.patched_range_sha256 in source
        for write_index, write in enumerate(patch.writes):
            assert _c_array_hex(source, f"PATCH_{index}_WRITE_{write_index}") == (
                write.data.hex()
            )

    assert patcher.STOCK_SHA256 in source
    assert "original_mode = (mode_t)(original_stat.st_mode & 07777);" in source
    assert "backup_mode = (mode_t)(backup_stat.st_mode & 07777);" in source
    assert "remount_root_ro_or_error(error, error_len)" in source
    assert 'set_error(error, error_len, "remount_ro_failed");' in source


def test_patch_tables_are_hash_guarded_minimal_writes() -> None:
    patcher = _load_patcher()
    agent = (ROOT / "native_agent" / "src" / "device_routing.c").read_text(
        encoding="utf-8"
    )

    for patch in patcher.PATCHES:
        assert patch.range_len > 0
        assert len(patch.expected_range_sha256) == 64
        assert len(patch.patched_range_sha256) == 64
        assert patch.writes
        assert all(write.data for write in patch.writes)
    assert "expected_range_sha256" in agent
    assert "patched_range_sha256" in agent


def _c_array_hex(source: str, name: str) -> str:
    match = re.search(
        rf"static const unsigned char {name}\[\] = \{{(?P<body>.*?)\}};",
        source,
        re.DOTALL,
    )
    assert match is not None, name
    return "".join(re.findall(r"0x([0-9a-f]{2})", match.group("body")))
