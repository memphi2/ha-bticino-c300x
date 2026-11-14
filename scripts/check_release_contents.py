#!/usr/bin/env python3
"""Bind packaged sources and bundle metadata to the checked-out release.

Without --agent-binary this checks package consistency only, not the ARM
executable's origin. With it, expected bundle content comes from the supplied
build output, not the archive. The caller must independently select that output;
neither mode proves compiler provenance.
With --build-lock, executable bytes must also match the reviewer-approved
digest and current source inputs, even if --agent-binary came from a ZIP.
"""

from __future__ import annotations

import argparse
import subprocess
import tempfile
import zipfile
from pathlib import Path

from build_hacs_release import PACKAGE_METADATA
from native_build_lock import validate_archive
from stage_device_agent_bundle import ROOT, integration_version, stage_bundle


def validate_release_contents(
    zip_path: Path, *, agent_binary: Path | None = None, build_lock: Path | None = None,
) -> None:
    """Reject mismatched, missing, extra or duplicated archive files."""
    if build_lock is not None:
        validate_archive(zip_path, root=ROOT, lock_path=build_lock)
    component = ROOT / "custom_components/bticino_c300x"
    tracked = subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-files", "-z", "--", str(component)],
    ).decode().split("\0")
    expected = {
        (ROOT / name).relative_to(component).as_posix(): (ROOT / name).read_bytes()
        for name in tracked if name
    }
    expected.update({name: (ROOT / name).read_bytes() for name in PACKAGE_METADATA})
    with zipfile.ZipFile(zip_path) as archive, tempfile.TemporaryDirectory() as temporary:
        names = [entry.filename for entry in archive.infolist() if not entry.is_dir()]
        if len(names) != len(set(names)):
            raise ValueError("duplicate release archive entries")
        directory = Path(temporary)
        binary = agent_binary
        if binary is None:
            binary = directory / "agent"
            binary.write_bytes(archive.read("device_agent/armhf/c300x-agent-native"))
        staged = directory / "staged"
        stage_bundle(staged, version=integration_version(component),
                     skip_build=True, agent_binary=binary)
        if agent_binary is not None:
            name = "device_agent/armhf/c300x-agent-native"
            if archive.read(name) != (staged / name).read_bytes():
                raise ValueError("release agent differs from independently supplied build output")
        expected.update({path.relative_to(staged).as_posix(): path.read_bytes()
                         for path in staged.rglob("*") if path.is_file()})
        if set(names) != set(expected):
            raise ValueError("release archive file set differs from checkout")
        for name, content in expected.items():
            if archive.read(name) != content:
                raise ValueError(f"release archive content differs from checkout: {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip", type=Path)
    parser.add_argument(
        "--agent-binary", type=Path,
        help="Separately selected output to compare after stripping; ZIP-derived bytes also need --build-lock.",
    )
    parser.add_argument("--build-lock", type=Path,
                        help="Reviewed source-input and stripped-binary digest lock.")
    args = parser.parse_args()
    validate_release_contents(args.zip, agent_binary=args.agent_binary, build_lock=args.build_lock)


if __name__ == "__main__":
    main()
