#!/usr/bin/env python3
"""Create a local C300X bt_answering_machine compatibility patch copy.

This tool is intentionally narrow: it only accepts the known C300X 1.7.19, 2.0.2
and 3.0.6 and C100X 1.5.8 stock bt_answering_machine routing targets and writes
a patched copy to an explicit output path. It never modifies the input file in place and it verifies expected patch ranges by
hash instead of storing byte ranges in this repository.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

STOCK_SHA256 = "605a808f1ed0c826c06bbf1eb4131b9198007a7ab822e7541a6666e79816c810"
STOCK_SHA256_2_0_2 = "18a555afcfb3c1d163cdb649cdd7a61e9526e08aec8275f88dd78df4bc5f2ec7"


@dataclass(frozen=True)
class Write:
    """One byte write inside a verified patch range."""

    offset: int
    data: bytes


@dataclass(frozen=True)
class Patch:
    """One hash-verified routing setup range."""

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


# Firmware 2.0.2 rebuilt the same binary: the writes are unchanged, only the
# offsets moved. Range 4 has another stock hash because its call moved too.
PATCHES_2_0_2: tuple[Patch, ...] = tuple(
    Patch(
        name=patch.name,
        offset=offset,
        range_len=patch.range_len,
        expected_range_sha256=expected,
        patched_range_sha256=patch.patched_range_sha256,
        writes=patch.writes,
    )
    for patch, offset, expected in zip(
        PATCHES,
        (0x28300, 0xDA08, 0x35FE8, 0x35FFC, 0x36008, 0x363E0, 0x28428, 0x285A8, 0x285B4),
        (
            "ed451a5b137b7b59ebfd3f4bb8ff6598a18abce58603b72eed97f50b8d6391b8",
            "cad698e029e49e8557fa4259c816e318021875a348f0d2b967ed1579fce8439b",
            "85a84a4f037c33de92504a8958803d3ca0aa78d17145ea83a7683d3f2fcc2547",
            "4954ed54e1284656fc34df4acf32b7bb7239c20a64300e0d7698c727e1de8391",
            "e5843cd556cbbd9fc95fa4ae7b7291050d9a66615285f82804755eaf14039f2a",
            "578b7e8e1392acf5b7a042f27140fdff16d967de87b359c4629374f363061deb",
            "4a113f9e80b59325c236497a1f60eb4c25ecfc818d846bc838d30d7a9d153d48",
            "c77ead30bd3f6cae55371b8695c71e4c28de7b2006d3f17cd0a2629cdc98a5df",
            "a883b9c4475398a5852aaf4ef0b4cbd8bd0557c4206c4d8bafd69832c8d56a47",
        ),
        strict=True,
    )
)

# Firmware 3.0.6 (Qt5-era PIE rebuild). Patch sites re-derived from the
# recompiled binary; the 1.7.x rec_json_f restructure collapses to a literal
# route_ext->route_int redirect because the symlink call exists inline here.
STOCK_SHA256_3_0_6 = "7f7b28e1579c93d1c752ecab220801f639a4c5fc7eb845d79fe76563e7c9f1cb"

PATCHES_3_0_6: tuple[Patch, ...] = (
    Patch(
        name="p0_mode_recjson",
        offset=0x27014,
        range_len=12,
        expected_range_sha256="a9db5d94fdd0cb9b4dae85941ac99762a33abcc5237db4edf051259c973b146e",
        patched_range_sha256="bfac450eff18576df39e787372d02b01c4ea3b4099d7cb1507ab4a21700d67cb",
        writes=(Write(1, bytes.fromhex("0050")), Write(11, bytes.fromhex("8a")),),
    ),
    Patch(
        name="p1_mode_sigusr2",
        offset=0xA1DC,
        range_len=16,
        expected_range_sha256="cad698e029e49e8557fa4259c816e318021875a348f0d2b967ed1579fce8439b",
        patched_range_sha256="9bf52da965bdf744685e93b31353826af7bc74bc1fc3248d91f3b89f493444fe",
        writes=(Write(1, bytes.fromhex("0050")), Write(4, bytes.fromhex("00")), Write(7, bytes.fromhex("93")), Write(11, bytes.fromhex("9a01")), Write(15, bytes.fromhex("e3")),),
    ),
    Patch(
        name="p2_nop_blx",
        offset=0x34D04,
        range_len=4,
        expected_range_sha256="85a84a4f037c33de92504a8958803d3ca0aa78d17145ea83a7683d3f2fcc2547",
        patched_range_sha256="71b1548a3867fe8e62a860f8010becb36b0386c9e97d552809cebccb9d93881d",
        writes=(Write(0, bytes.fromhex("0000a0")),),
    ),
    Patch(
        name="p3_nop_str",
        offset=0x34D1C,
        range_len=4,
        expected_range_sha256="4954ed54e1284656fc34df4acf32b7bb7239c20a64300e0d7698c727e1de8391",
        patched_range_sha256="71b1548a3867fe8e62a860f8010becb36b0386c9e97d552809cebccb9d93881d",
        writes=(Write(0, bytes.fromhex("0000a0e1")),),
    ),
    Patch(
        name="p4_nop_block",
        offset=0x34D24,
        range_len=16,
        expected_range_sha256="cea97ef00435c2c2429911a495511a3f914c7b055dd04c4176c141c71a6d7b27",
        patched_range_sha256="801b48661d2b117e9d4c1065f5b27b8e68938ac8efaf47e5a1db1211d495f592",
        writes=(Write(0, bytes.fromhex("0000")), Write(4, bytes.fromhex("0000")), Write(8, bytes.fromhex("00")), Write(12, bytes.fromhex("0000a0e1")),),
    ),
    Patch(
        name="p5_redir_update",
        offset=0x350DC,
        range_len=4,
        expected_range_sha256="60b7b33fa991351fdc7658edb4d51d7f1193979428b4a5516d302911a4352b9b",
        patched_range_sha256="2ddad22425195d27460390320d8ed0b8bdd67a6bcbc94b36a5b16af16fa3f678",
        writes=(Write(0, bytes.fromhex("7c830000")),),
    ),
    Patch(
        name="p6_redir_recjson",
        offset=0x272D8,
        range_len=4,
        expected_range_sha256="7bd214987c21b0d60e03be16fe943d682bdb18e9c85c006b1b8a363d31398245",
        patched_range_sha256="b4fe8af24b6dbb176ec9f93a250610fe56bad6c2807b5c0f2c10dab1722fbc89",
        writes=(Write(0, bytes.fromhex("f05e0100")),),
    ),
)

# Classe 100X 1.5.8: the same routing code as the C300X 1.7.19, built for that
# device. Same patch sites, other offsets and call targets.
STOCK_SHA256_C100X_1_5_8 = "cc53dd834361e8a76268b108ce2562b8447d597798dd2f136ce4707142485e12"

PATCHES_C100X_1_5_8: tuple[Patch, ...] = (
    Patch(
        name="patch_range_0",
        offset=0x27958,
        range_len=12,
        expected_range_sha256="ed451a5b137b7b59ebfd3f4bb8ff6598a18abce58603b72eed97f50b8d6391b8",
        patched_range_sha256="59e44ff04f935f33e91e44d52771e6188e7a50c735c07b54f236087a818925d7",
        writes=(Write(1, bytes.fromhex("0050")), Write(11, bytes.fromhex("8a")),),
    ),
    Patch(
        name="patch_range_1",
        offset=0xCCDC,
        range_len=16,
        expected_range_sha256="cad698e029e49e8557fa4259c816e318021875a348f0d2b967ed1579fce8439b",
        patched_range_sha256="9bf52da965bdf744685e93b31353826af7bc74bc1fc3248d91f3b89f493444fe",
        writes=(Write(1, bytes.fromhex("0050")), Write(4, bytes.fromhex("00")), Write(7, bytes.fromhex("93")), Write(11, bytes.fromhex("9a01")), Write(15, bytes.fromhex("e3")),),
    ),
    Patch(
        name="patch_range_2",
        offset=0x353C0,
        range_len=4,
        expected_range_sha256="85a84a4f037c33de92504a8958803d3ca0aa78d17145ea83a7683d3f2fcc2547",
        patched_range_sha256="71b1548a3867fe8e62a860f8010becb36b0386c9e97d552809cebccb9d93881d",
        writes=(Write(0, bytes.fromhex("0000a0")),),
    ),
    Patch(
        name="patch_range_3",
        offset=0x353D4,
        range_len=4,
        expected_range_sha256="4954ed54e1284656fc34df4acf32b7bb7239c20a64300e0d7698c727e1de8391",
        patched_range_sha256="71b1548a3867fe8e62a860f8010becb36b0386c9e97d552809cebccb9d93881d",
        writes=(Write(0, bytes.fromhex("0000a0e1")),),
    ),
    Patch(
        name="patch_range_4",
        offset=0x353E0,
        range_len=16,
        expected_range_sha256="a3c4925a787f8f0a30438bd324e0aa354bfddce3b559dff84bff2ac2997f8d1b",
        patched_range_sha256="801b48661d2b117e9d4c1065f5b27b8e68938ac8efaf47e5a1db1211d495f592",
        writes=(Write(0, bytes.fromhex("0000")), Write(4, bytes.fromhex("0000")), Write(8, bytes.fromhex("00")), Write(12, bytes.fromhex("0000a0e1")),),
    ),
    Patch(
        name="patch_range_5",
        offset=0x357B0,
        range_len=4,
        expected_range_sha256="86fee0a47ad59e05660f2942600617081e2566a6dfae1e91eb677916b4343f51",
        patched_range_sha256="536d1d675a6befffe6b908d9f5dbee941995f64fa735e852375f65c4c1ac0fd9",
        writes=(Write(0, bytes.fromhex("647a0000")),),
    ),
    Patch(
        name="patch_range_6",
        offset=0x27A80,
        range_len=60,
        expected_range_sha256="4a113f9e80b59325c236497a1f60eb4c25ecfc818d846bc838d30d7a9d153d48",
        patched_range_sha256="0798984c1f9bff3d03759999f8b3f110b2752d77de089fa60a5659e60d8e1935",
        writes=(Write(0, bytes.fromhex("010058e30500001a70219fe578119fe502208fe001108fe005")), Write(26, bytes.fromhex("a0e140c2ffeb5c219f")), Write(36, bytes.fromhex("5c319fe5029096e7036096e70000a0e10000")), Write(55, bytes.fromhex("e10000a0")),),
    ),
    Patch(
        name="patch_range_7",
        offset=0x27C00,
        range_len=4,
        expected_range_sha256="4b59487eb8ab373488f734840d731a784b012a9efcd74b32524d5b910fa625af",
        patched_range_sha256="f41460fb396a434b65dcb784d93cb083e8fefcd641430ee4dd36e68a0e69add5",
        writes=(Write(0, bytes.fromhex("a0530100")),),
    ),
    Patch(
        name="patch_range_8",
        offset=0x27C0C,
        range_len=4,
        expected_range_sha256="1522ff5a062ae5f276461e938415126b0cd09935ed9de2fee73d7f6294512bee",
        patched_range_sha256="f70bee9ce146862e6e2c2bad32fdda100b0b2705a523971840050b55f9c26567",
        writes=(Write(0, bytes.fromhex("143e0100")),),
    ),
)


class PatchError(Exception):
    """Raised when the routing target cannot be patched safely."""


def sha256(data: bytes) -> str:
    """Return the SHA-256 hex digest for *data*."""

    return hashlib.sha256(data).hexdigest()


def _verify_range(data: bytes, patch: Patch, expected_sha256: str) -> bool:
    end = patch.offset + patch.range_len
    return end <= len(data) and sha256(data[patch.offset:end]) == expected_sha256


def patch_routing(source: Path, target: Path) -> str:
    """Patch *source* and write a new routing target to *target*."""

    if source.resolve() == target.resolve() or (target.exists() and source.samefile(target)):
        raise PatchError("Source and target must be different files")
    if target.is_symlink():
        raise PatchError("Target must not be a symbolic link")
    data = bytearray(source.read_bytes())
    digest = sha256(bytes(data))
    if digest == STOCK_SHA256:
        patches = PATCHES
    elif digest == STOCK_SHA256_2_0_2:
        patches = PATCHES_2_0_2
    elif digest == STOCK_SHA256_3_0_6:
        patches = PATCHES_3_0_6
    elif digest == STOCK_SHA256_C100X_1_5_8:
        patches = PATCHES_C100X_1_5_8
    else:
        raise PatchError(
            f"Unsupported bt_answering_machine SHA-256: {digest}; expected "
            f"{STOCK_SHA256}, {STOCK_SHA256_2_0_2}, {STOCK_SHA256_3_0_6} "
            f"or {STOCK_SHA256_C100X_1_5_8}"
        )

    for patch in patches:
        if not _verify_range(bytes(data), patch, patch.expected_range_sha256):
            raise PatchError(
                f"Patch precondition failed for {patch.name} at 0x{patch.offset:x}: "
                "unexpected precheck hash"
            )
        for write in patch.writes:
            end = patch.offset + write.offset + len(write.data)
            if write.offset < 0 or end > patch.offset + patch.range_len:
                raise PatchError(f"Patch write out of range for {patch.name}")
            data[patch.offset + write.offset : end] = write.data
        if not _verify_range(bytes(data), patch, patch.patched_range_sha256):
            raise PatchError(f"Patch verification failed for {patch.name}")

    patched_digest = sha256(bytes(data))
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.name}.", delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
            output.flush()
            os.fchmod(output.fileno(), source.stat().st_mode & 0o7777)
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
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
        digest = patch_routing(args.source, args.target)
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
