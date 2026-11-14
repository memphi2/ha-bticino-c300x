#!/usr/bin/env python3
"""Resolve one stable HA target before pip can backtrack to an older release."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
PYPI_URL = "https://pypi.org/pypi/homeassistant/json"


def stable_version(value: str) -> tuple[int, ...]:
    if not re.fullmatch(r"20[0-9]{2}\.(?:[1-9]|1[0-2])\.[0-9]+", value):
        raise ValueError(f"Not a stable Home Assistant version: {value!r}")
    return tuple(map(int, value.split(".")))


def latest_stable(data: dict, minimum: str) -> str:
    candidates = []
    for version, files in data["releases"].items():
        try:
            parsed = stable_version(version)
        except ValueError:
            continue
        if parsed >= stable_version(minimum) and any(
            not item.get("yanked", False) for item in files
        ):
            candidates.append((parsed, version))
    if not candidates:
        raise ValueError("PyPI returned no supported, non-yanked stable HA release")
    return max(candidates)[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=("min-ha", "current-ha"))
    args = parser.parse_args()
    config = json.loads((ROOT / "project-versions.json").read_text(encoding="utf-8"))
    version = config["min_homeassistant"]
    stable_version(version)
    if args.target == "current-ha":
        with urlopen(PYPI_URL, timeout=30) as response:
            version = latest_stable(json.load(response), version)
    sys.stdout.write(f"{args.target}: Home Assistant {version}\n")
    sys.stdout.flush()
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"version={version}\n")
            if args.target == "current-ha":
                stream.write(f"current_ha={version}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
