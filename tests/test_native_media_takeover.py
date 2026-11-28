"""The on-demand start waits for the station's stream, not for fixed sleeps.

The real bridge and device_media.c run against a fake media service that
answers the client adds like bt_av_media and streams 250 ms after the add that
took effect; see native_agent/test/media_takeover_test.c.
"""

import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"
SOURCES = [
    "config", "json_parse", "json_util", "string_util", "time_util", "video_rtsp", "sha256", "audio_codec",
    "device_file", "media_audio", "audio_level", "audio_gain", "audio_chip", "media_sip", "media_sip_io",
    "media_sip_dialog", "media_base64",
    "media_session_guard", "media_rtsp_auth", "media_rtsp_io", "media_rtsp_reader", "talkback_g711",
    "device_detect", "device_file_sync", "file_io", "root_mount", "media_gop_cache", "device_media", "media_unit",
    "station_archive",
]
SCENARIOS = {"stream-after-first-add": 0, "first-add-cleared": 1, "first-add-refused": 2, "no-stream": 3}


@pytest.fixture(scope="module", params=[False, True], ids=["host", "asan-ubsan"])
def binary(request, tmp_path_factory):
    path = tmp_path_factory.mktemp("media-takeover") / "media_takeover"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if request.param else []
    result = subprocess.run(
        ["cc", "-std=c11", "-O2", "-g", "-Wall", "-Wextra", "-Werror",
         "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
         "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
         "-Wl,--wrap=connect", "-Wl,--wrap=bind", *flags,
         str(NATIVE / "test/media_takeover_test.c"),
         *(str(NATIVE / f"src/{source}.c") for source in SOURCES),
         "-pthread", "-ldl", "-o", str(path)],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return path


@pytest.mark.parametrize("scenario", SCENARIOS.values(), ids=SCENARIOS.keys())
def test_play_follows_the_station_stream(binary, scenario):
    result = subprocess.run([str(binary), str(scenario)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
