"""Tests for the local C300X in-house binary patch helper."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCHER_PATH = ROOT / "scripts" / "patch_bticino_inhouse_binary.py"


def _load_patcher():
    spec = importlib.util.spec_from_file_location("patch_bticino_inhouse_binary", PATCHER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_patch_binary_applies_expected_bytes(tmp_path: Path) -> None:
    patcher = _load_patcher()
    size = max(patch.offset + len(patch.original) for patch in patcher.PATCHES)
    data = bytearray(b"\x00" * size)
    for patch in patcher.PATCHES:
        data[patch.offset : patch.offset + len(patch.original)] = patch.original

    source = tmp_path / "bt_answering_machine"
    target = tmp_path / "bt_answering_machine.inhouse"
    source.write_bytes(data)
    source.chmod(0o754)
    expected = bytearray(data)
    for patch in patcher.PATCHES:
        expected[patch.offset : patch.offset + len(patch.patched)] = patch.patched

    patcher.STOCK_SHA256 = patcher.sha256(data)
    patcher.PATCHED_SHA256 = patcher.sha256(expected)

    assert patcher.patch_binary(source, target) == patcher.sha256(expected)
    assert target.read_bytes() == expected
    assert target.stat().st_mode & 0o777 == 0o754


def test_patch_binary_rejects_unexpected_original_bytes(tmp_path: Path) -> None:
    patcher = _load_patcher()
    size = max(patch.offset + len(patch.original) for patch in patcher.PATCHES)
    data = bytearray(b"\x00" * size)
    for patch in patcher.PATCHES:
        data[patch.offset : patch.offset + len(patch.original)] = patch.original
    data[patcher.PATCHES[0].offset] ^= 0xFF

    source = tmp_path / "bt_answering_machine"
    target = tmp_path / "bt_answering_machine.inhouse"
    source.write_bytes(data)
    patcher.STOCK_SHA256 = patcher.sha256(data)

    try:
        patcher.patch_binary(source, target)
    except patcher.PatchError as err:
        assert "Patch precondition failed" in str(err)
    else:
        raise AssertionError("patch_binary accepted unexpected original bytes")


def test_python_and_agent_patch_tables_match() -> None:
    patcher = _load_patcher()
    source = (ROOT / "native_agent" / "src" / "inhouse_patch.c").read_text(
        encoding="utf-8"
    )

    for index, patch in enumerate(patcher.PATCHES):
        assert f"0x{patch.offset:x}" in source
        assert _c_array_hex(source, f"PATCH_{index}_ORIG") == patch.original.hex()
        assert _c_array_hex(source, f"PATCH_{index}_NEW") == patch.patched.hex()

    assert patcher.STOCK_SHA256 in source
    assert patcher.PATCHED_SHA256 in source
    assert "original_mode = (mode_t)(original_stat.st_mode & 07777);" in source
    assert "backup_mode = (mode_t)(backup_stat.st_mode & 07777);" in source
    assert "remount_root_ro_or_error(error, error_len)" in source
    assert 'set_error(error, error_len, "remount_ro_failed");' in source


def _c_array_hex(source: str, name: str) -> str:
    match = re.search(
        rf"static const unsigned char {name}\[\] = \{{(?P<body>.*?)\}};",
        source,
        re.DOTALL,
    )
    assert match is not None, name
    return "".join(re.findall(r"0x([0-9a-f]{2})", match.group("body")))
