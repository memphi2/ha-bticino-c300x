"""Production RTSP authorization and home-call ownership, without device I/O."""

import select
import shutil
import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


@pytest.fixture(scope="module", params=[False, True], ids=["host", "asan-ubsan"])
def media_binaries(request, tmp_path_factory):
    directory = tmp_path_factory.mktemp("media-lifecycle")
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if request.param else []
    sources = [
        "config", "json_parse", "json_util", "string_util", "time_util", "video_rtsp", "sha256", "audio_codec",
        "media_audio", "media_sip", "media_sip_io", "media_base64", "media_session_guard",
        "media_rtsp_auth", "media_rtsp_io",
    ]
    for name, dependencies in (
        ("media_lifecycle", sources),
        ("media_start_stop", sources),
        ("media_rtsp_auth", ["media_rtsp_auth", "media_base64", "string_util"]),
    ):
        result = subprocess.run(
            ["cc", "-std=c11", "-O2", "-g", "-Wall", "-Wextra", "-Werror",
             "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
             "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections", *flags,
             str(NATIVE / f"test/{name}_test.c"),
             *(str(NATIVE / f"src/{source}.c") for source in dependencies),
             "-pthread", "-ldl", "-o", str(directory / name)],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, result.stderr
    return directory


def test_rtsp_credential_validation(media_binaries):
    result = subprocess.run([str(media_binaries / "media_rtsp_auth")],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_stop_cancels_inflight_sip_setup(media_binaries):
    result = subprocess.run([str(media_binaries / "media_start_stop")],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("case", [
    "auth", "legacy", "pending_stop", "home_stop", "home_restart", "home_concurrent", "stalled_client",
])
def test_media_lifecycle(media_binaries, case):
    result = subprocess.run([str(media_binaries / "media_lifecycle"), case],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("password,expected_plays", [("pass", 1), ("wrong", 0)])
def test_ffprobe_basic_challenge(media_binaries, password, expected_plays):
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        pytest.skip("FFmpeg client not installed")
    server = subprocess.Popen(
        [str(media_binaries / "media_lifecycle"), "serve"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        assert select.select([server.stdout], [], [], 5)[0], "RTSP listener did not start"
        port = int(server.stdout.readline())
        probe = subprocess.Popen(
            [ffprobe, "-loglevel", "trace", "-rtsp_transport", "tcp",
             "-analyzeduration", "1000", "-probesize", "32",
             f"rtsp://user:{password}@127.0.0.1:{port}/doorbell-video"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            _, log = probe.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            probe.kill()
            _, log = probe.communicate(timeout=3)
        assert b"401 Unauthorized" in log
        output, errors = server.communicate(b"q", timeout=5)
        assert server.returncode == 0, errors.decode()
        assert f"plays={expected_plays}".encode() in output
    finally:
        if server.poll() is None:
            server.kill()
            server.communicate(timeout=5)
