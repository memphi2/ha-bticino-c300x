#!/usr/bin/env python3
"""Remove what the device does not need from the display's QML and JS files.

The files under device_qml/ are written to the device as they are packaged.
Comments and blank lines explain the code to a reader of this repository; on
the device they are only bytes to transfer, store and parse. Packaging drops
them, the sources keep them.

Three things are removed, because each is unambiguous without parsing:

* a line that holds nothing but a ``//`` comment
* a blank line
* whitespace at the start and end of every line

Indentation is by far the largest share, about a quarter of the bytes. QML and
JavaScript give it no meaning outside a string literal that continues over a
line break, and such a literal makes this strip refuse the file.

A ``//`` after code is left alone: telling it apart from the same characters
inside a string or a regular expression needs a tokenizer, and a wrong guess
would silently change what the display runs.

Control characters other than tab and the line endings are refused too. Python
ends a line at some that JavaScript keeps inside a string, such as form feed.
"""

from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEVICE_SOURCE_DIR = ROOT / "device_qml"
DEVICE_SOURCE_FILES = (
    "Alarm.qml",
    "HomeAssistant.qml",
    "C300XRingerControl.qml",
    "js/c300x_ha.js",
    "js/c300x_i18n.js",
    "js/c300x_memos.js",
)
STRIPPED_SUFFIXES = frozenset({".qml", ".js"})
_ALLOWED_CONTROL_CHARACTERS = frozenset("\t\n\r")
_LINE_SEPARATORS = frozenset("\u2028\u2029")


def _is_unsupported_character(character: str) -> bool:
    """Tell whether a device file may not contain ``character``.

    Control characters other than tab, line feed and carriage return are
    refused, as are the Unicode line separators, which a JavaScript engine
    counts as line ends.
    """

    if character in _LINE_SEPARATORS:
        return True
    return unicodedata.category(character) == "Cc" and character not in _ALLOWED_CONTROL_CHARACTERS


def _find_unsupported_character(text: str) -> int | None:
    for index, character in enumerate(text):
        if _is_unsupported_character(character):
            return index
    return None


class DeviceFileStripError(ValueError):
    """Raised when a source uses a construct this line-based strip cannot judge."""


def strip_device_source(text: str, *, name: str = "<source>") -> str:
    """Return ``text`` without comment-only lines, blank lines and line padding."""

    control = _find_unsupported_character(text)
    if control is not None:
        number = text.count("\n", 0, control) + 1
        raise DeviceFileStripError(
            f"{name}:{number}: control character U+{ord(text[control]):04X}"
            " is not supported in device files"
        )
    kept: list[str] = []
    for number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip()
        stripped = line.lstrip()
        if "/*" in line or "*/" in line:
            # A block comment can hide or expose whole lines. None exist today;
            # refuse instead of guessing if one is ever added.
            raise DeviceFileStripError(
                f"{name}:{number}: block comments are not supported in device files"
            )
        if line.endswith("\\"):
            # A continued string literal makes the next line string content,
            # which must not be judged as a comment or a blank line.
            raise DeviceFileStripError(
                f"{name}:{number}: line continuations are not supported in device files"
            )
        if not stripped or stripped.startswith("//"):
            continue
        kept.append(stripped)
    return "\n".join(kept) + "\n" if kept else ""


def strip_device_file(source: Path, target: Path) -> Path:
    """Write the stripped form of ``source`` to ``target``."""

    text = source.read_text(encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        strip_device_source(text, name=str(source)), encoding="utf-8", newline="\n"
    )
    return target


def strip_device_tree(target_dir: Path, source_dir: Path = DEVICE_SOURCE_DIR) -> list[Path]:
    """Write every display file, stripped, below ``target_dir``."""

    return [
        strip_device_file(source_dir / relative, target_dir / relative)
        for relative in DEVICE_SOURCE_FILES
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, help="Write the stripped display files here.")
    args = parser.parse_args()

    saved = 0
    try:
        for relative in DEVICE_SOURCE_FILES:
            source = DEVICE_SOURCE_DIR / relative
            text = source.read_text(encoding="utf-8")
            stripped = strip_device_source(text, name=str(source))
            before, after = len(text.encode()), len(stripped.encode())
            saved += before - after
            if args.out is not None:
                strip_device_file(source, args.out / relative)
            sys.stdout.write(f"{relative}: {before} -> {after} bytes\n")
    except DeviceFileStripError as err:
        sys.stderr.write(f"{err}\n")
        return 1
    sys.stdout.write(f"saved {saved} bytes\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
