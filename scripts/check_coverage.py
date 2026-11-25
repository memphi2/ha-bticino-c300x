#!/usr/bin/env python3
"""Run the current Python coverage gate.

This is an aggregate repository floor, not proof of a Home Assistant tier.
The HA per-module and config-flow requirements are tracked separately.

The suite runs on one pytest-xdist worker per logical CPU; most of its time is
spent waiting on agent processes, shell scripts and emulators, not on the
CPU. PYTEST_XDIST_AUTO_NUM_WORKERS sets another worker count, for example
on a machine that other jobs share.
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
            "--numprocesses=logical",
            # Work stealing keeps the long shell and sanitizer files from
            # leaving one worker running alone at the end.
            "--dist=worksteal",
            "--cov=custom_components/bticino_c300x",
            "--cov-report=term-missing:skip-covered",
            f"--cov-fail-under={MINIMUM_COVERAGE}",
            "-q",
        ],
        check=False,
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
