"""qrc_overlay.so registers the agent's resource file in the Qt 5 display program, and only there."""

from __future__ import annotations

import json
import os
import struct
import subprocess
from pathlib import Path

import pytest

from tests.test_display_qt5 import _vendor_tables

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"
FLAGS = ["-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic"]


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, Path]:
    out = tmp_path_factory.mktemp("qrc-overlay")
    library, program, helper = out / "qrc_overlay.so", out / "display", out / "helper"
    subprocess.run(["gcc", *FLAGS, "-fPIC", "-shared", str(NATIVE / "qt5/qrc_overlay.c"), "-o", str(library), "-ldl"],
                   check=True, capture_output=True, text=True)
    # -rdynamic lets the library find the stand-in by name, as it finds Qt's.
    subprocess.run(["gcc", *FLAGS, "-rdynamic", str(NATIVE / "test/qrc_overlay_test.c"), "-o", str(program)],
                   check=True, capture_output=True, text=True)
    helper.write_text("#!/bin/sh\nprintf '%s\\n' \"${LD_PRELOAD:-}\"\n")
    helper.chmod(0o755)
    return library, program, helper


def _rcc(path: Path, *, magic: bytes = b"qres", version: int = 2, size: int | None = None,
         tree: int = 20, names: int | None = None, data: int | None = None) -> Path:
    nodes, strings, payload = _vendor_tables({"MainApp.qml": b"probe"}, flags=0)
    body = magic + struct.pack(">IIII", version, tree, data if data is not None else 20 + len(nodes) + len(strings),
                               names if names is not None else 20 + len(nodes)) + nodes + strings + payload
    path.write_bytes(body if size is None else body[:size])
    return path


def _run(built: tuple[Path, Path, Path], rcc: Path | None, **env: str) -> dict[str, object]:
    library, program, _ = built
    environment = {**os.environ, "LD_PRELOAD": str(library), **env}
    environment["C300X_QRC_OVERLAY"] = str(rcc) if rcc else "/nonexistent/display-qt5.rcc"
    result = subprocess.run([str(program)], check=True, capture_output=True, text=True, env=environment)
    return json.loads(result.stdout)


def test_registers_the_three_tables_of_a_resource_file(built: tuple[Path, Path, Path], tmp_path: Path) -> None:
    assert _run(built, _rcc(tmp_path / "ok.rcc")) == {
        "calls": 1, "version": 2, "marks": [2, 5, 5], "preload_kept": False,
    }


@pytest.mark.parametrize(
    "case",
    [
        {"magic": b"qrex"},
        {"version": 4},
        {"version": 0},
        {"tree": 64},
        {"names": 200},
        {"data": 8},
        {"size": 19},
    ],
)
def test_a_damaged_file_is_not_registered(
    built: tuple[Path, Path, Path], tmp_path: Path, case: dict[str, object]
) -> None:
    result = _run(built, _rcc(tmp_path / "bad.rcc", **case))  # type: ignore[arg-type]
    assert result["calls"] == 0
    assert rcc_failed(tmp_path / "bad.rcc").exists()


def rcc_failed(path: Path) -> Path:
    return path.with_name(path.name + ".failed")


@pytest.mark.parametrize("offset,value,width", [
    (20 + 4, 0, 2), (20 + 6, 0xffffffff, 4), (20 + 10, 0, 4),
    (20 + 22, 0xffffffff, 4), (20 + 22 + 4, 3, 2),
    (20 + 3 * 22 + 10, 0xffffffff, 4), (108, 0xffff, 2),
    (110, 0xffffffff, 4),
])
def test_internal_tables_are_checked_before_calling_qt(
    built: tuple[Path, Path, Path], tmp_path: Path, offset: int, value: int, width: int,
) -> None:
    path = _rcc(tmp_path / "internal.rcc")
    blob = bytearray(path.read_bytes())
    struct.pack_into(">I" if width == 4 else ">H", blob, offset, value)
    path.write_bytes(blob)
    assert _run(built, path)["calls"] == 0
    assert rcc_failed(path).exists()


def test_symlink_is_not_registered(built: tuple[Path, Path, Path], tmp_path: Path) -> None:
    target = _rcc(tmp_path / "target.rcc")
    link = tmp_path / "link.rcc"
    link.symlink_to(target)
    assert _run(built, link)["calls"] == 0


def test_every_truncation_is_rejected(built: tuple[Path, Path, Path], tmp_path: Path) -> None:
    path = _rcc(tmp_path / "truncated.rcc")
    original = path.read_bytes()
    for length in range(len(original)):
        path.write_bytes(original[:length])
        assert _run(built, path)["calls"] == 0, length


def test_no_file_registers_nothing(built: tuple[Path, Path, Path]) -> None:
    assert _run(built, None)["calls"] == 0


def test_a_refused_file_leaves_the_program_running(built: tuple[Path, Path, Path], tmp_path: Path) -> None:
    result = _run(built, _rcc(tmp_path / "ok.rcc"), QRC_TEST_ACCEPT="0")
    assert result["calls"] == 1


def test_a_helper_without_qt_passes_the_preload_on(built: tuple[Path, Path, Path], tmp_path: Path) -> None:
    library, _, helper = built
    environment = {**os.environ, "LD_PRELOAD": str(library), "C300X_QRC_OVERLAY": str(_rcc(tmp_path / "ok.rcc"))}
    result = subprocess.run([str(helper)], check=True, capture_output=True, text=True, env=environment)
    assert result.stdout.strip() == str(library)
