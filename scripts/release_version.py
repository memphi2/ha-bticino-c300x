"""Shared stable, beta and release-candidate version policy."""

from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path

from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:(?:b|rc)[1-9][0-9]*)?"


def validate_version(value: str) -> str:
    """Accept canonical X.Y.Z, X.Y.ZbN and X.Y.ZrcN versions."""

    if not re.fullmatch(VERSION_PATTERN, value):
        raise ValueError("expected X.Y.Z, X.Y.ZbN or X.Y.ZrcN")
    return value


def version_from_tag(tag: str) -> str:
    """Validate a tag before using it in commands or file paths."""

    if not tag.startswith("v"):
        raise ValueError("release tag must start with v")
    return validate_version(tag[1:])


def is_prerelease(tag: str) -> bool:
    """Derive the publication channel from the validated tag."""

    return Version(version_from_tag(tag)).is_prerelease


def select_previous_tag(tags: Iterable[str], current_tag: str) -> str | None:
    """Choose the newest older version, with b2 < b10 < rc1 < stable."""

    current = Version(version_from_tag(current_tag))
    candidates: dict[Version, str] = {}
    for tag in tags:
        try:
            version = Version(version_from_tag(tag))
        except ValueError:
            continue
        if version < current:
            candidates[version] = tag
    return candidates[max(candidates)] if candidates else None


def previous_release_tag(current_tag: str, root: Path = ROOT) -> str | None:
    """Find a preceding version in the current checkout's ancestry."""

    version_from_tag(current_tag)
    tags = subprocess.check_output(
        ["git", "-C", str(root), "tag", "--merged", "HEAD"], text=True
    )
    return select_previous_tag(tags.splitlines(), current_tag)


def main() -> int:
    parser = argparse.ArgumentParser(description="Print the preceding release tag.")
    parser.add_argument("tag")
    args = parser.parse_args()
    try:
        tag = previous_release_tag(args.tag)
    except (ValueError, subprocess.CalledProcessError) as err:
        parser.exit(1, f"Cannot select previous release: {err}\n")
    print(tag or "")  # noqa: T201 - CLI output consumed by release workflow
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
