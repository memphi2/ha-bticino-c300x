#!/usr/bin/env python3
"""Build a HACS release zip with the native C300X agent bundle included."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

from stage_device_agent_bundle import AGENT_BINARY, stage_bundle

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "bticino_c300x"
COMPONENT_SRC = ROOT / "custom_components" / DOMAIN
RELEASE_ROOT = ROOT / ".release"
PACKAGE_ROOT = RELEASE_ROOT / "package"
AUTO_DEVICE_SYSROOT = ROOT.parent / "c300x-fwpatch" / "work" / "rootfs-1.7.19"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
PACKAGE_METADATA = (
    "LICENSE",
    "NOTICE",
    "PRIVACY.md",
    "SECURITY.md",
    "docs/legal.md",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Package the already built ARMHF agent binary.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output zip path. Defaults to .release/ha-bticino-c300x.zip.",
    )
    parser.add_argument(
        "--reuse-agent-from-release-zip",
        type=Path,
        default=None,
        help=(
            "Extract the ARMHF agent binary from an existing HACS release zip. "
            "Use only when native-agent and device bundle inputs are unchanged."
        ),
    )
    args = parser.parse_args()

    version = _integration_version()
    if args.reuse_agent_from_release_zip is not None:
        try:
            _restore_agent_from_release_zip(args.reuse_agent_from_release_zip)
        except (OSError, zipfile.BadZipFile, KeyError) as err:
            sys.stderr.write(f"Cannot reuse ARMHF agent from release zip: {err}\n")
            return 1
    elif not args.skip_build:
        sysroot = _release_sysroot()
        if sysroot is None:
            sys.stderr.write(
                "C300X_DEVICE_SYSROOT is required for release ARMHF builds. "
                "Use --skip-build only with a verified existing agent binary.\n"
            )
            return 1
        env = os.environ.copy()
        env["C300X_DEVICE_SYSROOT"] = str(sysroot)
        _run(
            ["make", "-C", str(ROOT / "native_agent"), "armhf", "armhf-abi-check"],
            env=env,
        )
    if not AGENT_BINARY.exists():
        sys.stderr.write("Missing ARMHF agent binary. Run without --skip-build first.\n")
        return 1

    output = args.output or RELEASE_ROOT / "ha-bticino-c300x.zip"
    _prepare_package(version)
    _write_zip(output)
    sys.stdout.write(f"{output}\n")
    return 0


def _integration_version() -> str:
    manifest = json.loads((COMPONENT_SRC / "manifest.json").read_text(encoding="utf-8"))
    return str(manifest["version"])


def _prepare_package(version: str) -> None:
    if PACKAGE_ROOT.exists():
        shutil.rmtree(PACKAGE_ROOT)
    shutil.copytree(
        COMPONENT_SRC,
        PACKAGE_ROOT,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "device_agent/armhf"),
    )

    stage_bundle(PACKAGE_ROOT, version=version, skip_build=True)
    _copy_package_metadata()


def _copy_package_metadata() -> None:
    """Include legal/security metadata in the standalone HACS zip asset."""

    for relative_name in PACKAGE_METADATA:
        source = ROOT / relative_name
        target = PACKAGE_ROOT / relative_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _write_zip(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(PACKAGE_ROOT.rglob("*")):
            if path.is_file():
                archive.writestr(_zip_info(path), path.read_bytes())


def _restore_agent_from_release_zip(zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        data = archive.read("device_agent/armhf/c300x-agent-native")
    AGENT_BINARY.parent.mkdir(parents=True, exist_ok=True)
    AGENT_BINARY.write_bytes(data)
    AGENT_BINARY.chmod(0o700)


def _zip_info(path: Path) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(
        filename=path.relative_to(PACKAGE_ROOT).as_posix(),
        date_time=ZIP_TIMESTAMP,
    )
    info.compress_type = zipfile.ZIP_DEFLATED
    mode = path.stat().st_mode & 0o777
    info.external_attr = (stat.S_IFREG | mode) << 16
    return info


def _release_sysroot() -> Path | None:
    explicit = os.environ.get("C300X_DEVICE_SYSROOT")
    if explicit:
        path = Path(explicit).expanduser()
        return path if _is_device_sysroot(path) else None
    return AUTO_DEVICE_SYSROOT if _is_device_sysroot(AUTO_DEVICE_SYSROOT) else None


def _is_device_sysroot(path: Path) -> bool:
    return (path / "lib" / "libc.so.6").exists()


def _run(args: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(args, cwd=ROOT, check=True, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
