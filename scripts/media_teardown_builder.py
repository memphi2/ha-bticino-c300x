from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

STOCK_RANGE_SHA256 = "ebcdb6c80e93af3a75a7ea485ab65763ab7f2bf7a6e4ed1623640f0d6a2b050f"
PATCHED_RANGE_SHA256 = "347e4e96ea7158b26c991f7d6b9cd4ead625dc82ab2296c9dc277cbcdb164f8f"
STOCK_SHA256 = "97b61ad80e67c1b3ea494956568645b93c7fe3ef359f77af9c7e2ad6dff1bf9e"
PATCHED_SHA256 = "45f776fee4bb4b5fd020f19e961c48754fe3513ea6c70266a817a03639fb014a"
TARGET_SIZE = 186932

PATCHED_DRAIN = b"\x40\x0d\x03"


@dataclass(frozen=True)
class Write:
    offset: int
    data: bytes


@dataclass(frozen=True)
class Patch:
    name: str
    offset: int
    range_len: int
    expected_range_sha256: str
    patched_range_sha256: str
    writes: tuple[Write, ...]


PATCHES: tuple[Patch, ...] = (
    Patch(
        name="teardown_drain_0",
        offset=0x5EE0,
        range_len=4,
        expected_range_sha256=STOCK_RANGE_SHA256,
        patched_range_sha256=PATCHED_RANGE_SHA256,
        writes=(Write(0, PATCHED_DRAIN),),
    ),
    Patch(
        name="teardown_drain_1",
        offset=0xDD0C,
        range_len=4,
        expected_range_sha256=STOCK_RANGE_SHA256,
        patched_range_sha256=PATCHED_RANGE_SHA256,
        writes=(Write(0, PATCHED_DRAIN),),
    ),
)


class PatchError(Exception):
    pass


def sha256(data: bytes) -> str:

    return hashlib.sha256(data).hexdigest()


def _verify_range(data: bytes, patch: Patch, expected_sha256: str) -> bool:
    end = patch.offset + patch.range_len
    return end <= len(data) and sha256(data[patch.offset : end]) == expected_sha256


def patch_media(source: Path, target: Path) -> str:
    if source.resolve() == target.resolve() or (
        target.exists() and source.samefile(target)
    ):
        raise PatchError("Source and target must be different files")
    data = bytearray(source.read_bytes())
    original = bytes(data)
    if len(data) != TARGET_SIZE or sha256(data) != STOCK_SHA256:
        raise PatchError("Patch precondition failed: unsupported target identity")

    for patch in PATCHES:
        if not _verify_range(data, patch, patch.expected_range_sha256):
            raise PatchError(
                f"Patch precondition failed for {patch.name} at 0x{patch.offset:x}: "
                "unexpected precheck hash"
            )
        for write in patch.writes:
            end = patch.offset + write.offset + len(write.data)
            if write.offset < 0 or end > patch.offset + patch.range_len:
                raise PatchError(f"Write outside range for {patch.name}")
            data[patch.offset + write.offset : end] = write.data
        if not _verify_range(data, patch, patch.patched_range_sha256):
            raise PatchError(f"Patched range hash mismatch for {patch.name}")

    if len(data) != len(original):
        raise PatchError("Patch changed the file size")
    changed = sum(1 for index in range(len(original)) if original[index] != data[index])
    expected_changed = sum(len(write.data) for patch in PATCHES for write in patch.writes)
    if changed > expected_changed:
        raise PatchError(f"Patch changed {changed} bytes, expected at most {expected_changed}")
    if sha256(data) != PATCHED_SHA256:
        raise PatchError("Patched file identity mismatch")

    target.write_bytes(bytes(data))
    shutil.copymode(source, target)
    return sha256(bytes(data))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a patched C300X media daemon copy with a longer teardown drain."
    )
    parser.add_argument("source", type=Path, help="Stock binary to read (never modified)")
    parser.add_argument("target", type=Path, help="Path for the patched copy")
    arguments = parser.parse_args()

    if not arguments.source.is_file():
        sys.stderr.write(f"error: {arguments.source} is not a file\n")
        return 2
    try:
        digest = patch_media(arguments.source, arguments.target)
    except PatchError as error:
        sys.stderr.write(f"error: {error}\n")
        return 1
    sys.stdout.write(f"patched {arguments.target} sha256={digest}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
