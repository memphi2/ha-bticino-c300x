#!/usr/bin/env python3
"""Build a local-only Qt 4.8.7 ARM test probe using a private firmware sysroot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tests/qml/qt4_runtime_probe.c"
START = ROOT / "native_agent/src/arm_start.S"
KEYS = ("QEMU", "ROOTFS", "PROBE", "IMPORTS")


def cache_directory() -> Path:
    """Keep generated executables and private paths out of the checkout."""
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "c300x-dev/qt4-runtime"


def source_digest() -> str:
    return hashlib.sha256(SOURCE.read_bytes() + START.read_bytes() + Path(__file__).read_bytes()).hexdigest()


def validate_paths(paths: list[str]) -> None:
    if len(paths) != 4 or not all(isinstance(path, str) and path for path in paths):
        raise ValueError("Qt 4 runtime needs QEMU, ROOTFS, PROBE and IMPORTS paths")
    if any(char in paths[1] for char in (":", "\n", "\r", ",")):
        raise ValueError("Firmware path cannot contain loader/QEMU separators")
    for index, path in enumerate(paths):
        target = Path(path)
        if not (target.is_dir() if index in (1, 3) else target.is_file() and os.access(target, os.X_OK)):
            raise ValueError(f"Missing Qt 4 runtime path: {path}; rerun scripts/setup_qt4_runtime.py")


def runtime_paths() -> list[str] | None:
    """Explicit variables win and the built setup supplies the rest; a wrong variable or setup fails, never skips.

    The runtime is unconfigured, and its tests skip, only without a built
    setup and with none of the variables set, or with just QEMU and ROOTFS,
    both valid: those two are also the variables of the compile and render
    tests.
    """
    explicit = [os.environ.get("C300X_QT4_" + key, "") for key in KEYS]
    for index, (key, path) in enumerate(zip(KEYS, explicit, strict=True)):
        target = Path(path)
        if path and not (target.is_dir() if index in (1, 3) else target.is_file() and os.access(target, os.X_OK)):
            kind = "a directory" if index in (1, 3) else "an executable file"
            raise ValueError(f"C300X_QT4_{key} is not {kind}: {path}")
    if all(explicit):
        validate_paths(explicit)
        return explicit
    manifest = cache_directory() / "environment.json"
    if not manifest.exists():
        if explicit[2] or explicit[3] or bool(explicit[0]) != bool(explicit[1]):
            missing = ", ".join("C300X_QT4_" + key for key, path in zip(KEYS, explicit, strict=True)
                                if not path and (explicit[2] or explicit[3] or key in KEYS[:2]))
            raise ValueError(f"Qt 4 runtime: set {missing} as well, or run scripts/setup_qt4_runtime.py")
        return None
    data = json.loads(manifest.read_text())
    if not isinstance(data, dict) or data.get("schema") != 1 or data.get("source_sha256") != source_digest():
        raise ValueError("Stale Qt 4 runtime; rerun scripts/setup_qt4_runtime.py")
    built = data.get("paths", [])
    if not isinstance(built, list):
        raise ValueError("Invalid Qt 4 runtime paths")
    validate_paths(built)
    if hashlib.sha256(Path(built[2]).read_bytes()).hexdigest() != data.get("binary_sha256"):
        raise ValueError("Qt 4 probe differs from its build; rerun scripts/setup_qt4_runtime.py")
    paths = [given or path for given, path in zip(explicit, built, strict=True)]
    validate_paths(paths)
    return paths


def probe_command(paths: list[str], qml: Path) -> list[str]:
    qemu, rootfs, probe, imports = paths
    return [qemu, "-L", rootfs, "-E", f"LD_LIBRARY_PATH={rootfs}/usr/lib:{rootfs}/lib",
            probe, str(qml.resolve()), imports]


def install(rootfs: Path, compiler: str, qemu: str) -> Path:
    rootfs = rootfs.expanduser().resolve()
    cache = cache_directory().expanduser().resolve()
    if cache.is_relative_to(ROOT) or cache.is_relative_to(rootfs):
        raise ValueError("Qt 4 cache must be outside the repository and firmware sysroot")
    for library in ("lib/ld-linux-armhf.so.3", "usr/lib/libQtCoreE.so.4", "usr/lib/libQtDeclarativeE.so.4"):
        if not (rootfs / library).is_file():
            raise ValueError(f"Missing firmware library: {library}")
    cc, emulator = shutil.which(compiler), shutil.which(qemu)
    if not cc or not emulator:
        raise ValueError("Install an ARMHF C compiler and qemu-arm first")
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix=".build-", dir=cache) as temporary:
        stage = Path(temporary)
        probe = stage / "qml_runtime_probe"
        imports = stage / "imports"
        imports.mkdir()
        subprocess.run([
            cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-D_DEFAULT_SOURCE",
            "-D_POSIX_C_SOURCE=200809L", "-D_TIME_BITS=32", "-Wl,--export-dynamic",
            str(SOURCE), str(START), "-pthread", f"-Wl,-rpath-link,{rootfs}/lib",
            f"-L{rootfs}/lib", "-l:libpthread.so.0", "-l:libdl.so.2", "-l:libc.so.6",
            "-l:ld-linux-armhf.so.3", "-nostartfiles", "-o", str(probe),
        ], check=True, capture_output=True, timeout=60)
        paths = [emulator, str(rootfs), str(probe), str(imports)]
        validate_paths(paths)
        result = subprocess.run(probe_command(paths, ROOT / "tests/qml/energy_consumers_qt4.qml"),
                                check=True, capture_output=True, text=True, timeout=30)
        output = result.stdout + result.stderr
        if "QT4_RUNTIME_VERSION 4.8.7" not in output or "C300X_CONSUMERS_QT4_PASS 214" not in output:
            raise ValueError(f"Qt 4 smoke test did not confirm its runtime and checks:\n{output}")
        sys.stderr.write(output)
        # Publish only a successfully tested probe; no vendor files are copied.
        destination = cache / "qml_runtime_probe"
        probe.replace(destination)
        (cache / "imports").mkdir(exist_ok=True)
        data = {"schema": 1, "source_sha256": source_digest(),
                "binary_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                "paths": [emulator, str(rootfs), str(destination), str(cache / "imports")]}
        staged_manifest = stage / "environment.json"
        staged_manifest.write_text(json.dumps(data, indent=2) + "\n")
        staged_manifest.replace(cache / "environment.json")
    return cache


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sysroot", required=True, type=Path)
    parser.add_argument("--compiler", default="arm-linux-gnueabihf-gcc")
    parser.add_argument("--qemu", default="qemu-arm")
    args = parser.parse_args()
    try:
        path = install(args.sysroot, args.compiler, args.qemu)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        sys.stderr.write(f"FAIL: Qt 4 runtime setup: {error}\n")
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            sys.stderr.write(error.stderr.decode() if isinstance(error.stderr, bytes) else error.stderr)
        return 1
    sys.stdout.write(f"Qt 4 runtime ready: {path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
