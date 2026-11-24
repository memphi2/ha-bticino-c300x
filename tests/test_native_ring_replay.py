"""Device-captured ring sequences, replayed against the real agent code.

The binary runs the agent's event loop, video state and media bridge with a
fake flexisip/station on loopback and fake bus frames; see
native_agent/test/ring_replay_test.c.
"""

import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"
WRAPPED = (
    "c300x_device_user_media_identity", "c300x_device_media_takeover",
    "c300x_device_media_start", "c300x_device_media_stop",
    "c300x_audio_codec_device_is_pcmu", "c300x_monotonic_ms",
    "dlopen", "dlsym", "dlclose", "bind", "c300x_mqtt_publish_event",
)
CASES = {
    "display_answer": 0, "unanswered": 0, "ha_answer": 0,
    "station_busy_bus_end": 2, "station_busy_timeout": 2,
}


@pytest.fixture(scope="module", params=[False, True], ids=["host", "asan-ubsan"])
def replay_binary(request, tmp_path_factory):
    sources = sorted(
        str(path) for path in (NATIVE / "src").glob("*.c")
        if path.name not in {"http.c", "main.c"}
    )
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if request.param else []
    binary = tmp_path_factory.mktemp("ring-replay") / "ring-replay"
    build = subprocess.run(
        [
            "cc", "-std=c11", "-O1", "-g",
            "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
            "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
            *(f"-Wl,--wrap={name}" for name in WRAPPED), *flags,
            str(NATIVE / "test/ring_replay_test.c"), *sources,
            "-pthread", "-ldl", "-o", str(binary),
        ],
        capture_output=True, text=True, timeout=180,
    )
    assert build.returncode == 0, build.stderr
    return binary


@pytest.mark.parametrize(("case", "invites"), CASES.items())
def test_ring_replay(replay_binary, case, invites):
    result = subprocess.run([str(replay_binary), case], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"ondemand_invites={invites}" in result.stdout
