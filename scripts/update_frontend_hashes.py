#!/usr/bin/env python3
"""Update or verify cache-busting hashes for bundled frontend modules."""

from __future__ import annotations

import argparse
import re
import sys
from hashlib import sha256
from pathlib import Path

from check_reporting import report_failures

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "custom_components" / "bticino_c300x" / "frontend"
FRONTEND_IMPORT_VERSION_PATTERN = re.compile(r"\?v=[0-9a-f]{16}")
FRONTEND_BUNDLE_PLACEHOLDER = "?v=__C300X_FRONTEND_BUNDLE__"
FRONTEND_MODULES = (
    "c300x-doorbell-call-card.js",
    "c300x-doorbell-call-card-metadata.js",
    "c300x-card-actions.js",
    "c300x-card-editor.js",
    "c300x-card-lifecycle.js",
    "c300x-card-template.js",
    "c300x-entity-resolver.js",
    "c300x-media-attach.js",
    "c300x-ringback-tone.js",
    "c300x-ring-preview-state.js",
    "c300x-state-model.js",
    "c300x-translations.js",
    "c300x-webrtc-client.js",
    "c300x-webrtc-debug.js",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if frontend import hashes are not current",
    )
    args = parser.parse_args()

    failures = _validate_module_list()
    if failures:
        return report_failures(failures)

    bundle_hash = frontend_bundle_hash()
    changed = update_frontend_import_hashes(bundle_hash, check=args.check)
    if changed and args.check:
        for path in changed:
            sys.stderr.write(f"FAIL: stale frontend import hash in {path}\n")
        sys.stderr.write(
            "Run scripts/update_frontend_hashes.py to refresh bundled frontend hashes.",
        )
        sys.stderr.write("\n")
        return 1
    if changed:
        for path in changed:
            sys.stdout.write(f"Updated frontend import hash in {path}\n")
    sys.stdout.write(f"Frontend bundle hash: {bundle_hash}\n")
    return 0


def frontend_bundle_hash() -> str:
    digest = sha256()
    for source_path in frontend_module_paths():
        digest.update(source_path.name.encode())
        digest.update(b"\0")
        digest.update(_normalized_bytes(source_path))
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def frontend_module_paths() -> tuple[Path, ...]:
    return tuple(FRONTEND_DIR / name for name in FRONTEND_MODULES)


def update_frontend_import_hashes(bundle_hash: str, *, check: bool) -> list[str]:
    changed: list[str] = []
    for source_path in frontend_module_paths():
        source = source_path.read_text(encoding="utf-8")
        updated = FRONTEND_IMPORT_VERSION_PATTERN.sub(f"?v={bundle_hash}", source)
        if updated == source:
            continue
        changed.append(str(source_path.relative_to(ROOT)))
        if not check:
            source_path.write_text(updated, encoding="utf-8")
    return changed


def _normalized_bytes(path: Path) -> bytes:
    return FRONTEND_IMPORT_VERSION_PATTERN.sub(
        FRONTEND_BUNDLE_PLACEHOLDER,
        path.read_text(encoding="utf-8"),
    ).encode()


def _validate_module_list() -> list[str]:
    failures: list[str] = []
    configured = set(FRONTEND_MODULES)
    present = {path.name for path in FRONTEND_DIR.glob("*.js")}
    missing = sorted(configured - present)
    extra = sorted(present - configured)
    if missing:
        failures.append(f"frontend bundle source missing: {', '.join(missing)}")
    if extra:
        failures.append(f"frontend bundle source not listed: {', '.join(extra)}")
    return failures


if __name__ == "__main__":
    sys.exit(main())
