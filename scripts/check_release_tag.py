#!/usr/bin/env python3
"""Validate that a release tag matches the checked-out integration version."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from check_reporting import report_failures
from manifest_version import read_integration_version

ROOT = Path(__file__).resolve().parents[1]
TAG_RE = re.compile(r"v(?P<version>\d+\.\d+\.\d+)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tag", help="Release tag, for example v1.6.2.")
    args = parser.parse_args()

    failures = validate_release_tag(args.tag)
    return report_failures(
        failures,
        f"Release tag {args.tag} matches repository metadata",
    )


def validate_release_tag(tag: str, root: Path = ROOT) -> list[str]:
    failures: list[str] = []
    match = TAG_RE.fullmatch(tag)
    if match is None:
        return [f"release tag must use vX.Y.Z format, got {tag!r}"]

    version = match.group("version")
    manifest_version = read_integration_version(
        root / "custom_components" / "bticino_c300x" / "manifest.json"
    )
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


if __name__ == "__main__":
    raise SystemExit(main())
