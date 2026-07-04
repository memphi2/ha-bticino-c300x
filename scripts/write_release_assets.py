#!/usr/bin/env python3
"""Write deterministic release metadata, checksums, and an SPDX SBOM."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
COMPONENT_MANIFEST = ROOT / "custom_components" / "bticino_c300x" / "manifest.json"
NATIVE_AGENT_VERSION = ROOT / "native_agent" / "VERSION"
PROJECT_VERSIONS = ROOT / "project-versions.json"
DEFAULT_PACKAGE_NAME = "ha-bticino-c300x"
DEFAULT_REPOSITORY = "unknown"


@dataclass(frozen=True)
class ZipEntry:
    name: str
    size: int
    sha256: str


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", required=True, type=Path, help="Release zip asset.")
    parser.add_argument("--tag", required=True, help="Release tag, for example v1.6.2.")
    parser.add_argument(
        "--repository",
        default=os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPOSITORY),
        help="GitHub repository name used in build metadata.",
    )
    parser.add_argument(
        "--native-agent-reused-from",
        default=os.environ.get("C300X_NATIVE_AGENT_REUSED_FROM", ""),
        help="Release tag whose native agent binary was reused, if any.",
    )
    parser.add_argument(
        "--sha256sums",
        required=True,
        type=Path,
        help="Output SHA256SUMS path.",
    )
    parser.add_argument(
        "--metadata",
        required=True,
        type=Path,
        help="Output build metadata JSON path.",
    )
    parser.add_argument(
        "--sbom",
        required=True,
        type=Path,
        help="Output SPDX 2.3 SBOM JSON path.",
    )
    args = parser.parse_args()

    try:
        write_release_assets(
            zip_path=args.zip,
            tag=args.tag,
            repository=args.repository,
            native_agent_reused_from=args.native_agent_reused_from,
            sha256sums_path=args.sha256sums,
            metadata_path=args.metadata,
            sbom_path=args.sbom,
        )
    except ReleaseAssetError as err:
        sys.stderr.write(f"{err}\n")
        return 1
    return 0


class ReleaseAssetError(Exception):
    """Raised when release asset metadata cannot be generated."""


def write_release_assets(
    *,
    zip_path: Path,
    tag: str,
    repository: str,
    sha256sums_path: Path,
    metadata_path: Path,
    sbom_path: Path,
    native_agent_reused_from: str = "",
) -> None:
    if not zip_path.exists():
        raise ReleaseAssetError(f"release zip does not exist: {zip_path}")

    zip_entries = _zip_entries(zip_path)
    zip_sha256 = _sha256_file(zip_path)
    integration_version = _integration_version()
    native_agent_version = _native_agent_version()
    commit = _git_output("rev-parse", "HEAD") or os.environ.get("GITHUB_SHA", "unknown")
    commit_date = _git_output("show", "-s", "--format=%cI", "HEAD")
    created = _spdx_timestamp(commit_date)
    bundle = _device_bundle_summary(zip_path)

    metadata = _build_metadata(
        tag=tag,
        repository=repository,
        commit=commit,
        integration_version=integration_version,
        native_agent_version=native_agent_version,
        native_agent_reused_from=native_agent_reused_from.strip() or None,
        zip_path=zip_path,
        zip_sha256=zip_sha256,
        zip_entries=zip_entries,
        bundle=bundle,
    )
    _write_json(metadata_path, metadata)

    sbom = _spdx_document(
        tag=tag,
        repository=repository,
        package_name=DEFAULT_PACKAGE_NAME,
        version=integration_version,
        zip_sha256=zip_sha256,
        zip_entries=zip_entries,
        created=created,
    )
    _write_json(sbom_path, sbom)
    _write_sha256sums(sha256sums_path, (zip_path, metadata_path, sbom_path))


def _build_metadata(
    *,
    tag: str,
    repository: str,
    commit: str,
    integration_version: str,
    native_agent_version: str,
    native_agent_reused_from: str | None,
    zip_path: Path,
    zip_sha256: str,
    zip_entries: list[ZipEntry],
    bundle: dict[str, str] | None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "schema_version": 1,
        "name": DEFAULT_PACKAGE_NAME,
        "release_tag": tag,
        "repository": repository,
        "git_commit": commit,
        "integration_version": integration_version,
        "native_agent_version": native_agent_version,
        "lts_evidence": _lts_evidence(
            tag=tag,
            native_agent_reused_from=native_agent_reused_from,
        ),
        "artifacts": [
            {
                "filename": zip_path.name,
                "sha256": zip_sha256,
                "size": zip_path.stat().st_size,
                "zip_entry_count": len(zip_entries),
            }
        ],
    }
    if bundle is not None:
        metadata["device_agent_bundle"] = bundle
    return metadata


def _lts_evidence(
    *,
    tag: str,
    native_agent_reused_from: str | None,
) -> dict[str, Any]:
    versions = _project_versions()
    return {
        "release": tag,
        "min_homeassistant": versions["min_homeassistant"],
        "current_homeassistant": versions["current_homeassistant"],
        "validated_homeassistant": [
            versions["min_homeassistant"],
            versions["current_homeassistant"],
        ],
        "python": versions["python"],
        "firmware_target": versions["c300x_firmware"],
        "native_agent_rebuilt": native_agent_reused_from is None,
        "native_agent_reused_from": native_agent_reused_from,
        "validated_jobs": ["min-ha", "current-ha", "hacs", "hassfest"],
    }


def _spdx_document(
    *,
    tag: str,
    repository: str,
    package_name: str,
    version: str,
    zip_sha256: str,
    zip_entries: list[ZipEntry],
    created: str,
) -> dict[str, Any]:
    package_id = "SPDXRef-Package-ha-bticino-c300x"
    file_documents: list[dict[str, Any]] = []
    relationships: list[dict[str, str]] = []
    for entry in zip_entries:
        file_id = _spdx_file_id(entry.name)
        file_documents.append(
            {
                "SPDXID": file_id,
                "fileName": entry.name,
                "checksums": [
                    {
                        "algorithm": "SHA256",
                        "checksumValue": entry.sha256,
                    }
                ],
                "licenseConcluded": "NOASSERTION",
                "copyrightText": "NOASSERTION",
            }
        )
        relationships.append(
            {
                "spdxElementId": package_id,
                "relationshipType": "CONTAINS",
                "relatedSpdxElement": file_id,
            }
        )

    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{package_name}-{tag}",
        "documentNamespace": (
            f"https://github.com/{repository}/releases/tag/{tag}#spdx-{zip_sha256}"
        ),
        "creationInfo": {
            "created": created,
            "creators": ["Tool: scripts/write_release_assets.py"],
        },
        "documentDescribes": [package_id],
        "packages": [
            {
                "SPDXID": package_id,
                "name": package_name,
                "versionInfo": version,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": True,
                "checksums": [
                    {
                        "algorithm": "SHA256",
                        "checksumValue": zip_sha256,
                    }
                ],
                "licenseConcluded": "Apache-2.0",
                "licenseDeclared": "Apache-2.0",
                "copyrightText": "NOASSERTION",
            }
        ],
        "files": file_documents,
        "relationships": relationships,
    }


def _zip_entries(zip_path: Path) -> list[ZipEntry]:
    entries: list[ZipEntry] = []
    try:
        with zipfile.ZipFile(zip_path) as archive:
            for info in sorted(archive.infolist(), key=lambda item: item.filename):
                if info.is_dir():
                    continue
                data = archive.read(info.filename)
                entries.append(
                    ZipEntry(
                        name=info.filename,
                        size=len(data),
                        sha256=hashlib.sha256(data).hexdigest(),
                    )
                )
    except zipfile.BadZipFile as err:
        raise ReleaseAssetError(f"invalid release zip: {zip_path}") from err
    return entries


def _device_bundle_summary(zip_path: Path) -> dict[str, str] | None:
    try:
        with zipfile.ZipFile(zip_path) as archive:
            data = archive.read("device_agent/bundle.json")
    except KeyError:
        return None
    except zipfile.BadZipFile as err:
        raise ReleaseAssetError(f"invalid release zip: {zip_path}") from err

    bundle = cast(dict[str, Any], json.loads(data.decode("utf-8")))
    keys = (
        "version",
        "agent_version",
        "api_version",
        "architecture",
        "bundle_hash",
        "runtime_hash",
        "script_hash",
        "qml_patch_hash",
        "firewall_patch_hash",
        "ipv6_firewall_patch_hash",
        "config_schema_hash",
    )
    summary: dict[str, str] = {}
    for key in keys:
        value = bundle.get(key)
        if isinstance(value, str):
            summary[key] = value
    return summary


def _integration_version() -> str:
    manifest = cast(dict[str, Any], json.loads(COMPONENT_MANIFEST.read_text(encoding="utf-8")))
    version = manifest.get("version")
    if not isinstance(version, str):
        raise ReleaseAssetError("manifest.json version must be a string")
    return version


def _project_versions() -> dict[str, str]:
    versions = cast(dict[str, Any], json.loads(PROJECT_VERSIONS.read_text(encoding="utf-8")))
    required = (
        "min_homeassistant",
        "current_homeassistant",
        "python",
        "c300x_firmware",
    )
    missing = [key for key in required if not isinstance(versions.get(key), str)]
    if missing:
        raise ReleaseAssetError(
            f"project-versions.json is missing string keys: {', '.join(missing)}"
        )
    return {key: cast(str, versions[key]) for key in required}


def _native_agent_version() -> str:
    version = NATIVE_AGENT_VERSION.read_text(encoding="utf-8").strip()
    if not version:
        raise ReleaseAssetError("native_agent/VERSION must not be empty")
    return version


def _write_sha256sums(output: Path, paths: tuple[Path, ...]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{_sha256_file(path)}  {path.name}" for path in paths]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_output(*args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _spdx_timestamp(value: str | None) -> str:
    if value is None:
        return "1970-01-01T00:00:00Z"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "1970-01-01T00:00:00Z"
    return (
        parsed.astimezone(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _spdx_file_id(name: str) -> str:
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
    return f"SPDXRef-File-{digest}"


if __name__ == "__main__":
    raise SystemExit(main())
