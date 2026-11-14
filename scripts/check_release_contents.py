#!/usr/bin/env python3
"""Bind packaged sources and bundle metadata to the checked-out release.

This checks content, not compiler provenance: the ARM binary still needs the
trusted build and commit checks enforced by the release workflow.
"""

from __future__ import annotations

import argparse
import subprocess
import tempfile
import zipfile
from pathlib import Path

from build_hacs_release import PACKAGE_METADATA
from stage_device_agent_bundle import ROOT, integration_version, stage_bundle


def validate_release_contents(zip_path: Path) -> None:
    """Reject mismatched, missing, extra or duplicated archive files."""
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
        binary = directory / "agent"
        binary.write_bytes(archive.read("device_agent/armhf/c300x-agent-native"))
        staged = directory / "staged"
        stage_bundle(staged, version=integration_version(component),
                     skip_build=True, agent_binary=binary)
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
    validate_release_contents(parser.parse_args().zip)


if __name__ == "__main__":
    main()
