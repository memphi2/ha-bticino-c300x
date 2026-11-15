"""Regression for recording a ring whose H.264 parameter sets arrive later."""

import asyncio
import shutil

import pytest

from scripts.check_capture_startup import async_check_capture_startup


def test_recording_waits_for_late_h264_headers_and_extracts_frames(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg tools not installed")
    asyncio.run(async_check_capture_startup(tmp_path / "late-headers"))
