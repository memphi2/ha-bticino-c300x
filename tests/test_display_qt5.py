"""--display-qt5 reads the display files out of the Qt 5 display program and packs the patched ones."""

from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"
SOURCES = ("test/display_qt5_test.c", "src/display_qt5.c", "src/device_patch_io.c", "src/sha256.c", "src/string_util.c")
FLAGS = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L"]
VENDOR = {
    "MainApp.qml": b"import QtQuick 2.7\nItem { id: mainApp }\n",
    "HomePage.qml": b"import QtQuick 2.7\nItem {\n    Connections {\n        function onX () {\n        }\n    }\n}\n",
    "Components/Settings/GeneralsChoice.qml": b"import QtQuick 2.7\nColumn {}\n",
    "images/plain.svg": b"<svg/>",
}


def qt_hash(name: str) -> int:
    value = 0
    for char in name:
        value = (value << 4) + ord(char)
        value ^= (value & 0xF0000000) >> 23
        value &= 0x0FFFFFFF
    return value


def _vendor_tables(files: dict[str, bytes], *, flags: int = 1) -> tuple[bytes, bytes, bytes]:
    """Tree, names and data as Qt's rcc writes them into a program, compressed."""

    root: dict[str, object] = {}
    for rel, content in files.items():
        node = root
        parts = ["skins", "default", *rel.split("/")]
        for part in parts[:-1]:
            node = node.setdefault(part, {})  # type: ignore[assignment]
        node[parts[-1]] = content
    entries: list[tuple[str, object]] = [("", root)]
    tree, names, data = bytearray(), bytearray(), bytearray()
    at = 0
    while at < len(entries):
        name, value = entries[at]
        name_offset = 0
        if at:
            name_offset = len(names)
            names += struct.pack(">HI", len(name), qt_hash(name)) + name.encode("utf-16-be")
        if isinstance(value, dict):
            children = sorted(value.items(), key=lambda item: qt_hash(item[0]))
            tree += struct.pack(">IHII", name_offset, 2, len(children), len(entries)) + bytes(8)
            entries.extend(children)
        else:
            assert isinstance(value, bytes)
            blob = struct.pack(">I", len(value)) + zlib.compress(value) if flags & 1 else value
            tree += struct.pack(">IHHHI", name_offset, flags, 0, 1, len(data)) + bytes(8)
            data += struct.pack(">I", len(blob)) + blob
        at += 1
    return bytes(tree), bytes(names), bytes(data)


def _program(files: dict[str, bytes], *, flags: int = 1) -> tuple[bytes, tuple[int, int, int]]:
    tree, names, data = _vendor_tables(files, flags=flags)
    head = b"\x7fELF" + bytes(300)
    offsets = (len(head), len(head) + len(tree) + 7, len(head) + len(tree) + 7 + len(names) + 5)
    body = head + tree + bytes(7) + names + bytes(5) + data + bytes(64)
    return body, offsets


def overlay_blob(out: Path) -> Path:
    """The host build of qrc_overlay.so as the object the agent carries it in."""

    library, blob = out / "c300x-qrc-overlay.so", out / "qrc_overlay_blob.o"
    subprocess.run(["gcc", *FLAGS, "-fPIC", "-shared", str(NATIVE / "qt5/qrc_overlay.c"), "-o", str(library), "-ldl"],
                   check=True, capture_output=True, text=True)
    subprocess.run(["gcc", f'-DQRC_OVERLAY_SO="{library}"', "-c", str(NATIVE / "qt5/qrc_overlay_blob.S"),
                    "-o", str(blob)], check=True, capture_output=True, text=True)
    return blob


@pytest.fixture(scope="module")
def vendor_program(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("btclass") / "BtClass"
    path.write_bytes(_program(VENDOR)[0])
    return path


@pytest.fixture(scope="module")
def cli(tmp_path_factory: pytest.TempPathFactory, vendor_program: Path) -> Path:
    body, (tree, names, data) = _program(VENDOR)
    layout = f'{{"{hashlib.sha256(body).hexdigest()}", {tree}u, {names}u, {data}u}}'
    out = tmp_path_factory.mktemp("cli")
    binary = out / "display-qt5"
    subprocess.run(
        ["gcc", *FLAGS, f"-DC300X_DISPLAY_QT5_TEST_LAYOUT={layout}", *(str(NATIVE / s) for s in SOURCES),
         str(overlay_blob(out)), "-o", str(binary), "-ldl"],
        check=True, capture_output=True, text=True,
    )
    return binary


def _run(cli: Path, *args: str | Path, program: Path | None = None) -> tuple[int, dict[str, object]]:
    env = {**os.environ}
    if program is not None:
        env["C300X_QT5_GUI_BINARY"] = str(program)
    result = subprocess.run([str(cli), *map(str, args)], capture_output=True, text=True, env=env, check=False)
    return result.returncode, json.loads(result.stdout)


def test_extracts_the_named_files_of_a_known_program(cli: Path, vendor_program: Path, tmp_path: Path) -> None:
    rels = ["MainApp.qml", "HomePage.qml", "Components/Settings/GeneralsChoice.qml"]
    assert _run(cli, "extract", tmp_path / "out", *rels, program=vendor_program) == (0, {"ok": True, "files": 3})
    for rel in rels:
        assert (tmp_path / "out" / rel).read_bytes() == VENDOR[rel]
    assert not (tmp_path / "out/images").exists()


def test_an_unknown_program_is_not_read(cli: Path, vendor_program: Path, tmp_path: Path) -> None:
    other = tmp_path / "BtClass"
    other.write_bytes(vendor_program.read_bytes() + b"\0")
    assert _run(cli, "extract", tmp_path / "out", "MainApp.qml", program=other) == (
        1, {"ok": False, "error": "display_program_unknown"},
    )
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    ("rel", "error"),
    [
        ("Missing.qml", "display_resource_missing"),
        ("Components", "display_resource_missing"),
        ("../MainApp.qml", "invalid_arguments"),
        ("/MainApp.qml", "invalid_arguments"),
        ("Components//Settings/GeneralsChoice.qml", "invalid_arguments"),
    ],
)
def test_extract_refuses_what_it_cannot_find(
    cli: Path, vendor_program: Path, tmp_path: Path, rel: str, error: str
) -> None:
    assert _run(cli, "extract", tmp_path / "out", rel, program=vendor_program) == (1, {"ok": False, "error": error})


def test_a_missing_program_is_reported(cli: Path, tmp_path: Path) -> None:
    assert _run(cli, "extract", tmp_path / "out", "MainApp.qml", program=tmp_path / "none") == (
        1, {"ok": False, "error": "display_program_unreadable"},
    )


def _qt_find(rcc: bytes, path: str) -> bytes | None:
    """Look a file up the way QResourceRoot::findNode does: binary search by hash."""

    magic, version, tree, data, names = struct.unpack(">4sIIII", rcc[:20])
    assert (magic, version) == (b"qres", 2)

    def entry(index: int) -> bytes:
        return rcc[tree + 22 * index:tree + 22 * index + 22]

    def name_at(index: int) -> tuple[int, str]:
        offset = names + struct.unpack(">I", entry(index)[:4])[0]
        length, value = struct.unpack(">HI", rcc[offset:offset + 6])
        return value, rcc[offset + 6:offset + 6 + 2 * length].decode("utf-16-be")

    node = 0
    for segment in path.split("/"):
        flags = struct.unpack(">H", entry(node)[4:6])[0]
        if not flags & 2:
            return None
        count, child = struct.unpack(">II", entry(node)[6:14])
        wanted = qt_hash(segment)
        left, right = 0, count - 1
        sub = (left + right + 1) // 2
        while right != left:
            value = name_at(child + sub)[0]
            if value == wanted:
                break
            if wanted < value:
                right = sub - 1
            else:
                left = sub
            sub = (left + right + 1) // 2
        sub += child
        while sub > child and name_at(sub - 1)[0] == wanted:
            sub -= 1
        found = None
        while sub < child + count and name_at(sub)[0] == wanted:
            if name_at(sub)[1] == segment:
                found = sub
                break
            sub += 1
        if found is None:
            return None
        node = found
    flags, _country, language, offset = struct.unpack(">HHHI", entry(node)[4:14])
    if flags & 2:
        return None
    assert (flags, language) == (0, 1)
    size = struct.unpack(">I", rcc[data + offset:data + offset + 4])[0]
    return rcc[data + offset + 4:data + offset + 4 + size]


def _write_tree(root: Path, files: dict[str, bytes]) -> None:
    for rel, content in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(content)


def test_pack_writes_a_file_qt_finds_every_page_in(cli: Path, tmp_path: Path) -> None:
    files = {f"C300X{index}.qml": f"import QtQuick 2.7\nItem {{ property int n: {index} }}\n".encode()
             for index in range(40)}
    files |= {"js/c300x_ha.js": b".pragma library\n", "Components/Settings/GeneralsChoice.qml": b"Column {}\n",
              "MainApp.qml": b"Item {}\n", "HomePage.qml": b"Item { }\n"}
    _write_tree(tmp_path / "gui", files)
    out = tmp_path / "display-qt5.rcc"
    assert _run(cli, "pack", tmp_path / "gui", out, *files) == (0, {"ok": True, "files": len(files)})
    rcc = out.read_bytes()
    for rel, content in files.items():
        assert _qt_find(rcc, f"skins/default/{rel}") == content, rel
    assert _qt_find(rcc, "skins/default/Other.qml") is None
    assert _qt_find(rcc, "skins/default/js") is None
    assert out.stat().st_mode & 0o777 == 0o644
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize(
    "case",
    ["missing", "symlink", "directory", "duplicate", "file_and_folder", "escape"],
)
def test_pack_refuses_files_it_should_not_pack(cli: Path, tmp_path: Path, case: str) -> None:
    gui = tmp_path / "gui"
    _write_tree(gui, {"MainApp.qml": b"Item {}\n", "js/a.js": b"1\n"})
    (tmp_path / "secret").write_text("x")
    (gui / "link.qml").symlink_to(tmp_path / "secret")
    rels = {
        "missing": ["MainApp.qml", "Gone.qml"],
        "symlink": ["link.qml"],
        "directory": ["js"],
        "duplicate": ["MainApp.qml", "MainApp.qml"],
        "file_and_folder": ["js", "js/a.js"],
        "escape": ["../secret"],
    }[case]
    out = tmp_path / "display-qt5.rcc"
    code, result = _run(cli, "pack", gui, out, *rels)
    assert code == 1
    assert result["ok"] is False
    assert not out.exists()


def test_a_compression_qt_has_but_the_device_lacks_is_refused(tmp_path: Path) -> None:
    body, (tree, names, data) = _program({"MainApp.qml": b"Item {}\n"}, flags=4)
    program = tmp_path / "BtClass"
    program.write_bytes(body)
    layout = f'{{"{hashlib.sha256(body).hexdigest()}", {tree}u, {names}u, {data}u}}'
    binary = tmp_path / "display-qt5"
    subprocess.run(
        ["gcc", *FLAGS, f"-DC300X_DISPLAY_QT5_TEST_LAYOUT={layout}", *(str(NATIVE / s) for s in SOURCES),
         "-o", str(binary), "-ldl"],
        check=True, capture_output=True, text=True,
    )
    assert _run(binary, "extract", tmp_path / "out", "MainApp.qml", program=program) == (
        1, {"ok": False, "error": "display_resource_compression_unsupported"},
    )


def test_overlay_writes_the_library_it_carries(cli: Path, tmp_path: Path) -> None:
    target = tmp_path / "agent/c300x-qrc-overlay.so"
    assert _run(cli, "overlay", target) == (0, {"ok": True, "files": 1})
    library = (cli.parent / "c300x-qrc-overlay.so").read_bytes()
    assert target.read_bytes() == library
    assert target.stat().st_mode & 0o777 == 0o644
    target.write_bytes(b"old")
    assert _run(cli, "overlay", target)[0] == 0
    assert target.read_bytes() == library


def test_a_build_without_the_library_says_so(tmp_path: Path) -> None:
    binary = tmp_path / "display-qt5"
    subprocess.run(["gcc", *FLAGS, *(str(NATIVE / s) for s in SOURCES), "-o", str(binary), "-ldl"],
                   check=True, capture_output=True, text=True)
    assert _run(binary, "overlay", tmp_path / "lib.so") == (1, {"ok": False, "error": "overlay_missing"})
    assert not (tmp_path / "lib.so").exists()


def test_the_3_0_6_program_is_the_one_pinned() -> None:
    source = (NATIVE / "src/display_qt5.c").read_text()
    assert '{"6e114e7d9ce17d4c587a13082720bb6b5e66d5683bfd12047321b9694f2971f8", 0x35c6cu, 0x3672cu, 0x3791cu}' in source
