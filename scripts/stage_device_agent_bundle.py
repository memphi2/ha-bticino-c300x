#!/usr/bin/env python3
"""Stage the native-agent bundle inside the integration package tree.

The repository keeps the ARMHF binary and generated device bundle out of git.
Local HA-test installs still need the same package shape as the HACS release,
so this helper stages those generated files before copying the custom component.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "bticino_c300x"
COMPONENT_SRC = ROOT / "custom_components" / DOMAIN
AGENT_BINARY = ROOT / "native_agent" / "build" / "armhf" / "c300x-agent-native"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target",
        type=Path,
        default=COMPONENT_SRC,
        help="Integration package directory to stage into.",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Use the already built ARMHF agent binary.",
    )
    args = parser.parse_args()

    try:
        version = integration_version(COMPONENT_SRC)
        stage_bundle(args.target, version=version, skip_build=args.skip_build)
    except BundleStageError as err:
        sys.stderr.write(f"{err}\n")
        return 1
    return 0


class BundleStageError(Exception):
    """Raised when the native-agent bundle cannot be staged."""


def integration_version(component_dir: Path) -> str:
    """Return the integration version from a component manifest."""

    manifest_path = component_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise BundleStageError(f"Cannot read integration manifest: {manifest_path}") from err
    return str(manifest["version"])


def stage_bundle(
    component_dir: Path,
    *,
    version: str,
    skip_build: bool = False,
) -> None:
    """Stage all native-agent files required by the config-flow installer."""

    component_dir = component_dir.resolve()
    if not skip_build:
        _run(["make", "-C", str(ROOT / "native_agent"), "armhf", "armhf-abi-check"])
    if not AGENT_BINARY.exists():
        raise BundleStageError(
            "Missing ARMHF agent binary. Run native_agent armhf build first."
        )

    _copy(ROOT / "device_qml" / "Alarm.qml", component_dir / "device_agent/qml/Alarm.qml")
    _copy(
        ROOT / "device_qml" / "HomeAssistant.qml",
        component_dir / "device_agent/qml/HomeAssistant.qml",
    )
    for name in ("c300x_ha.js", "c300x_i18n.js", "c300x_memos.js"):
        _copy(
            ROOT / "device_qml" / "js" / name,
            component_dir / "device_agent/qml/js" / name,
        )
    _copy(
        ROOT / "native_agent" / "scripts" / "qml_patch.sh",
        component_dir / "device_agent/scripts/qml_patch.sh",
    )
    _copy(
        ROOT / "native_agent" / "scripts" / "remove_agent.sh",
        component_dir / "device_agent/scripts/remove_agent.sh",
    )
    _copy(AGENT_BINARY, component_dir / "device_agent/armhf/c300x-agent-native")
    (component_dir / "device_agent/bundle.json").write_text(
        json.dumps(
            {
                "version": version,
                "architecture": "armhf",
                "agent": "device_agent/armhf/c300x-agent-native",
                "qml": "device_agent/qml",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _copy(source: Path, target: Path) -> None:
    if not source.exists():
        raise BundleStageError(f"Missing native-agent bundle source: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _run(args: list[str]) -> None:
    try:
        subprocess.run(args, cwd=ROOT, check=True)
    except subprocess.CalledProcessError as err:
        raise BundleStageError("Native-agent ARMHF build failed") from err


if __name__ == "__main__":
    raise SystemExit(main())
