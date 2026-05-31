#!/usr/bin/env python3
"""Run the current strict typing gate.

The gate starts with pure helper modules and expands as HA-facing modules get
fixture-backed tests and typed stubs.
"""

from __future__ import annotations

import subprocess
import sys

STRICT_TARGETS = (
    "custom_components/bticino_c300x/action.py",
    "custom_components/bticino_c300x/capabilities.py",
    "custom_components/bticino_c300x/data.py",
    "custom_components/bticino_c300x/discovery.py",
    "custom_components/bticino_c300x/event_payload.py",
    "custom_components/bticino_c300x/memos.py",
    "custom_components/bticino_c300x/video.py",
    "custom_components/bticino_c300x/video_messages.py",
    "scripts/check_quality_scale.py",
    "scripts/check_coverage.py",
    "scripts/check_repo.py",
    "scripts/check_typing.py",
)


def main() -> int:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--strict",
            "--ignore-missing-imports",
            "--follow-imports=silent",
            *STRICT_TARGETS,
        ],
        check=False,
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
