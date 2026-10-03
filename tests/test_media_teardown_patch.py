from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native_agent"

STOCK_ENV = "C300X_TEARDOWN_TEST_STOCK"


def _build(tmp_path: Path) -> Path:
    sources = sorted(
        str(path)
        for path in (NATIVE / "src").glob("*.c")
        if path.name not in {"http.c", "main.c"}
    )
    binary = tmp_path / "teardown-patch-test"
    subprocess.run(
        [
            "gcc",
            "-std=c11",
            "-O2",
            "-D_DEFAULT_SOURCE",
            "-D_POSIX_C_SOURCE=200809L",
            "-ffunction-sections",
            "-fdata-sections",
            "-Wl,--gc-sections",
            str(NATIVE / "test" / "teardown_patch_test.c"),
            *sources,
            "-pthread",
            "-ldl",
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return binary


def _run(binary: Path, tmp_path: Path, stock: str | None) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["TMPDIR"] = str(tmp_path)
    if stock:
        environment[STOCK_ENV] = stock
    else:
        environment.pop(STOCK_ENV, None)
    return subprocess.run(
        [str(binary)], capture_output=True, text=True, env=environment
    )


def test_teardown_patch_status_refusal_idempotence_and_restore(tmp_path: Path) -> None:
    binary = _build(tmp_path)

    result = _run(binary, tmp_path, stock=None)

    assert result.returncode == 0, result.stderr
    assert "media teardown patch test passed" in result.stdout
    assert "skipped stock roundtrip" in result.stdout


def test_teardown_patch_roundtrip_against_stock_binary(tmp_path: Path) -> None:
    stock = os.environ.get(STOCK_ENV)
    if not stock or not Path(stock).is_file():
        pytest.skip(f"{STOCK_ENV} does not point at a stock device binary")
    binary = _build(tmp_path)

    result = _run(binary, tmp_path, stock=stock)

    assert result.returncode == 0, result.stderr
    assert "skipped stock roundtrip" not in result.stdout


def _load_builder():
    import importlib.util

    path = ROOT / "scripts" / "media_teardown_builder.py"
    spec = importlib.util.spec_from_file_location("media_teardown_builder", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    import sys as _sys

    _sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_builder_applies_expected_range_writes(tmp_path: Path) -> None:
    builder = _load_builder()
    data = bytearray(b"0123456789abcdef")
    expected = bytearray(data)
    expected[4:6] = b"XY"
    builder.PATCHES = (
        builder.Patch(
            name="synthetic",
            offset=4,
            range_len=8,
            expected_range_sha256=builder.sha256(bytes(data[4:12])),
            patched_range_sha256=builder.sha256(bytes(expected[4:12])),
            writes=(builder.Write(0, b"XY"),),
        ),
    )
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_bytes(bytes(data))
    source.chmod(0o754)

    assert builder.patch_media(source, target) == builder.sha256(bytes(expected))
    assert target.read_bytes() == bytes(expected)
    assert target.stat().st_mode & 0o777 == 0o754
    assert source.read_bytes() == bytes(data), "source must never be modified"


def test_builder_rejects_unexpected_range_hash(tmp_path: Path) -> None:
    builder = _load_builder()
    data = bytearray(b"0123456789abcdef")
    builder.PATCHES = (
        builder.Patch(
            name="synthetic",
            offset=0,
            range_len=4,
            expected_range_sha256=builder.sha256(b"ZZZZ"),
            patched_range_sha256=builder.sha256(b"ZZZZ"),
            writes=(builder.Write(0, b"AB"),),
        ),
    )
    source = tmp_path / "source"
    source.write_bytes(bytes(data))

    with pytest.raises(builder.PatchError, match="precondition failed"):
        builder.patch_media(source, tmp_path / "target")


def test_builder_and_agent_tables_match() -> None:
    builder = _load_builder()
    agent = (NATIVE / "src" / "media_teardown_patch.c").read_text(encoding="utf-8")

    assert len(builder.PATCHES) == 2
    for patch in builder.PATCHES:
        assert f'"{patch.name}"' in agent
        assert f"0x{patch.offset:x}" in agent
        assert patch.expected_range_sha256 in agent
        assert patch.patched_range_sha256 in agent
        assert patch.range_len == 4
        for write in patch.writes:
            as_c = ", ".join(f"0x{byte:02x}" for byte in write.data)
            assert as_c in agent, as_c
    assert builder.PATCHES[0].offset != builder.PATCHES[1].offset
    assert "0xa8, 0x61" not in agent
    assert "a8610000" not in agent


def test_builder_roundtrip_against_stock_binary(tmp_path: Path) -> None:
    stock = os.environ.get(STOCK_ENV)
    if not stock or not Path(stock).is_file():
        pytest.skip(f"{STOCK_ENV} does not point at a stock device binary")
    builder = _load_builder()
    source = Path(stock)
    target = tmp_path / "patched"

    builder.patch_media(source, target)

    original = source.read_bytes()
    patched = target.read_bytes()
    assert len(original) == len(patched)
    differing = [i for i in range(len(original)) if original[i] != patched[i]]
    assert len(differing) == 6, differing
    assert differing == [0x5EE0, 0x5EE1, 0x5EE2, 0xDD0C, 0xDD0D, 0xDD0E]
