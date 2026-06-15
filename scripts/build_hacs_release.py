#!/usr/bin/env python3
"""Build a HACS release zip with the native C300X agent bundle included."""

from __future__ import annotations

import argparse
import json
import shutil
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
    args = parser.parse_args()

    version = _integration_version()
    if not args.skip_build:
        _run(["make", "-C", str(ROOT / "native_agent"), "armhf", "armhf-abi-check"])
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
                archive.write(path, path.relative_to(PACKAGE_ROOT))


def _run(args: list[str]) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


if __name__ == "__main__":
    raise SystemExit(main())
