#!/usr/bin/env python3
"""Patch BTicino C300X bt_answering_machine for in-house-only forwarding.

This tool is intentionally narrow: it only accepts the known 1.7.19 stock
bt_answering_machine binary and writes a patched copy to an explicit output path.
It never modifies the input file in place.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path


STOCK_SHA256 = "605a808f1ed0c826c06bbf1eb4131b9198007a7ab822e7541a6666e79816c810"
PATCHED_SHA256 = "8f6e45d4c5f94bab74fa1dc8bd9ce06ca76a3a499dc664a9c6dbd934943e1c13"


@dataclass(frozen=True)
class Patch:
    """One exact binary patch."""

    name: str
    offset: int
    original: bytes
    patched: bytes


PATCHES: tuple[Patch, ...] = (
    Patch(
        name="allow Dimension 37 receive values 0, 1 and 2",
        offset=0x282F8,
        original=bytes.fromhex("0230d0e30080a0e12f00001a"),
        patched=bytes.fromhex("020050e30080a0e12f00008a"),
    ),
    Patch(
        name="allow DisableRemote values 0, 1 and 2",
        offset=0xDA04,
        original=bytes.fromhex("0250d0e30150a0130100000a0500a0e1"),
        patched=bytes.fromhex("020050e30050a0930100009a0100a0e3"),
    ),
    Patch(
        name="suppress in-house-disabled log call",
        offset=0x35FE0,
        original=bytes.fromhex("3aff2fe1"),
        patched=bytes.fromhex("0000a0e1"),
    ),
    Patch(
        name="keep DisableRemote instead of forcing 0",
        offset=0x35FF4,
        original=bytes.fromhex("b4b384e5"),
        patched=bytes.fromhex("0000a0e1"),
    ),
    Patch(
        name="preserve route mode instead of writing DisableRemote=0",
        offset=0x36000,
        original=bytes.fromhex("0620a0e10410a0e10b00a0e17b5effeb"),
        patched=bytes.fromhex("0000a0e10000a0e10000a0e10000a0e1"),
    ),
    Patch(
        name="route DisableRemote=1 to route_int.conf",
        offset=0x363D8,
        original=bytes.fromhex("6c620000"),
        patched=bytes.fromhex("8c780000"),
    ),
    Patch(
        name="route runtime in-house mode through route_int.conf",
        offset=0x28420,
        original=bytes.fromhex(
            "7c219fe57c319fe5029096e7036096e7043099e5002096e5"
            "010013e3c30082e000a099e5c33092175c219fe50aa09317"
            "02208fe00210a0e33aff2fe1"
        ),
        patched=bytes.fromhex(
            "010058e30500001a70219fe578119fe502208fe001108fe0"
            "0500a0e16cc3ffeb5c219fe55c319fe5029096e7036096e7"
            "0000a0e10000a0e10000a0e1"
        ),
    ),
    Patch(
        name="runtime route trampoline target route_int.conf",
        offset=0x285A0,
        original=bytes.fromhex("301e0100"),
        patched=bytes.fromhex("48540100"),
    ),
    Patch(
        name="runtime route trampoline link route.conf",
        offset=0x285AC,
        original=bytes.fromhex("643e0100"),
        patched=bytes.fromhex("483e0100"),
    ),
)


class PatchError(Exception):
    """Raised when the binary cannot be patched safely."""


def sha256(data: bytes) -> str:
    """Return the SHA-256 hex digest for *data*."""

    return hashlib.sha256(data).hexdigest()


def patch_binary(source: Path, target: Path) -> str:
    """Patch *source* and write a new binary to *target*."""

    data = bytearray(source.read_bytes())
    digest = sha256(data)
    if digest != STOCK_SHA256:
        raise PatchError(
            f"Unsupported bt_answering_machine SHA-256: {digest}; "
            f"expected {STOCK_SHA256}"
        )

    for patch in PATCHES:
        end = patch.offset + len(patch.original)
        current = bytes(data[patch.offset:end])
        if current != patch.original:
            raise PatchError(
                f"Patch precondition failed for {patch.name} at 0x{patch.offset:x}: "
                f"found {current.hex()}, expected {patch.original.hex()}"
            )
        data[patch.offset:end] = patch.patched

    patched_digest = sha256(data)
    if patched_digest != PATCHED_SHA256:
        raise PatchError(
            f"Unexpected patched SHA-256: {patched_digest}; expected {PATCHED_SHA256}"
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    target.chmod(source.stat().st_mode & 0o7777)
    return patched_digest


def main() -> int:
    """Run the command-line patcher."""

    parser = argparse.ArgumentParser(
        description="Create a patched C300X bt_answering_machine copy."
    )
    parser.add_argument("source", type=Path, help="Stock bt_answering_machine")
    parser.add_argument("target", type=Path, help="Output path for patched copy")
    args = parser.parse_args()

    try:
        digest = patch_binary(args.source, args.target)
    except OSError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    except PatchError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2

    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
