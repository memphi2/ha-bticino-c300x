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
    "custom_components/bticino_c300x/agent_contracts",
    "custom_components/bticino_c300x/capabilities.py",
    "custom_components/bticino_c300x/config_schemas.py",
    "custom_components/bticino_c300x/dashboard_entities.py",
    "custom_components/bticino_c300x/dashboard_labels.py",
    "custom_components/bticino_c300x/data.py",
    "custom_components/bticino_c300x/discovery.py",
    "custom_components/bticino_c300x/event_payload.py",
    "custom_components/bticino_c300x/camera_media/rtsp_orchestrator.py",
    "custom_components/bticino_c300x/camera_media/rtsp_policy.py",
    "custom_components/bticino_c300x/camera_media/rtsp_url.py",
    "custom_components/bticino_c300x/camera_media/sdp.py",
    "custom_components/bticino_c300x/camera_media/state_machine.py",
    "custom_components/bticino_c300x/forwarding.py",
    "custom_components/bticino_c300x/media_status.py",
    "custom_components/bticino_c300x/memos.py",
    "custom_components/bticino_c300x/use_cases/common.py",
    "custom_components/bticino_c300x/use_cases/device_actions.py",
    "custom_components/bticino_c300x/use_cases/doorbell_video.py",
    "custom_components/bticino_c300x/use_cases/home_call.py",
    "custom_components/bticino_c300x/use_cases/maintenance.py",
    "custom_components/bticino_c300x/use_cases/memos.py",
    "custom_components/bticino_c300x/use_cases/messages.py",
    "custom_components/bticino_c300x/use_cases/ring_analysis.py",
    "custom_components/bticino_c300x/use_cases/ring_call.py",
    "custom_components/bticino_c300x/use_cases/ring_capture.py",
    "custom_components/bticino_c300x/value_parsing.py",
    "custom_components/bticino_c300x/video.py",
    "custom_components/bticino_c300x/video_messages.py",
    "scripts/check_quality_scale.py",
    "scripts/check_coverage.py",
    "scripts/check_repo.py",
    "scripts/check_typing.py",
    "scripts/check_validate.py",
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
