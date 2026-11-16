#!/usr/bin/env python3
"""Cache the pinned upstream TurboJPEG library for Linux amd64 dev/CI only."""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import platform
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

VERSION = "3.2.1"
ASSET = f"libjpeg-turbo-official_{VERSION}_amd64.deb"
URL = f"https://github.com/libjpeg-turbo/libjpeg-turbo/releases/download/{VERSION}/{ASSET}"
# Published release asset digest (GitHub API asset 682859044), not a live lookup.
SHA256 = "21c7af6e505386dda0fa05e9eab5a8d288947f2e09ade8d7a48ff393ed08182d"
ASSET_SIZE = 730000
LIBRARY_MEMBER = "./opt/libjpeg-turbo/lib64/libturbojpeg.so.0.5.0"
LIBRARY_SIZE = 1272504
ROOT = Path(__file__).resolve().parents[1]


def verify_package(data: bytes) -> None:
    """Reject changed downloads and corrupt cache entries before parsing."""
    if len(data) != ASSET_SIZE or hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError(f"{ASSET}: size/SHA256 mismatch")


def library_payload(data: bytes) -> bytes:
    """Read exactly one regular member; never extract archive paths or links."""
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        members = [m for m in archive if m.name == LIBRARY_MEMBER]
        if len(members) != 1:
            raise ValueError("Expected exactly one pinned TurboJPEG library member")
        member = members[0]
        if not member.isfile() or member.issparse() or member.size != LIBRARY_SIZE:
            raise ValueError("TurboJPEG member must be a regular file of the pinned size")
        stream = archive.extractfile(member)
        if stream is None:
            raise ValueError("TurboJPEG library payload is missing")
        with stream:
            payload = stream.read(LIBRARY_SIZE + 1)
        if len(payload) != LIBRARY_SIZE:
            raise ValueError("TurboJPEG library payload is truncated")
        return payload


def install(cache: Path) -> Path:
    """Verify the package on every run and atomically refresh its sole library."""
    cache = cache.expanduser().resolve()
    if cache.is_relative_to(ROOT):
        raise ValueError("TurboJPEG cache must be outside the repository")
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    package = cache / ASSET
    # Stage privately: dpkg-deb reads the verified bytes, never a mutable cache path.
    with tempfile.TemporaryDirectory(prefix=".turbojpeg-", dir=cache) as temporary:
        stage = Path(temporary)
        if package.exists():
            data = package.read_bytes()
        else:
            with urllib.request.urlopen(URL, timeout=60) as response:
                if not response.url.startswith("https://"):
                    raise ValueError("TurboJPEG download requires HTTPS")
                data = response.read(ASSET_SIZE + 1)
        verify_package(data)
        verified = stage / ASSET
        verified.write_bytes(data)
        result = subprocess.run(
            ["dpkg-deb", "--fsys-tarfile", str(verified)],
            check=True, capture_output=True, timeout=30,
        )
        payload = library_payload(result.stdout)
        libdir = cache / f"turbojpeg-{VERSION}-{SHA256[:12]}" / "lib"
        if libdir.is_symlink() or libdir.parent.is_symlink():
            raise ValueError("TurboJPEG library directory must not be a symlink")
        libdir.mkdir(parents=True, exist_ok=True, mode=0o700)
        library = libdir / "libturbojpeg.so.0"
        # Do not replace an identical mapped library during concurrent validation.
        if library.is_symlink() or not library.exists() or library.read_bytes() != payload:
            staged_library = stage / library.name
            staged_library.write_bytes(payload)
            staged_library.chmod(0o755)
            staged_library.replace(library)
        verified.replace(package)
    return library


def loader_path(library: Path) -> str:
    """Prepend our isolated directory without introducing an empty search entry."""
    directory = str(library.parent)
    if any(char in directory for char in ("\n", "\r", ":")):
        raise ValueError("TurboJPEG cache path cannot contain newlines or colons")
    entries = [directory, *os.environ.get("LD_LIBRARY_PATH", "").split(":")]
    value = ":".join(dict.fromkeys(entry for entry in entries if entry))
    if "\n" in value or "\r" in value:
        raise ValueError("LD_LIBRARY_PATH cannot contain newlines")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_cache = Path(os.environ.get("RUNNER_TEMP") or os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "c300x-dev"
    parser.add_argument("--cache-dir", type=Path, default=default_cache)
    parser.add_argument("--github-env", action="store_true")
    args = parser.parse_args()
    try:
        if platform.system() != "Linux" or platform.machine() not in {"x86_64", "AMD64"}:
            raise ValueError("Pinned TurboJPEG package supports Linux amd64 only")
        library = install(args.cache_dir)
        value = loader_path(library)
        # LD_LIBRARY_PATH must be set before Python starts, not via ctypes preload.
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/check_turbojpeg.py"), "--expect-library", str(library)],
            env={**os.environ, "LD_LIBRARY_PATH": value},
            stdout=sys.stderr, check=True, timeout=60,
        )
        if args.github_env:
            with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as output:
                output.write(f"LD_LIBRARY_PATH={value}\n")
        sys.stdout.write(f"{library.parent}\n")
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, tarfile.TarError) as error:
        sys.stderr.write(f"FAIL: TurboJPEG setup: {error}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
