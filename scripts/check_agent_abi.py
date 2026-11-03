#!/usr/bin/env python3
"""Fail closed when the native agent's firmware ABI cannot be verified."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys


def check_abi(binary: str, readelf: str) -> None:
    result = subprocess.run(
        [readelf, "--version-info", binary],
        capture_output=True, text=True, check=True, timeout=30,
    )
    versions = set(re.findall(r"\bGLIBC_[A-Za-z0-9_.]+", result.stdout))
    if not versions:
        raise ValueError("readelf returned no GLIBC version requirements")
    for name in sorted(versions):
        match = re.fullmatch(r"GLIBC_(\d+)\.(\d+)(?:\.(\d+))?", name)
        if match is None:
            raise ValueError(f"unrecognized firmware ABI requirement: {name}")
        version = tuple(int(part or 0) for part in match.groups())
        if version > (2, 26, 0):
            raise ValueError(f"{name} requires glibc newer than firmware glibc 2.26")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary")
    parser.add_argument("--readelf", default="arm-linux-gnueabihf-readelf")
    args = parser.parse_args()
    try:
        check_abi(args.binary, args.readelf)
    except (OSError, subprocess.SubprocessError, ValueError) as err:
        sys.stderr.write(f"FAIL: ARMHF ABI check: {err}\n")
        return 1
    sys.stdout.write("ARMHF ABI check passed\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
