#!/usr/bin/env python3
"""Write every Qt resource file of a firmware 3.0.x BtClass program into a folder.

For local analysis and tests/test_device_qt5_runtime.py only: the output is
firmware and must stay outside the repository. It finds the resource tables
itself (names table, tree, data start), so it also reads builds whose offsets
are not known yet.

    scripts/extract_btclass_resources.py BtClass OUT
    -> OUT/skins/default/... (C300X_QT5_SKIN=OUT/skins/default)
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

ENTRY = 22


def qt_hash(text: str) -> int:
    value = 0
    for char in text:
        value = ((value << 4) + ord(char)) & 0xFFFFFFFF
        value ^= (value & 0xF0000000) >> 23
        value &= 0x0FFFFFFF
    return value


def name_at(data: bytes, offset: int) -> str | None:
    if offset + 6 > len(data):
        return None
    length = struct.unpack(">H", data[offset:offset + 2])[0]
    if not 0 < length < 256:
        return None
    try:
        text = data[offset + 6:offset + 6 + 2 * length].decode("utf-16-be")
    except UnicodeDecodeError:
        return None
    return text if struct.unpack(">I", data[offset + 2:offset + 6])[0] == qt_hash(text) else None


def names_tables(data: bytes) -> list[dict[int, str]]:
    tables, offset = [], 0
    while offset < len(data) - 8:
        text = name_at(data, offset)
        if text is None:
            offset += 1
            continue
        start, names = offset, {}
        while text is not None:
            names[offset - start] = text
            offset += 6 + 2 * len(text)
            text = name_at(data, offset)
        if len(names) >= 3:
            tables.append(names)
    return tables


def tree_files(data: bytes, tree: int, names: dict[int, str]) -> list[tuple[str, int, int]]:
    files: list[tuple[str, int, int]] = []

    def walk(index: int, path: str, depth: int) -> None:
        entry = data[tree + index * ENTRY:tree + (index + 1) * ENTRY]
        if depth > 32 or len(entry) < ENTRY:
            raise ValueError
        name_offset, flags = struct.unpack(">IH", entry[:6])
        name = names.get(name_offset)
        if index and name is None:
            raise ValueError
        child = f"{path}/{name}" if index else ""
        if flags & 2:
            count, first = struct.unpack(">II", entry[6:14])
            if count > 4096:
                raise ValueError
            for item in range(first, first + count):
                walk(item, child, depth + 1)
        else:
            files.append((child, flags, struct.unpack(">I", entry[10:14])[0]))

    walk(0, "", 0)
    return files


def data_start(data: bytes, files: list[tuple[str, int, int]]) -> int | None:
    offsets = sorted(offset for _, _, offset in files)
    found = []
    for base in range(0, len(data) - offsets[-1] - 4):
        ok = True
        for here, after in zip(offsets, [*offsets[1:], None], strict=True):
            size = struct.unpack(">I", data[base + here:base + here + 4])[0]
            if (after is not None and here + 4 + size != after) or base + here + 4 + size > len(data):
                ok = False
                break
        if ok:
            found.append(base)
            if len(found) > 1:
                return None
    return found[0] if found else None


def extract(data: bytes, out: Path) -> int:
    written = 0
    for names in names_tables(data):
        for tree in range(0, len(data) - 2 * ENTRY, 2):
            if data[tree:tree + 6] != b"\0\0\0\0\0\x02":
                continue
            count, first = struct.unpack(">II", data[tree + 6:tree + 14])
            if first != 1 or not 0 < count < 4096:
                continue
            try:
                files = tree_files(data, tree, names)
            except (ValueError, struct.error):
                continue
            base = data_start(data, files) if files else None
            if base is None:
                continue
            for path, flags, offset in files:
                start = base + offset
                size = struct.unpack(">I", data[start:start + 4])[0]
                body = data[start + 4:start + 4 + size]
                if flags & 1:
                    body = zlib.decompress(body[4:])
                target = out / path.lstrip("/")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)
                written += 1
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("program", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    count = extract(args.program.read_bytes(), args.out)
    sys.stdout.write(f"{count} files\n")
    return 0 if count else 1


if __name__ == "__main__":
    sys.exit(main())
