#!/usr/bin/env python3
"""Run the current Python coverage gate.

This is an aggregate repository floor, not proof of a Home Assistant tier.
The HA per-module and config-flow requirements are tracked separately.
"""

from __future__ import annotations

import subprocess
import sys

MINIMUM_COVERAGE = 95


def main() -> int:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--cov=custom_components/bticino_c300x",
            "--cov-report=term-missing:skip-covered",
            f"--cov-fail-under={MINIMUM_COVERAGE}",
            "-q",
        ],
        check=False,
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
