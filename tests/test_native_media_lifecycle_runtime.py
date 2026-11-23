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
        "config", "json_parse", "json_util", "string_util", "time_util", "video_rtsp", "sha256", "audio_codec", "device_file",
        "media_audio", "media_sip", "media_sip_io", "media_sip_dialog", "media_base64", "media_session_guard",
        "media_rtsp_auth", "media_rtsp_io", "media_rtsp_reader", "talkback_g711", "device_detect", "file_io",
    ]
    for name, dependencies in (
        ("media_lifecycle", sources),
        ("media_start_stop", sources),
        ("media_rtsp_auth", ["media_rtsp_auth", "media_base64", "string_util"]),
        ("media_rtsp_writer", ["time_util"]),
        ("media_rtsp_deadline", []),
        ("media_ring_stop", []),
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


def test_ring_receiver_stop_ownership(media_binaries):
    result = subprocess.run([str(media_binaries / "media_ring_stop")],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("case", [
    "response_after_rtp", "rtp_after_response", "audio_after_video", "framing", "timeouts", "partial_failure", "real_partial_recovery", "slow_reader", "stall_limit",
])
def test_rtsp_writer(media_binaries, case):
    result = subprocess.run([str(media_binaries / "media_rtsp_writer"), case],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("case", [
    "interrupt", "response_interrupt", "partial_interrupt", "short_writes",
    "partial_stall_frame", "partial_stall_response", "partial_stall_stall_limit",
    "partial_stall_epipe", "partial_stall_recover_fanout",
])
def test_rtsp_write_deadlines(media_binaries, case):
    result = subprocess.run([str(media_binaries / "media_rtsp_deadline"), case],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_stop_cancels_inflight_sip_setup(media_binaries):
    result = subprocess.run([str(media_binaries / "media_start_stop")],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("case", [
    "admission", "auth", "legacy", "pending_stop", "home_stop", "home_restart", "home_concurrent", "stalled_client", "target_ownership", "interleaved", "unauth_rejections", "unauth_lifetime", "unauth_trickle", "talkback_stop_race", "relay_ports", "read_timeout", "sip_join", "sip_renew",
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


def test_a_playing_ring_or_home_call_client_gets_the_advertised_timeout():
    """The SETUP answer promises the session timeout to every client.

    The read timeout used to follow ``media_started``, which is only set for
    an on-demand session. A ring or home-call client that sent nothing for
    30 seconds was closed, although it was told 180.
    """

    from pathlib import Path

    source = (Path(__file__).parents[1] / "native_agent/src/media_bridge.c").read_text()
    handler = source[source.index("handle_rtsp_client("):]
    call = handler[handler.index("c300x_rtsp_read_timeout("):][:240]
    assert "playing ? RTSP_IDLE_TIMEOUT_SECONDS : 0" in call
    assert "media_started" not in call
    play = handler[handler.index("media_started = !ring_session && !home_call_session;"):][:120]
    assert play.split(";")[1].strip() == "playing = true"
