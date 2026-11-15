#!/usr/bin/env python3
"""Check native media tools and event contracts inside the selected HA image."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def write(message: str) -> None:
    sys.stdout.write(f"{message}\n")
    sys.stdout.flush()


def run(*command: str) -> str:
    return subprocess.run(
        command, check=True, capture_output=True, text=True, timeout=30
    ).stdout


async def check_frames(directory: Path) -> None:
    from custom_components.bticino_c300x.ring_capture import (
        _async_extract_capture_frames,
    )

    for name, settings in (
        ("unknown", []),
        ("limited", ["-color_range", "tv", "-colorspace", "bt709",
                     "-color_primaries", "bt709", "-color_trc", "bt709"]),
        ("full", ["-vf", "scale=out_range=full", "-color_range", "pc"]),
    ):
        clip = directory / f"{name}.mp4"
        run("ffmpeg", "-v", "error", "-f", "lavfi", "-i",
            "testsrc2=size=400x288:rate=10:duration=3", "-c:v", "libx264",
            "-pix_fmt", "yuv420p", *settings, str(clip))
        output = directory / name
        output.mkdir()
        await _async_extract_capture_frames(clip, output, duration_seconds=3)
        frames = list(output.glob("*.jpg"))
        if len(frames) != 3:
            raise RuntimeError(f"{name}: expected 3 JPEG frames, got {len(frames)}")
        for frame in frames:
            stream = json.loads(run(
                "ffprobe", "-v", "error", "-show_streams", "-of", "json", str(frame)
            ))["streams"][0]
            if (stream["width"], stream["height"], stream["color_range"]) != (400, 288, "pc"):
                raise RuntimeError(f"{name}: unexpected JPEG format: {stream}")
        write(f"{name}: 3 full-range JPEG frames")


def check_events() -> None:
    from custom_components.bticino_c300x.event import (
        C300XDeviceAgentEventEntity,
        C300XDoorbellEventEntity,
    )

    entry = SimpleNamespace(entry_id="container-test", title="C300X", data={}, options={},
                            runtime_data=SimpleNamespace(agent_info={}, capabilities={}))
    for cls, expected, key in (
        (C300XDoorbellEventEntity, "ring", "doorbell_pressed"),
        (C300XDeviceAgentEventEntity, "door_unlock_started", "door_unlock_started"),
    ):
        entity = cls(entry) if cls is C300XDoorbellEventEntity else cls(entry, [key])
        entity.hass = SimpleNamespace(config=SimpleNamespace(language="en"))
        payload = {"entry_id": entry.entry_id, "event_key": key,
                   "event_type": "Display label", "event_at": "2026-01-01T00:00:00Z"}
        # Only state publication is replaced; HA's event processing stays real.
        with patch.object(entity, "async_write_ha_state"):
            entity._handle_agent_event(SimpleNamespace(data=payload))
        if entity.state_attributes["event_type"] != expected:
            raise RuntimeError(f"{cls.__name__}: technical event type overwritten")
        write(f"{cls.__name__}: event_type={expected}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-ha", required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    from homeassistant.const import __version__

    if __version__ != args.expect_ha:
        raise RuntimeError(f"Expected HA {args.expect_ha}, running {__version__}")
    write(f"Home Assistant {__version__}")
    write(run("ffmpeg", "-version"))
    check_events()
    with tempfile.TemporaryDirectory(prefix="c300x-container-test-") as temporary:
        asyncio.run(check_frames(Path(temporary)))
        from scripts.check_capture_startup import async_check_capture_startup

        asyncio.run(async_check_capture_startup(Path(temporary) / "late-headers"))
        write("Late H.264 headers: MP4 and 3 full-range JPEG frames")
    write("HA container runtime checks passed")


if __name__ == "__main__":
    main()
