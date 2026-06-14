#!/usr/bin/env python3
"""Create a local C300X bt_answering_machine compatibility patch copy.

This tool is intentionally narrow: it only accepts the known 1.7.19 stock
bt_answering_machine binary and writes a patched copy to an explicit output path.
It never modifies the input file in place and it verifies expected patch ranges by
hash instead of storing byte ranges in this repository.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

STOCK_SHA256 = "605a808f1ed0c826c06bbf1eb4131b9198007a7ab822e7541a6666e79816c810"


@dataclass(frozen=True)
class Write:
    """One byte write inside a verified patch range."""

    offset: int
    data: bytes


@dataclass(frozen=True)
class Patch:
    """One hash-verified binary patch range."""

    name: str
    offset: int
    range_len: int
    expected_range_sha256: str
    patched_range_sha256: str
    writes: tuple[Write, ...]


PATCHES: tuple[Patch, ...] = (
    Patch(
        name="patch_range_0",
        offset=0x282F8,
        range_len=12,
        expected_range_sha256="ed451a5b137b7b59ebfd3f4bb8ff6598a18abce58603b72eed97f50b8d6391b8",
        patched_range_sha256="59e44ff04f935f33e91e44d52771e6188e7a50c735c07b54f236087a818925d7",
        writes=(Write(1, bytes.fromhex("0050")), Write(11, bytes.fromhex("8a"))),
    ),
    Patch(
        name="patch_range_1",
        offset=0xDA04,
        range_len=16,
        expected_range_sha256="cad698e029e49e8557fa4259c816e318021875a348f0d2b967ed1579fce8439b",
        patched_range_sha256="9bf52da965bdf744685e93b31353826af7bc74bc1fc3248d91f3b89f493444fe",
        writes=(
            Write(1, bytes.fromhex("0050")),
            Write(4, bytes.fromhex("00")),
            Write(7, bytes.fromhex("93")),
            Write(11, bytes.fromhex("9a01")),
            Write(15, bytes.fromhex("e3")),
        ),
    ),
    Patch(
        name="patch_range_2",
        offset=0x35FE0,
        range_len=4,
        expected_range_sha256="85a84a4f037c33de92504a8958803d3ca0aa78d17145ea83a7683d3f2fcc2547",
        patched_range_sha256="71b1548a3867fe8e62a860f8010becb36b0386c9e97d552809cebccb9d93881d",
        writes=(Write(0, bytes.fromhex("0000a0")),),
    ),
    Patch(
        name="patch_range_3",
        offset=0x35FF4,
        range_len=4,
        expected_range_sha256="4954ed54e1284656fc34df4acf32b7bb7239c20a64300e0d7698c727e1de8391",
        patched_range_sha256="71b1548a3867fe8e62a860f8010becb36b0386c9e97d552809cebccb9d93881d",
        writes=(Write(0, bytes.fromhex("0000a0e1")),),
    ),
    Patch(
        name="patch_range_4",
        offset=0x36000,
        range_len=16,
        expected_range_sha256="52c4701f0ebe03e78c0fed564727560fa0fc58e477656da7c254df341da5a55f",
        patched_range_sha256="801b48661d2b117e9d4c1065f5b27b8e68938ac8efaf47e5a1db1211d495f592",
        writes=(
            Write(0, bytes.fromhex("0000")),
            Write(4, bytes.fromhex("0000")),
            Write(8, bytes.fromhex("00")),
            Write(12, bytes.fromhex("0000a0e1")),
        ),
    ),
    Patch(
        name="patch_range_5",
        offset=0x363D8,
        range_len=4,
        expected_range_sha256="578b7e8e1392acf5b7a042f27140fdff16d967de87b359c4629374f363061deb",
        patched_range_sha256="588247adc40731e7dac725b7c418ce8dedc2a7318e61f12836086f31d5d41520",
        writes=(Write(0, bytes.fromhex("8c78")),),
    ),
    Patch(
        name="patch_range_6",
        offset=0x28420,
        range_len=60,
        expected_range_sha256="4a113f9e80b59325c236497a1f60eb4c25ecfc818d846bc838d30d7a9d153d48",
        patched_range_sha256="16f1f5712d28c39b0e2ddf193b57ea53b9d8f498d42cee86625f2ff2792eef5c",
        writes=(
            Write(
                0,
                bytes.fromhex(
                    "010058e30500001a70219fe578119fe502208fe001108fe005"
                ),
            ),
            Write(26, bytes.fromhex("a0e16cc3ffeb5c219f")),
            Write(
                36,
                bytes.fromhex("5c319fe5029096e7036096e70000a0e10000"),
            ),
            Write(55, bytes.fromhex("e10000a0")),
        ),
    ),
    Patch(
        name="patch_range_7",
        offset=0x285A0,
        range_len=4,
        expected_range_sha256="c77ead30bd3f6cae55371b8695c71e4c28de7b2006d3f17cd0a2629cdc98a5df",
        patched_range_sha256="27d18ebd92839189526cb6345d7f2d5e043d7551446dd60407975ef0e46e5cc4",
        writes=(Write(0, bytes.fromhex("4854")),),
    ),
    Patch(
        name="patch_range_8",
        offset=0x285AC,
        range_len=4,
        expected_range_sha256="a883b9c4475398a5852aaf4ef0b4cbd8bd0557c4206c4d8bafd69832c8d56a47",
        patched_range_sha256="a828ca69c6e94a3592c35b9989123858720ac9b114514e040d53a604f87e1d6d",
        writes=(Write(0, bytes.fromhex("48")),),
    ),
)


class PatchError(Exception):
    """Raised when the binary cannot be patched safely."""


def sha256(data: bytes) -> str:
    """Return the SHA-256 hex digest for *data*."""

    return hashlib.sha256(data).hexdigest()


def _verify_range(data: bytes, patch: Patch, expected_sha256: str) -> bool:
    end = patch.offset + patch.range_len
    return end <= len(data) and sha256(data[patch.offset:end]) == expected_sha256


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
        if not _verify_range(data, patch, patch.expected_range_sha256):
            raise PatchError(
                f"Patch precondition failed for {patch.name} at 0x{patch.offset:x}: "
                "unexpected precheck hash"
            )
        for write in patch.writes:
            end = patch.offset + write.offset + len(write.data)
            if write.offset < 0 or end > patch.offset + patch.range_len:
                raise PatchError(f"Patch write out of range for {patch.name}")
            data[patch.offset + write.offset : end] = write.data
        if not _verify_range(data, patch, patch.patched_range_sha256):
            raise PatchError(f"Patch verification failed for {patch.name}")

    patched_digest = sha256(data)
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
        sys.stderr.write(f"error: {err}\n")
        return 1
    except PatchError as err:
        sys.stderr.write(f"error: {err}\n")
        return 2

    sys.stdout.write(f"{digest}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
