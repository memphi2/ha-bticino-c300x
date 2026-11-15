"""Exercise production recording with an H.264 stream joined between keyframes."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from unittest.mock import patch


def _run(*command: str) -> str:
    return subprocess.run(
        command, check=True, capture_output=True, text=True, timeout=20,
    ).stdout


def _prepare(directory: Path) -> Path:
    directory.mkdir()
    complete = directory / "complete.h264"
    _run(
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
        "testsrc2=size=400x288:rate=10:duration=5", "-c:v", "libx264",
        "-g", "20", "-keyint_min", "20", "-sc_threshold", "0", "-crf", "18",
        "-x264-params", "repeat-headers=1", "-f", "h264", str(complete),
    )
    packets = json.loads(_run(
        "ffprobe", "-v", "error", "-show_packets", "-show_entries",
        "packet=pos,size,flags", "-of", "json", str(complete),
    ))["packets"]
    start = int(packets[1]["pos"])
    next_keyframe = next(int(p["pos"]) for p in packets[1:] if "K" in p["flags"])
    if "K" in packets[1]["flags"] or next_keyframe - start <= 32768:
        raise RuntimeError("Late-header fixture does not exceed the old probe budget")
    late = directory / "late-headers.h264"
    late.write_bytes(complete.read_bytes()[start:])
    return late


async def async_check_capture_startup(directory: Path) -> None:
    """Replay late parameter sets without opening a network or device connection."""
    from custom_components.bticino_c300x import ring_capture

    late = await asyncio.to_thread(_prepare, directory)
    target = directory / "recording.mp4"
    rtsp_url = "rtsp://offline.invalid/doorbell-recorder"
    execute = ring_capture._async_run_ffmpeg_command

    async def replay_transport(command: list[str], **kwargs):
        if command[0] == "ffmpeg" and rtsp_url in command:
            # Only the transport changes. Production probing, muxing, duration,
            # subprocess deadlines and JPEG extraction all execute unchanged.
            command = command.copy()
            for option in ("-rtsp_transport", "-timeout"):
                index = command.index(option)
                del command[index:index + 2]
            command[command.index(rtsp_url)] = str(late)
            index = command.index("-i")
            command[index:index] = ["-r", "10", "-f", "h264"]
        return await execute(command, **kwargs)

    with patch.object(ring_capture, "_async_run_ffmpeg_command", replay_transport):
        await ring_capture._async_run_ffmpeg(
            rtsp_url, target, work_dir=directory, duration_seconds=3, include_audio=False,
        )
    stream = json.loads(await asyncio.to_thread(_run,
        "ffprobe", "-v", "error", "-show_streams", "-of", "json", str(target),
    ))["streams"][0]
    if (stream["codec_name"], stream["width"], stream["height"]) != ("h264", 400, 288):
        raise RuntimeError("Late-header recording has incorrect video parameters")
    for index in (1, 2, 3):
        frame = directory / f"frame_{index:02}.jpg"
        image = json.loads(await asyncio.to_thread(_run,
            "ffprobe", "-v", "error", "-show_streams", "-of", "json", str(frame),
        ))["streams"][0]
        if (image["width"], image["height"], image["color_range"]) != (400, 288, "pc"):
            raise RuntimeError("Late-header recording did not produce valid full-range JPEGs")
