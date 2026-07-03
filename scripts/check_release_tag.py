#!/usr/bin/env python3
"""Validate that a release tag matches the checked-out integration version."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
TAG_RE = re.compile(r"v(?P<version>\d+\.\d+\.\d+)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tag", help="Release tag, for example v1.6.2.")
    args = parser.parse_args()

    failures = validate_release_tag(args.tag)
    if failures:
        for failure in failures:
            sys.stderr.write(f"FAIL: {failure}\n")
        return 1
    sys.stdout.write(f"Release tag {args.tag} matches repository metadata\n")
    return 0


def validate_release_tag(tag: str, root: Path = ROOT) -> list[str]:
    failures: list[str] = []
    match = TAG_RE.fullmatch(tag)
    if match is None:
        return [f"release tag must use vX.Y.Z format, got {tag!r}"]

    version = match.group("version")
    manifest_version = _manifest_version(root)
    if manifest_version != version:
        failures.append(
            f"manifest version {manifest_version!r} does not match release tag {tag!r}"
        )

    changelog = root / "CHANGELOG.md"
    if tag not in changelog.read_text(encoding="utf-8"):
        failures.append(f"CHANGELOG.md must contain a {tag} section")

    release_note = root / ".github" / "release-notes" / f"{tag}.md"
    if not release_note.exists():
        failures.append(f"missing release notes file: {release_note.relative_to(root)}")
    elif tag not in release_note.read_text(encoding="utf-8"):
        failures.append(f"{release_note.relative_to(root)} must mention {tag}")

    return failures


def _manifest_version(root: Path) -> str:
    manifest_path = root / "custom_components" / "bticino_c300x" / "manifest.json"
    manifest = cast(dict[str, Any], json.loads(manifest_path.read_text(encoding="utf-8")))
    version = manifest.get("version")
    if not isinstance(version, str):
        raise ValueError("manifest.json version must be a string")
    return version


if __name__ == "__main__":
    raise SystemExit(main())
