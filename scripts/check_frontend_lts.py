#!/usr/bin/env python3
"""Validate Lovelace-card compatibility contracts for the supported HA line."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from update_frontend_hashes import (
    FRONTEND_IMPORT_VERSION_PATTERN,
    FRONTEND_MODULES,
    frontend_bundle_hash,
    frontend_module_paths,
    update_frontend_import_hashes,
)

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "custom_components" / "bticino_c300x" / "frontend"
PROJECT_VERSIONS = ROOT / "project-versions.json"
MAIN_CARD = FRONTEND_DIR / "c300x-doorbell-call-card.js"
METADATA = FRONTEND_DIR / "c300x-doorbell-call-card-metadata.js"
EDITOR = FRONTEND_DIR / "c300x-card-editor.js"
LIFECYCLE = FRONTEND_DIR / "c300x-card-lifecycle.js"
WEBRTC = FRONTEND_DIR / "c300x-webrtc-client.js"

FORBIDDEN_FRONTEND_TOKENS = ("mwc" + "-", "paper" + "-", "ha" + "-fab")
REQUIRED_CONTRACT_SNIPPETS = {
    MAIN_CARD: (
        "static getConfigElement()",
        "static getStubConfig(hass, entityId)",
        "getGridOptions()",
        "formatEntityName",
        "subscribeEvents",
        "documentationURL: C300X_DOCUMENTATION_URL",
        "preview: false",
    ),
    METADATA: (
        "getEntitySuggestion: c300xMetadataEntitySuggestion",
        'import "./c300x-doorbell-call-card.js?v=',
    ),
    EDITOR: (
        "<ha-form>",
        "selector: { entity_name: {} }",
        'context: { entity: "entity" }',
    ),
}


def main() -> int:
    failures = check_frontend_lts()
    if failures:
        for failure in failures:
            sys.stderr.write(f"FAIL: {failure}\n")
        return 1
    versions = _project_versions()
    sys.stdout.write(
        "Frontend LTS gate passed "
        f"(HA {versions['min_homeassistant']}..{versions['current_homeassistant']})\n"
    )
    return 0


def check_frontend_lts() -> list[str]:
    failures: list[str] = []
    failures.extend(_check_project_versions())
    failures.extend(_check_module_inventory())
    failures.extend(_check_forbidden_tokens())
    failures.extend(_check_required_contracts())
    failures.extend(_check_bundle_cachebuster())
    return failures


def _check_project_versions() -> list[str]:
    versions = _project_versions()
    failures: list[str] = []
    for key in ("min_homeassistant", "current_homeassistant"):
        if not _valid_semver(versions.get(key, "")):
            failures.append(f"project-versions.json must define {key} as x.y.z")
    if _version_tuple(versions["min_homeassistant"]) > _version_tuple(
        versions["current_homeassistant"]
    ):
        failures.append("min_homeassistant must not be newer than current_homeassistant")
    return failures


def _check_module_inventory() -> list[str]:
    configured = set(FRONTEND_MODULES)
    present = {path.name for path in FRONTEND_DIR.glob("*.js")}
    failures: list[str] = []
    missing = sorted(configured - present)
    extra = sorted(present - configured)
    if missing:
        failures.append(f"frontend bundle source missing: {', '.join(missing)}")
    if extra:
        failures.append(f"frontend bundle source not listed: {', '.join(extra)}")
    return failures


def _check_forbidden_tokens() -> list[str]:
    failures: list[str] = []
    for path in frontend_module_paths():
        source = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_FRONTEND_TOKENS:
            if token in source:
                failures.append(f"{_relative(path)} must not use legacy HA frontend token {token!r}")
    return failures


def _check_required_contracts() -> list[str]:
    failures: list[str] = []
    for path, snippets in REQUIRED_CONTRACT_SNIPPETS.items():
        source = path.read_text(encoding="utf-8")
        for snippet in snippets:
            if snippet not in source:
                failures.append(f"{_relative(path)} must keep frontend contract: {snippet}")
    return failures


def _check_bundle_cachebuster() -> list[str]:
    bundle_hash = frontend_bundle_hash()
    failures = [
        f"stale frontend import hash in {path}"
        for path in update_frontend_import_hashes(bundle_hash, check=True)
    ]
    expected_import = f"?v={bundle_hash}"
    for path in (MAIN_CARD, METADATA, EDITOR, LIFECYCLE, WEBRTC):
        source = path.read_text(encoding="utf-8")
        import_hashes = set(FRONTEND_IMPORT_VERSION_PATTERN.findall(source))
        stale_hashes = sorted(value for value in import_hashes if value != expected_import)
        if stale_hashes:
            failures.append(
                f"{_relative(path)} must use bundle cachebuster {expected_import}, got "
                + ", ".join(stale_hashes)
            )
    return failures


def _project_versions() -> dict[str, str]:
    return {
        key: str(value)
        for key, value in json.loads(PROJECT_VERSIONS.read_text(encoding="utf-8")).items()
    }


def _valid_semver(version: str) -> bool:
    parts = version.split(".")
    return len(parts) == 3 and all(part.isdigit() for part in parts)


def _version_tuple(version: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in version.split("."))  # type: ignore[return-value]


def _relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


if __name__ == "__main__":
    sys.exit(main())
