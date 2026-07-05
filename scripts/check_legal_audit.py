#!/usr/bin/env python3
"""Focused legal/provenance gate for release preparation."""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_DIRS = {
    "dist",
    "external",
    "extracted",
    "firmware",
    "node_modules",
    "original_firmware",
    "third_party",
    "vendor",
}
FORBIDDEN_SUFFIXES = {
    ".7z",
    ".a",
    ".apk",
    ".bin",
    ".deb",
    ".ext4",
    ".fwz",
    ".gz",
    ".img",
    ".ipk",
    ".o",
    ".pcap",
    ".pcapng",
    ".rpm",
    ".so",
    ".tar",
    ".tgz",
    ".xz",
    ".zip",
}
STOCK_QML_NAMES = {"HomePage.qml", "MainApp.qml", "MemoPage.qml"}
CODE_SUFFIXES = {".c", ".h", ".js", ".py", ".qml", ".sh"}
REFERENCE_MARKERS = (
    "slyoldfox",
    "c300x-controller",
    "fquinto/bticinoClasse300x",
    "bticinoClasse300x",
)
LEGAL_PHRASES = (
    "No firmware or APK payloads",
    "No vendored third-party controller code",
    "Media codecs and patents",
    "Trademark notice",
    "not affiliated with, endorsed by, sponsored by, or certified by",
    "project-owned generic artwork",
    "Apache License, Version 2.0",
)
NOTICE_PHRASES = (
    "not affiliated with, endorsed by, sponsored by, or certified by",
    "trademarks or names of their respective owners",
)
PROJECT_OWNED_BRAND_HASH = (
    "cd64c8c333ae2cfde2f32a8681054c1a5755a2edafadec1183501cd774088834"
)


def main() -> int:
    failures: list[str] = []
    tracked = _tracked_files()
    if tracked is None:
        return 1

    failures.extend(_check_tracked_payloads(tracked))
    failures.extend(_check_reference_markers(tracked))
    failures.extend(_check_required_documents())
    failures.extend(_check_runtime_requirements())
    failures.extend(_check_brand_assets())

    if failures:
        for failure in failures:
            sys.stderr.write(f"FAIL: {failure}\n")
        return 1

    classes = _extension_counts(tracked)
    sys.stdout.write("Legal/provenance audit passed\n")
    sys.stdout.write(f"tracked_files={len(tracked)}\n")
    sys.stdout.write(
        "tracked_extensions="
        + ", ".join(f"{key}:{classes[key]}" for key in sorted(classes))
        + "\n"
    )
    return 0


def _tracked_files() -> list[Path] | None:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        sys.stderr.write("FAIL: unable to inspect tracked files\n")
        return None
    return [Path(line) for line in result.stdout.splitlines() if line.strip()]


def _check_tracked_payloads(paths: list[Path]) -> list[str]:
    failures: list[str] = []
    for rel in paths:
        parts = rel.parts
        if any(part in FORBIDDEN_DIRS for part in parts):
            failures.append(f"foreign/runtime directory must not be tracked: {rel}")
        if rel.suffix.lower() in FORBIDDEN_SUFFIXES:
            failures.append(f"forbidden binary/archive/payload must not be tracked: {rel}")
        if rel.name in STOCK_QML_NAMES and parts[:1] in {("device_qml",), ("custom_components",)}:
            failures.append(f"stock/vendor QML page must not be tracked: {rel}")
    return failures


def _check_reference_markers(paths: list[Path]) -> list[str]:
    failures: list[str] = []
    allowed_prefixes = {
        ".github",
        "docs",
        "tests",
    }
    allowed_files = {
        "CHANGELOG.md",
        "NOTICE",
        "PRIVACY.md",
        "README.md",
        "SECURITY.md",
        "scripts/check_legal_audit.py",
        "scripts/check_repo.py",
    }
    for rel in paths:
        if rel.suffix not in CODE_SUFFIXES:
            continue
        if rel.parts and rel.parts[0] in allowed_prefixes:
            continue
        if str(rel) in allowed_files:
            continue
        text = (ROOT / rel).read_text(encoding="utf-8", errors="ignore").lower()
        for marker in REFERENCE_MARKERS:
            if marker.lower() in text:
                failures.append(
                    f"third-party/reference marker {marker!r} belongs in docs, not runtime code: {rel}"
                )
    return failures


def _check_required_documents() -> list[str]:
    failures: list[str] = []
    for rel in (
        "LICENSE",
        "NOTICE",
        "PRIVACY.md",
        "SECURITY.md",
        "docs/legal.md",
        "docs/audits/current-legal-provenance.md",
    ):
        if not (ROOT / rel).is_file():
            failures.append(f"missing legal/provenance document: {rel}")
    audit_files = sorted(path.name for path in (ROOT / "docs" / "audits").glob("*.md"))
    if audit_files != ["current-legal-provenance.md"]:
        failures.append(
            "docs/audits must contain only current-legal-provenance.md, got "
            + ", ".join(audit_files)
        )
    legal_path = ROOT / "docs" / "legal.md"
    if legal_path.is_file():
        legal = _normalized_text(legal_path)
        for phrase in LEGAL_PHRASES:
            if phrase not in legal:
                failures.append(f"docs/legal.md must mention {phrase!r}")
    notice_path = ROOT / "NOTICE"
    if notice_path.is_file():
        notice = _normalized_text(notice_path)
        for phrase in NOTICE_PHRASES:
            if phrase not in notice:
                failures.append(f"NOTICE must mention {phrase!r}")
    readme_path = ROOT / "README.md"
    if readme_path.is_file():
        first_line = readme_path.read_text(encoding="utf-8").splitlines()[0]
        if "(Unofficial)" not in first_line:
            failures.append("README title must keep the project marked as unofficial")
    return failures


def _check_runtime_requirements() -> list[str]:
    manifest = json.loads(
        (ROOT / "custom_components" / "bticino_c300x" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    requirements = manifest.get("requirements", [])
    if requirements:
        return [f"manifest.json runtime requirements must stay empty, got {requirements!r}"]
    return []


def _check_brand_assets() -> list[str]:
    failures: list[str] = []
    for rel in (
        "custom_components/bticino_c300x/brand/icon.png",
        "custom_components/bticino_c300x/brand/logo.png",
    ):
        digest = _sha256(ROOT / rel)
        if digest != PROJECT_OWNED_BRAND_HASH:
            failures.append(f"brand asset hash changed and docs/legal.md needs review: {rel}")
    return failures


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalized_text(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def _extension_counts(paths: list[Path]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for path in paths:
        counts[path.suffix or "[none]"] += 1
    return counts


if __name__ == "__main__":
    sys.exit(main())
