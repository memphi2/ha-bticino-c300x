"""RTSP video starts at a keyframe: the keyframe group cache and the relay
that reads the station's stream during the on-demand takeover."""

import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"
BRIDGE_SOURCES = [
    "config", "json_parse", "json_util", "string_util", "time_util", "video_rtsp", "sha256", "audio_codec",
    "device_file", "media_audio", "audio_level", "audio_gain", "audio_chip", "media_sip", "media_sip_io",
    "media_sip_dialog", "media_base64",
    "media_session_guard", "media_rtsp_auth", "media_rtsp_io", "media_rtsp_reader", "talkback_g711",
    "device_detect", "device_file_sync", "file_io", "root_mount", "media_gop_cache",
]
CACHE_CASES = [
    "late_join", "cap", "age", "stale", "restart", "resume", "loss", "slow", "slow_burst", "two_sources", "malformed",
    "no_memory",
]


@pytest.fixture(scope="module", params=[False, True], ids=["host", "asan-ubsan"])
def binaries(request, tmp_path_factory):
    directory = tmp_path_factory.mktemp("media-video-start")
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if request.param else []
    for name, sources in (
        ("media_gop_cache", ["media_rtsp_io", "time_util"]),
        ("media_video_start", BRIDGE_SOURCES),
    ):
        result = subprocess.run(
            ["cc", "-std=c11", "-O2", "-g", "-Wall", "-Wextra", "-Werror",
             "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
             "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections", *flags,
             str(NATIVE / f"test/{name}_test.c"),
             *(str(NATIVE / f"src/{source}.c") for source in sources),
             "-pthread", "-ldl", "-o", str(directory / name)],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, result.stderr
    return directory


@pytest.mark.parametrize("case", CACHE_CASES)
def test_keyframe_group_cache(binaries, case):
    result = subprocess.run([str(binaries / "media_gop_cache"), case],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_clients_start_at_the_newest_keyframe_from_the_first_media_command(binaries):
    """The first IDR arrives during the takeover's waits and fills more than
    the device's socket buffer: the first client gets it whole, a later one
    the newest IDR from the cache, both with continuous numbering."""

    result = subprocess.run([str(binaries / "media_video_start")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
