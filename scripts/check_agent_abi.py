#!/usr/bin/env python3
"""Fail closed when the native agent's firmware ABI cannot be verified."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# The C library files the agent links against, as the dynamic linker finds them.
SYSTEM_LIBRARIES = ("libc.so.6", "libpthread.so.0", "libdl.so.2", "ld-linux-armhf.so.3")
# What the agent loads with dlopen/dlsym at run time. A firmware that lacks one
# of these functions fails only when the feature is used, so it is checked here.
RUNTIME_SYMBOLS: dict[str, tuple[str, ...]] = {
    "libcurl.so.4": (
        "curl_easy_cleanup", "curl_easy_getinfo", "curl_easy_init", "curl_easy_perform",
        "curl_easy_setopt", "curl_global_init", "curl_slist_append", "curl_slist_free_all",
        "curl_version_info",
    ),
    "libsrtp.so.1": (
        "srtp_create", "srtp_dealloc", "srtp_init", "srtp_protect", "srtp_protect_rtcp",
        "srtp_unprotect", "srtp_unprotect_rtcp",
    ),
    "libspeex.so.1": (
        "speex_bits_destroy", "speex_bits_init", "speex_bits_read_from", "speex_bits_reset",
        "speex_bits_write", "speex_decode_int", "speex_decoder_destroy", "speex_decoder_init",
        "speex_encode_int", "speex_encoder_destroy", "speex_encoder_init", "speex_lib_get_mode",
    ),
}


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


def _readelf(readelf: str, *args: str) -> str:
    return subprocess.run(
        [readelf, *args], capture_output=True, text=True, check=True, timeout=30,
    ).stdout


def _dynamic_symbols(readelf: str, path: str, *, imported: bool) -> set[str]:
    """Return the imported or the defined dynamic symbols, with their version."""

    symbols = set()
    for line in _readelf(readelf, "-W", "--dyn-syms", path).splitlines():
        parts = line.split()
        if len(parts) < 8 or not parts[0].endswith(":"):
            continue
        if (parts[6] == "UND") is imported:
            symbols.add(parts[7].replace("@@", "@"))
    return symbols


def _library(sysroot: Path, name: str) -> Path:
    for folder in ("lib", "usr/lib"):
        path = sysroot / folder / name
        if path.exists():
            return path
    raise ValueError(f"{sysroot} lacks {name}")


def check_sysroot(binary: str, readelf: str, sysroot: Path) -> None:
    """Check that a firmware root file system has everything the agent uses.

    The agent is built against the oldest supported firmware. A newer one
    must still provide every versioned C library symbol it imports and every
    function it loads at run time.
    """

    needed = re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", _readelf(readelf, "-d", binary))
    if not needed:
        raise ValueError("readelf returned no needed libraries")
    for name in needed:
        _library(sysroot, name)
    defined: set[str] = set()
    for name in SYSTEM_LIBRARIES:
        defined |= _dynamic_symbols(readelf, str(_library(sysroot, name)), imported=False)
    imported = {name for name in _dynamic_symbols(readelf, binary, imported=True) if "@" in name}
    missing = sorted(imported - defined)
    if missing:
        raise ValueError(f"{sysroot} lacks {', '.join(missing[:5])}")
    for library, functions in RUNTIME_SYMBOLS.items():
        provided = {
            name.split("@", 1)[0]
            for name in _dynamic_symbols(readelf, str(_library(sysroot, library)), imported=False)
        }
        absent = [name for name in functions if name not in provided]
        if absent:
            raise ValueError(f"{sysroot}: {library} lacks {', '.join(absent)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary")
    parser.add_argument("--readelf", default="arm-linux-gnueabihf-readelf")
    parser.add_argument(
        "--sysroot", action="append", default=[], type=Path,
        help="Firmware root file system the binary must run on; repeat for each.",
    )
    args = parser.parse_args()
    try:
        check_abi(args.binary, args.readelf)
        for sysroot in args.sysroot:
            check_sysroot(args.binary, args.readelf, sysroot)
    except (OSError, subprocess.SubprocessError, ValueError) as err:
        sys.stderr.write(f"FAIL: ARMHF ABI check: {err}\n")
        return 1
    sys.stdout.write("ARMHF ABI check passed\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
