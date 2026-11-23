"""Read-only C100X HAL evidence; hardware and command calls are intercepted."""

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest
from test_native_routing_firmware_restore import FIRMWARE_ROOT

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = FIRMWARE_ROOT / "rootfs-c100x-1.5.8"
HAL = FIRMWARE / "home/bticino/lib/liblghal.so.0.0"
HAL_HASH = "f2f4ff4826f01ea84e60a3d98a4f779724f5fd315320d64d6bf1261b44a3947b"


@pytest.fixture(scope="module")
def hal_probe(tmp_path_factory):
    if not HAL.exists() or not all(shutil.which(t) for t in ("qemu-arm", "arm-linux-gnueabihf-gcc")):
        pytest.skip("original C100X 1.5.8 and ARM/QEMU tools required")
    assert hashlib.sha256(HAL.read_bytes()).hexdigest() == HAL_HASH
    binary = tmp_path_factory.mktemp("c100x-audio-hal") / "probe"
    subprocess.run([
        "arm-linux-gnueabihf-gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
        "-D_DEFAULT_SOURCE", "-D_TIME_BITS=32", "-Wl,--export-dynamic", "-nostartfiles",
        str(ROOT / "native_agent/test/c100x_audio_hal_probe.c"),
        str(ROOT / "native_agent/src/arm_start.S"),
        f"-Wl,-rpath-link,{FIRMWARE}/lib", f"-L{FIRMWARE}/lib",
        "-l:libdl.so.2", "-l:libc.so.6", "-l:ld-linux-armhf.so.3", "-o", str(binary),
    ], check=True, capture_output=True, text=True)

    def run(action, state, value):
        result = subprocess.run(["qemu-arm", "-L", str(FIRMWARE), str(binary), str(HAL),
                                 action, str(state), str(value)],
                                check=True, capture_output=True, text=True, timeout=10)
        return result.stdout.splitlines()

    return run


def test_local_ring_state_and_repeated_request(hal_probe):
    assert hal_probe("state", 0, 9) == [
        "mixer:Audio_State:7:2",
        "command:/usr/local/bin/Audio_State.sh EN_AUDIO_RINGING_LOC", "result:0",
    ]
    assert hal_probe("state", 7, 9) == ["result:0"]


def test_off_mutes_both_directions_before_releasing_state(hal_probe):
    assert hal_probe("state", 7, 0) == [
        "mixer:MUTE SOUT:1:1", "mixer:MUTE ROUT:1:1", "mixer:Audio_State:0:2",
        "command:/usr/local/bin/Audio_State.sh EN_AUDIO_OFF", "result:0",
    ]


@pytest.mark.parametrize("active_state", [4, 5])
def test_local_ring_request_overwrites_active_ip_not_an_ownership_check(hal_probe, active_state):
    assert hal_probe("state", active_state, 9) == [
        "mixer:Audio_State:7:2",
        "command:/usr/local/bin/Audio_State.sh EN_AUDIO_RINGING_LOC", "result:0",
    ]


@pytest.mark.parametrize("active_state", [4, 5])
def test_off_request_would_mute_an_active_ip_call(hal_probe, active_state):
    assert hal_probe("state", active_state, 0) == [
        "mixer:MUTE SOUT:1:1", "mixer:MUTE ROUT:1:1", "mixer:Audio_State:0:2",
        "command:/usr/local/bin/Audio_State.sh EN_AUDIO_OFF", "result:0",
    ]


def test_standby_is_a_distinct_end_state_not_unconditional_off(hal_probe):
    assert hal_probe("state", 7, 15) == [
        "mixer:Audio_State:8:2",
        "command:/usr/local/bin/Audio_State.sh EN_AUDIO_STBY", "result:0",
    ]


def test_legacy_memo_play_is_not_a_c100x_profile(hal_probe):
    assert hal_probe("state", 0, 1) == [
        "command:/usr/local/bin/Audio_State.sh FAKE", "result:0",
    ]


@pytest.mark.parametrize("enable,state,profile", [
    (5, 2, "PASSTHR"), (6, 6, "RINGING"), (7, 3, "PASSTHR_INT"),
    (11, 1, "BEEP"), (12, 4, "IP"), (14, 5, "IP_EU"), (15, 8, "STBY"),
])
def test_distinct_vendor_call_profiles(hal_probe, enable, state, profile):
    assert hal_probe("state", 0, enable) == [
        f"mixer:Audio_State:{state}:2",
        f"command:/usr/local/bin/Audio_State.sh EN_AUDIO_{profile}", "result:0",
    ]


def test_shark_play_volume_uses_dac2_and_aec_not_c300x_amplifier(hal_probe):
    assert hal_probe("volume", 7, 25) == [
        "mixer:DAC2 P ATT:2:2", "mixer:DAC2 M ATT:0:2",
        "mixer:AEC ROUT GAIN Volume:48:2", "mixer:MUTE SOUT:0:1",
        "mixer:MUTE ROUT:0:1", "result:0",
    ]


def test_original_configuration_contract():
    if not HAL.exists():
        pytest.skip("original C100X 1.5.8 required")
    import configparser
    import wave
    from xml.etree import ElementTree

    config = configparser.ConfigParser()
    config.read(FIRMWARE / "etc/linphone.conf")
    assert config["sound"]["rtp_map"] == "speex/8000/1"
    assert config["sound"]["rtp_ptnum"] == "110"
    assert config["audio_codec_0"]["enabled"] == "0"
    assert config["audio_codec_1"]["enabled"] == "1"
    tree = ElementTree.parse(FIRMWARE / "home/bticino/cfg/stack_open.xml")
    assert tree.findtext(".//bt_av_media/enable_speex") == "1"
    assert tree.findtext(".//bt_av_media/sampling_rate") == "16000"
    with wave.open(str(FIRMWARE / "home/bticino/ringtones/ring1.wav")) as sound:
        assert (sound.getframerate(), sound.getnchannels(), sound.getsampwidth()) == (16000, 2, 2)


def test_production_codec_with_original_arm_speex(tmp_path):
    library = FIRMWARE / "usr/lib/libspeex.so.1.5.1"
    if not library.exists() or not all(shutil.which(t) for t in ("qemu-arm", "arm-linux-gnueabihf-gcc")):
        pytest.skip("original C100X 1.5.8 and ARM/QEMU tools required")
    assert hashlib.sha256(library.read_bytes()).hexdigest() == (
        "5ff0a400fa72e0bd5038f65e85c8f4a7536e620001df846daa4de5027ca7de3a"
    )
    binary = tmp_path / "speex-probe"
    subprocess.run([
        "arm-linux-gnueabihf-gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
        "-D_DEFAULT_SOURCE", "-D_TIME_BITS=32", "-nostartfiles",
        "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
        str(ROOT / "native_agent/test/c100x_speex_probe.c"),
        str(ROOT / "native_agent/src/arm_start.S"),
        f"-Wl,-rpath-link,{FIRMWARE}/lib", f"-L{FIRMWARE}/lib",
        "-l:libpthread.so.0", "-l:libdl.so.2", "-l:libc.so.6", "-l:ld-linux-armhf.so.3",
        "-o", str(binary),
    ], check=True, capture_output=True, text=True, timeout=30)
    result = subprocess.run([
        "qemu-arm", "-L", str(FIRMWARE), "-E", f"LD_LIBRARY_PATH={FIRMWARE}/usr/lib",
        str(binary),
    ], check=True, capture_output=True, text=True, timeout=10)
    assert result.stdout.strip() == "speex/8000: 20 production encode/decode frames, 160 samples each"
