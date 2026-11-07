"""Publish verified assets without replacing an existing release."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from manifest_version import read_integration_version
from release_version import is_prerelease, version_from_tag

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ("ha-bticino-c300x.zip", "SHA256SUMS", "build-metadata.json", "sbom.spdx.json")


def run(*args: str) -> str:
    """Run a command without a shell and fail on API or authentication errors."""

    return subprocess.check_output(args, text=True)


def find_release(repository: str, tag: str) -> dict[str, Any] | None:
    """Distinguish an absent release from an unsuccessful lookup."""

    pages = json.loads(run("gh", "api", "--paginate", "--slurp",
                          f"repos/{repository}/releases?per_page=100"))
    matches = [release for page in pages for release in page if release.get("tag_name") == tag]
    if len(matches) > 1:
        raise ValueError("multiple releases for the tag")
    return matches[0] if matches else None


def verify_source_tag(repository: str, tag: str, commit: str) -> None:
    """Verify both lightweight and annotated remote tags against this checkout."""

    ref = f"refs/tags/{tag}"
    refs = dict(line.split()[::-1] for line in run(
        "git", "ls-remote", "--exit-code", f"https://github.com/{repository}.git",
        ref, f"{ref}^{{}}"
    ).splitlines())
    if refs.get(f"{ref}^{{}}", refs.get(ref)) != commit:
        raise ValueError("remote release tag does not match the checkout")


def publish(repository: str, tag: str, directory: Path) -> None:
    """Create a draft, verify downloads, then publish in the selected channel."""

    prerelease = is_prerelease(tag)
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", repository)
            or repository.split("/")[-1] in {".", ".."}):
        raise ValueError("expected owner/repository")
    if version_from_tag(tag) != read_integration_version():
        raise ValueError("tag does not match the integration version")
    notes_path = ROOT / ".github" / "release-notes" / f"{tag}.md"
    notes = notes_path.read_text(encoding="utf-8")
    for name in ASSETS:
        if not (directory / name).is_file() or (directory / name).stat().st_size == 0:
            raise ValueError(f"missing or empty release asset: {name}")
    commit = run("git", "rev-parse", "HEAD").strip()
    verify_source_tag(repository, tag, commit)
    flags = ("--prerelease", "--latest=false") if prerelease else ()
    release = find_release(repository, tag)
    if release is None:
        run("gh", "release", "create", tag, "--repo", repository, "--draft",
            "--verify-tag", "--title", tag, "--notes-file", str(notes_path),
            *flags, *(str(directory / name) for name in ASSETS))
        release = find_release(repository, tag)
    if release is None:
        raise ValueError("draft creation was not confirmed")
    if (release.get("tag_name") != tag or release.get("prerelease") is not prerelease
            or not isinstance(release.get("draft"), bool) or release.get("body") != notes
            or sorted(asset["name"] for asset in release.get("assets", [])) != sorted(ASSETS)):
        raise ValueError("existing release identity, channel, notes or assets differ")
    with tempfile.TemporaryDirectory(prefix="c300x-release-") as temporary:
        run("gh", "release", "download", tag, "--repo", repository, "--dir", temporary,
            *(arg for name in ASSETS for arg in ("--pattern", name)))
        if any((Path(temporary) / name).read_bytes() != (directory / name).read_bytes()
               for name in ASSETS):
            raise ValueError("existing release assets differ; refusing to replace them")
    if release["draft"]:
        verify_source_tag(repository, tag, commit)
        run("gh", "release", "edit", tag, "--repo", repository, "--draft=false",
            *(("--latest=false",) if prerelease else ()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--directory", type=Path, default=ROOT / ".release")
    args = parser.parse_args()
    try:
        publish(args.repo, args.tag, args.directory)
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as err:
        parser.exit(1, f"Release publication stopped: {err}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
