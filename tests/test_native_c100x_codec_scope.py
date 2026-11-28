"""C100X test-build codec policy through production CLI/core and HTTP paths."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"
STACK = (
    "<media>\n<enable_speex>1</enable_speex>\n<unrelated>keep</unrelated>\n</media>\n"
)
LINPHONE = (
    "[sound]\nrtp_io=1\nrtp_ptnum=110\nrtp_map=speex/8000/1\n"
    "[audio_codec_0]\nmime=PCMU\nrate=8000\nchannels=1\nenabled=0\n"
    "[audio_codec_1]\nmime=speex\nrate=8000\nchannels=1\nenabled=1\n"
)
APPLY_BLOCKED = "c100x_test_build_codec_apply_blocked"
RECOVERY_BLOCKED = "c100x_codec_recovery_requires_stock_speex_backup"


@pytest.fixture(scope="module", params=[False, True], ids=["host", "asan-ubsan"])
def codec_probe(request, tmp_path_factory):
    directory = tmp_path_factory.mktemp("codec-scope-build")
    binary = directory / "probe"
    marker = directory / "BtClass100"
    flags = (
        ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        if request.param
        else []
    )
    sources = [
        "audio_codec",
        "device_file",
        "device_file_sync",
        "device_detect",
        "http_audio_codec",
        "http_auth",
        "json_util",
        "json_parse",
        "string_util",
    ]
    result = subprocess.run(
        [
            "cc",
            "-std=c11",
            "-O2",
            "-g",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-D_DEFAULT_SOURCE",
            "-D_POSIX_C_SOURCE=200809L",
            *flags,
            f'-DC300X_C100X_DISPLAY_MARKER="{marker}"',
            "-ffunction-sections",
            "-fdata-sections",
            "-Wl,--gc-sections",
            "-Wl,--wrap=c300x_device_file_remount",
            "-Wl,--wrap=c300x_device_file_write",
            str(NATIVE / "test/audio_codec_scope_test.c"),
            *(str(NATIVE / f"src/{source}.c") for source in sources),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return binary, marker


@pytest.fixture
def lab(codec_probe, tmp_path):
    binary, marker = codec_probe
    stack, linphone, backup = (
        tmp_path / "stack.xml",
        tmp_path / "linphone.conf",
        tmp_path / "backup",
    )
    stack.write_text(STACK)
    linphone.write_text(LINPHONE)
    environment = {
        **os.environ,
        "C300X_AUDIO_STACK_OPEN": str(stack),
        "C300X_AUDIO_LINPHONE_CONF": str(linphone),
        "C300X_AUDIO_BACKUP_DIR": str(backup),
    }

    def run(action, transport="cli", model="C100X", running="speex"):
        if model == "C100X":
            marker.touch()
        else:
            marker.unlink(missing_ok=True)
        result = subprocess.run(
            [str(binary), transport, action, running],
            env=environment,
            capture_output=True,
            text=True,
            timeout=5,
        )
        lines = result.stdout.splitlines()
        assert lines, result.stderr
        code = int(lines.pop(0)) if transport == "http" else result.returncode
        return code, json.loads(lines[0]), json.loads(result.stderr)

    return run, stack, linphone, backup


def snapshot(directory):
    return {
        str(p.relative_to(directory)): (
            p.read_bytes(),
            p.stat().st_mtime_ns,
            p.stat().st_ino,
        )
        for p in directory.rglob("*")
        if p.is_file()
    }


@pytest.mark.parametrize("transport", ["cli", "http"])
@pytest.mark.parametrize("patched", [False, True])
def test_c100_apply_never_writes_or_reboots(lab, transport, patched):
    run, stack, _, _ = lab
    if patched:
        assert run("apply", model="C300X")[0] == 0
    before = snapshot(stack.parent)
    code, body, effects = run("apply", transport, running="speex")
    assert code == (403 if transport == "http" else 1)
    assert body.get("detail", body.get("error")) == APPLY_BLOCKED
    assert effects == {"remounts": 0, "writes": 0, "reboots": 0, "recorded": 0}
    assert snapshot(stack.parent) == before


@pytest.mark.parametrize("transport", ["cli", "http"])
def test_c100_codec_status_remains_read_only(lab, transport):
    run, stack, _, _ = lab
    before = snapshot(stack.parent)
    code, body, effects = run("status", transport)
    assert code == (200 if transport == "http" else 0)
    assert body["supported"] is True and body["state"] == "speex"
    assert effects == {"remounts": 0, "writes": 0, "reboots": 0, "recorded": 0}
    assert snapshot(stack.parent) == before


@pytest.mark.parametrize("transport", ["cli", "http", "remove"])
def test_c100_verified_recovery_preserves_unrelated_configuration(lab, transport):
    run, stack, linphone, _ = lab
    assert run("apply", model="C300X")[0] == 0
    stack.write_text(stack.read_text().replace("keep", "new-setting"))
    code, body, effects = run("restore", transport, running="pcmu")
    assert code == (200 if transport == "http" else 0)
    assert body["ok"] is True
    assert stack.read_text() == STACK.replace("keep", "new-setting")
    assert linphone.read_text() == LINPHONE
    assert effects["writes"] == 2 and effects["remounts"] == 2
    assert effects["reboots"] == (1 if transport == "http" else 0)


@pytest.mark.parametrize("transport", ["cli", "http", "remove"])
@pytest.mark.parametrize(
    "damage",
    [
        "missing_stack",
        "missing_linphone",
        "pcmu_stack",
        "pcmu_linphone",
        "payload",
        "incomplete",
    ],
)
def test_c100_ambiguous_recovery_does_not_mutate(lab, transport, damage):
    run, stack, _, backup = lab
    assert run("apply", model="C300X")[0] == 0
    sb, lb = backup / "stack_open.xml", backup / "linphone.conf"
    if damage.startswith("missing_"):
        (sb if damage == "missing_stack" else lb).unlink()
    elif damage == "pcmu_stack":
        sb.write_text(STACK.replace(">1<", ">0<"))
    elif damage == "pcmu_linphone":
        lb.write_text(LINPHONE.replace("speex/8000/1", "PCMU/8000/1"))
    elif damage == "payload":
        lb.write_text(LINPHONE.replace("rtp_ptnum=110", "rtp_ptnum=0"))
    else:
        lb.write_text(LINPHONE.replace("rtp_ptnum=110\n", ""))
    before = snapshot(stack.parent)
    code, body, effects = run("restore", transport, running="pcmu")
    assert code == (403 if transport == "http" else 1)
    assert body.get("detail", body.get("error")) == RECOVERY_BLOCKED
    assert effects == {"remounts": 0, "writes": 0, "reboots": 0, "recorded": 0}
    assert snapshot(stack.parent) == before


def test_unpatched_removal_is_noop_but_restore_needs_backups(lab):
    run, stack, _, _ = lab
    before = snapshot(stack.parent)
    assert run("restore")[1]["error"] == RECOVERY_BLOCKED
    assert run("restore", "remove")[0] == 0
    assert snapshot(stack.parent) == before


@pytest.mark.parametrize("transport", ["cli", "http"])
def test_c300_apply_and_restore_unchanged(lab, transport):
    run, stack, linphone, _ = lab
    for action, state, running in [
        ("apply", "pcmu", "speex"),
        ("restore", "speex", "pcmu"),
    ]:
        code, body, effects = run(action, transport, model="C300X", running=running)
        assert code == (200 if transport == "http" else 0)
        assert body.get("configured_state", body["state"]) == state
        assert effects["writes"] == 2 and effects["remounts"] == 2
        assert effects["reboots"] == (1 if transport == "http" else 0)
    assert stack.read_text() == STACK and linphone.read_text() == LINPHONE


def test_original_c100_firmware_recovery_round_trip(lab):
    from test_native_routing_firmware_restore import FIRMWARE_ROOT

    root = FIRMWARE_ROOT / "rootfs-c100x-1.5.8"
    if not root.is_dir():
        pytest.skip("original C100X 1.5.8 required")
    run, stack, linphone, _ = lab
    shutil.copy2(root / "home/bticino/cfg/stack_open.xml", stack)
    shutil.copy2(root / "etc/linphone.conf", linphone)
    originals = tuple(
        hashlib.sha256(path.read_bytes()).hexdigest() for path in (stack, linphone)
    )
    assert run("status")[1]["state"] == "speex"
    assert run("apply")[1]["error"] == APPLY_BLOCKED
    assert (
        run("apply", model="C300X")[0] == 0
    )  # Simulate an existing managed patch, on copies only.
    assert run("restore")[0] == 0
    assert (
        tuple(
            hashlib.sha256(path.read_bytes()).hexdigest() for path in (stack, linphone)
        )
        == originals
    )
