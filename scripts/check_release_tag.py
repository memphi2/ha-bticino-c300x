#!/usr/bin/env python3
"""Validate that a release tag matches the checked-out integration version."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path

from check_reporting import report_failures
from manifest_version import read_integration_version

ROOT = Path(__file__).resolve().parents[1]
TAG_RE = re.compile(r"v(?P<version>\d+\.\d+\.\d+)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tag", help="Release tag, for example v1.6.2.")
    parser.add_argument(
        "--attestation-context",
        action="store_true",
        help="Require the GitHub workflow ref and commit to match the release checkout.",
    )
    args = parser.parse_args()

    failures = validate_release_tag(args.tag)
    if args.attestation_context:
        commit = subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
        ).strip()
        failures.extend(
            validate_attestation_context(
                args.tag,
                workflow_ref=os.environ.get("GITHUB_REF", ""),
                workflow_commit=os.environ.get("GITHUB_SHA", ""),
                checkout_commit=commit,
            )
        )
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


def validate_attestation_context(
    tag: str,
    *,
    workflow_ref: str,
    workflow_commit: str,
    checkout_commit: str,
) -> list[str]:
    """Bind the signing workflow identity to the release source."""

    failures: list[str] = []
    if workflow_ref != f"refs/tags/{tag}":
        failures.append(f"release attestation workflow must run from refs/tags/{tag}")
    if not checkout_commit or workflow_commit != checkout_commit:
        failures.append("release attestation workflow commit must match the checkout")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
