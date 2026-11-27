"""Device-captured ring sequences, replayed against the real agent code.

The binary runs the agent's event loop, video state and media bridge with a
fake flexisip/station on loopback and fake bus frames; see
native_agent/test/ring_replay_test.c.
"""

import hashlib
import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"
WRAPPED = (
    "c300x_device_user_media_identity", "c300x_device_media_takeover",
    "c300x_device_media_start", "c300x_device_media_stop",
    "c300x_audio_codec_device_is_pcmu", "c300x_monotonic_ms",
    "dlopen", "dlsym", "dlclose", "bind", "c300x_mqtt_publish_event",
    "c300x_video_bridge_station_busy", "c300x_media_gop_reset", "c300x_media_sip_send_bye",
)
CASES = {
    "display_answer": 0, "display_answer_end_lost": 1, "unanswered": 0, "ha_answer": 0, "two_units": 0,
    "lifecycle_unanswered": 0, "lifecycle_ha_answer_ha_hangup": 0,
    "lifecycle_station_answer_station_hangup": 0, "lifecycle_ha_answer_station_hangup": 0,
    "lifecycle_ondemand_view": 1, "ondemand_units": 4, "refused_answer_then_station": 0,
    "call_id_lengths": 0, "boot_id_at_start": 0,
    "display_answer_without_preview": 0, "app_answer_end_frame_first": 0,
    "display_answer_end_lost_call": 0, "answer_before_caller": 0,
    "abandoned_answer_then_station": 0, "view_is_current": 1,
    "station_busy_bus_end": 2, "station_busy_timeout": 2,
    "station_freed_before_486": 2, "station_freed_after_486": 2,
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


# One ring at a one-unit station (bus ring, a ring copy, the caller frame,
# HA's answer, the station's frames, an unlock, the station's BYE): the
# events without the call fields the agent adds since 3.1.0. Produced by
# running the same case on work/3.0.0 (659b32a9).
SINGLE_UNIT_TYPES_3_0_0 = [
    "doorbell.pressed", "doorbell.view_requested", "doorbell.view_requested",
    "door_unlock.started", "door_unlock.ended", "doorbell.media.closed",
]
SINGLE_UNIT_SHA256_3_0_0 = "3a01987cc2670aae10c0a63a66bee1677941c8390e72e87acf332801686574a6"


def test_a_one_unit_station_gets_the_events_of_3_0_0(replay_binary):
    result = subprocess.run([str(replay_binary), "single_unit_as_3_0_0"], capture_output=True, text=True,
                            timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    lines = [line for line in result.stdout.splitlines() if line.startswith("event ")]
    assert [line.split(" ", 2)[1] for line in lines] == SINGLE_UNIT_TYPES_3_0_0
    digest = hashlib.sha256("".join(line + "\n" for line in lines).encode()).hexdigest()
    assert digest == SINGLE_UNIT_SHA256_3_0_0, "\n".join(lines)
