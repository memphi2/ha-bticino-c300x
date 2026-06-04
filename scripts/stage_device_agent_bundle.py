#!/usr/bin/env python3
"""Stage the native-agent bundle inside the integration package tree.

The repository keeps the ARMHF binary and generated device bundle out of git.
Local HA-test installs still need the same package shape as the HACS release,
so this helper stages those generated files before copying the custom component.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "bticino_c300x"
COMPONENT_SRC = ROOT / "custom_components" / DOMAIN
AGENT_BINARY = ROOT / "native_agent" / "build" / "armhf" / "c300x-agent-native"
AGENT_VERSION_FILE = ROOT / "native_agent" / "VERSION"
AGENT_API_VERSION = "1"
ARMHF_STRIP = "arm-linux-gnueabihf-strip"
FIREWALL_PATCH_MATERIAL = "c300x-native-agent-ipv4-firewall-v1-api-port"
IPV6_FIREWALL_PATCH_MATERIAL = "c300x-native-agent-ipv6-firewall-v1-api-port"
CONFIG_SCHEMA_MATERIAL = "c300x-native-agent-config-schema-v1"


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


def agent_version() -> str:
    """Return the native device-agent version independent from HA releases."""

    try:
        version = AGENT_VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError as err:
        raise BundleStageError(f"Cannot read native agent version: {AGENT_VERSION_FILE}") from err
    if not version:
        raise BundleStageError("Native agent version must not be empty")
    return version


def stage_bundle(
    component_dir: Path,
    *,
    version: str,
    skip_build: bool = False,
) -> None:
    """Stage all native-agent files required by the config-flow installer."""

    component_dir = component_dir.resolve()
    if not skip_build:
        _run(["make", "-C", str(ROOT / "native_agent"), "clean"])
        _run(["make", "-C", str(ROOT / "native_agent"), "armhf", "armhf-abi-check"])
    if not AGENT_BINARY.exists():
        raise BundleStageError(
            "Missing ARMHF agent binary. Run native_agent armhf build first."
        )
    native_version = agent_version()

    staged_files: list[Path] = []
    qml_files: list[Path] = []
    script_files: list[Path] = []
    runtime_files: list[Path] = []
    alarm_qml = _copy(
        ROOT / "device_qml" / "Alarm.qml",
        component_dir / "device_agent/qml/Alarm.qml",
    )
    qml_files.append(alarm_qml)
    _copy(
        ROOT / "device_qml" / "HomeAssistant.qml",
        component_dir / "device_agent/qml/HomeAssistant.qml",
    )
    qml_files.append(component_dir / "device_agent/qml/HomeAssistant.qml")
    for name in ("c300x_ha.js", "c300x_i18n.js", "c300x_memos.js"):
        qml_files.append(
            _copy(
                ROOT / "device_qml" / "js" / name,
                component_dir / "device_agent/qml/js" / name,
            )
        )
    qml_patch_script = _copy(
        ROOT / "native_agent" / "scripts" / "qml_patch.sh",
        component_dir / "device_agent/scripts/qml_patch.sh",
    )
    qml_files.append(qml_patch_script)
    script_files.append(qml_patch_script)
    remove_script = _copy(
        ROOT / "native_agent" / "scripts" / "remove_agent.sh",
        component_dir / "device_agent/scripts/remove_agent.sh",
    )
    script_files.append(remove_script)
    bootstrap_firewall_script = _copy(
        ROOT / "native_agent" / "scripts" / "bootstrap_firewall.sh",
        component_dir / "device_agent/scripts/bootstrap_firewall.sh",
    )
    script_files.append(bootstrap_firewall_script)
    runtime_files.append(
        _copy_agent_binary(AGENT_BINARY, component_dir / "device_agent/armhf/c300x-agent-native")
    )
    _set_file_modes(qml_files, 0o644)
    _set_file_modes(script_files, 0o700)
    _set_file_modes(runtime_files, 0o700)
    staged_files.extend(_unique_paths(runtime_files + script_files + qml_files))
    file_entries = _file_entries(component_dir, staged_files)
    group_hashes = {
        "runtime_hash": _content_hash(component_dir, runtime_files),
        "script_hash": _content_hash(component_dir, script_files),
        "qml_patch_hash": _content_hash(component_dir, qml_files),
        "firewall_patch_hash": _material_hash(FIREWALL_PATCH_MATERIAL),
        "ipv6_firewall_patch_hash": _material_hash(IPV6_FIREWALL_PATCH_MATERIAL),
        "config_schema_hash": _content_hash(
            ROOT,
            [ROOT / "native_agent" / "config.example.json"],
            extra_material=CONFIG_SCHEMA_MATERIAL,
        ),
    }
    bundle_hash = _bundle_hash(
        agent_version=native_version,
        api_version=AGENT_API_VERSION,
        files=file_entries,
        group_hashes=group_hashes,
    )
    manifest_path = component_dir / "device_agent/bundle.json"
    manifest_path.write_text(
        json.dumps(
            {
                "version": native_version,
                "agent_version": native_version,
                "integration_version": version,
                "api_version": AGENT_API_VERSION,
                "architecture": "armhf",
                "bundle_hash": bundle_hash,
                "agent": "device_agent/armhf/c300x-agent-native",
                "qml": "device_agent/qml",
                "files": file_entries,
                **group_hashes,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_path.chmod(0o600)


def _copy(source: Path, target: Path) -> Path:
    if not source.exists():
        raise BundleStageError(f"Missing native-agent bundle source: {source}")
    if source.resolve() == target.resolve():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def _copy_agent_binary(source: Path, target: Path) -> Path:
    """Copy the ARMHF agent into the release bundle and strip release symbols."""

    copied = _copy(source, target)
    if copied.read_bytes()[:4] == b"\x7fELF":
        _run([ARMHF_STRIP, "--strip-unneeded", str(copied)])
    return copied


def _set_file_modes(paths: list[Path], mode: int) -> None:
    """Apply deterministic device bundle modes before hashing the manifest."""

    for path in paths:
        path.chmod(mode)


def _unique_paths(paths: list[Path]) -> list[Path]:
    """Return paths once while preserving their first logical occurrence."""

    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def _file_entries(component_dir: Path, files: list[Path]) -> list[dict[str, str | int]]:
    """Return deterministic file metadata for the staged device bundle."""

    entries: list[dict[str, str | int]] = []
    for path in sorted(files):
        relative_path = path.relative_to(component_dir).as_posix()
        entries.append(
            {
                "path": relative_path,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size": path.stat().st_size,
                "mode": f"{path.stat().st_mode & 0o777:03o}",
            }
        )
    return entries


def _content_hash(
    component_dir: Path,
    files: list[Path],
    *,
    extra_material: str = "",
) -> str:
    """Return a stable hash for a logical device-artifact group."""

    digest = hashlib.sha256()
    if extra_material:
        digest.update(extra_material.encode())
        digest.update(b"\0")
    for path in sorted(files):
        digest.update(path.relative_to(component_dir).as_posix().encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _material_hash(material: str) -> str:
    """Return a stable hash for generated device behavior without a source file."""

    return f"sha256:{hashlib.sha256(material.encode()).hexdigest()}"


def _bundle_hash(
    *,
    agent_version: str,
    api_version: str,
    files: list[dict[str, str | int]],
    group_hashes: dict[str, str],
) -> str:
    """Return a stable hash for the complete native-agent device bundle."""

    payload = json.dumps(
        {
            "agent_version": agent_version,
            "api_version": api_version,
            "files": files,
            "groups": group_hashes,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _run(args: list[str]) -> None:
    try:
        subprocess.run(args, cwd=ROOT, check=True)
    except subprocess.CalledProcessError as err:
        raise BundleStageError("Native-agent ARMHF build failed") from err


if __name__ == "__main__":
    raise SystemExit(main())
