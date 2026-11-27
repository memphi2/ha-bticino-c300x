"""Door level and fine adjustment in the agent: gain curve, chip hook, software share."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native_agent"
# Synthetic stand-ins for the vendor stub and IP_PE.cr; the real pins stay in
# the source and are checked against the firmware images in the report only.
STUB = b'#!/bin/bash\ncase "$1" in\n*) ;;\nesac\nexit 1\n'
PROFILE = b"profile\n"
SOURCES = ("media_audio", "device_file", "device_file_sync", "root_mount", "sha256", "time_util")


def build_level_binary(binary: Path, *, sanitize: bool = False) -> Path:
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else []
    subprocess.run(
        ["cc", "-std=c11", "-O2", "-g", "-Wall", "-Wextra", "-Werror",
         "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L", *flags,
         f'-DSTOCK_HOOK_SHA256="{hashlib.sha256(STUB).hexdigest()}"',
         f'-DIP_PROFILE_SHA256="{hashlib.sha256(PROFILE).hexdigest()}"',
         str(NATIVE / "test/audio_level_test.c"),
         *(str(NATIVE / f"src/{name}.c") for name in SOURCES),
         "-pthread", "-o", str(binary)],
        check=True, capture_output=True, text=True, timeout=60,
    )
    return binary


def render_hook(level_binary: Path, steps: int) -> bytes:
    return subprocess.run(
        [str(level_binary), "render", str(steps)], capture_output=True, check=True, timeout=10,
    ).stdout


@pytest.fixture(scope="module", params=[False, True], ids=["host", "asan-ubsan"])
def level_binary(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_level_binary(tmp_path_factory.mktemp("audio-level") / "audio-level", sanitize=request.param)


CASES = ["gain", "gain_bounds", "chip", "level", "timing", "refresh"]


@pytest.mark.parametrize("case", CASES)
def test_gain_curve_chip_hook_and_software_share(level_binary: Path, tmp_path: Path, case: str) -> None:
    result = subprocess.run(
        [str(level_binary), str(tmp_path), case], capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "ok\n"


def _hook(level_binary: Path, steps: int, tmp_path: Path) -> Path:
    hook = tmp_path / "Audio_State.sh"
    hook.write_bytes(render_hook(level_binary, steps))
    hook.chmod(0o755)
    return hook


# The states of the vendor stub that load a profile with its own gain.
PROFILE_STATES = (
    "EN_AUDIO_BEEP", "EN_AUDIO_PASSTHR", "EN_AUDIO_PASSTHR_INT", "EN_AUDIO_IP", "EN_AUDIO_RINGING",
    "EN_AUDIO_RINGING_LOC", "EN_AUDIO_PLAY_LOC", "EN_AUDIO_PLAY_LOC_SCS", "EN_AUDIO_REC_SCS",
    "EN_AUDIO_REC_MIC",
)
SHELLS = {"sh": ["sh"], "bash": ["bash"], "busybox-ash": ["busybox", "ash"]}


@pytest.mark.parametrize("shell", sorted(SHELLS))
def test_hook_raises_only_the_app_state_and_puts_the_profile_value_back(
    level_binary: Path, tmp_path: Path, shell: str
) -> None:
    if shutil.which(SHELLS[shell][0]) is None:
        pytest.skip(f"{shell} missing")
    hook = _hook(level_binary, 3, tmp_path)
    log = tmp_path / "amixer.log"
    amixer = tmp_path / "amixer"
    mark = tmp_path / "raised"
    seen = tmp_path / "seen"
    # Also notes the mark as it is at each write.
    amixer.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{log}"\n'
        f'cat "{mark}" >> "{seen}" 2>/dev/null || echo none >> "{seen}"\n'
    )
    amixer.chmod(0o755)
    env = {**os.environ, "C300X_AMIXER": str(amixer), "C300X_SOUT_MARK": str(mark)}

    def run(state: str) -> list[str]:
        log.unlink(missing_ok=True)
        result = subprocess.run([*SHELLS[shell], str(hook), state], env=env, capture_output=True, timeout=10)
        # The HAL gets the stub's exit status for every state.
        assert result.returncode == 1
        return log.read_text().splitlines() if log.exists() else []

    assert run("EN_AUDIO_OFF") == []
    assert run("EN_AUDIO_IP_EU") == ["-q -c 0 cset name='ZL0 Sout Gain Volume' 14"]
    assert mark.read_text() == "14\n"
    # The mark was there, whole, before the gain went up, and nothing is left over.
    assert seen.read_text() == "14\n"
    assert sorted(path.name for path in tmp_path.iterdir() if path.name.startswith("raised")) == ["raised"]
    # No profile of its own: the value of IP_PE.cr comes back.
    assert run("EN_AUDIO_IP_IU") == ["-q -c 0 cset name='ZL0 Sout Gain Volume' 11"]
    assert not mark.exists()
    assert run("EN_AUDIO_IP_IU") == []
    run("EN_AUDIO_IP_EU")
    assert run("EN_AUDIO_OFF") == ["-q -c 0 cset name='ZL0 Sout Gain Volume' 11"]
    # A state with its own profile has its own value already: only the mark goes.
    run("EN_AUDIO_IP_EU")
    assert run("EN_AUDIO_RINGING") == []
    assert not mark.exists()
    assert run("EN_AUDIO_IP") == []
    # Every state the vendor stub lists with a profile of its own.
    for state in PROFILE_STATES:
        run("EN_AUDIO_IP_EU")
        assert run(state) == [], state
        assert not mark.exists()
    # Anything else, an empty argument included, never leaves the gain raised.
    for state in ("EN_AUDIO_FAKE", "EN_AUDIO_STBY", "", "garbage"):
        run("EN_AUDIO_IP_EU")
        assert run(state) == ["-q -c 0 cset name='ZL0 Sout Gain Volume' 11"], state
        assert not mark.exists()
        assert run(state) == [], state
    # A failed write leaves no mark: nothing counts as raised.
    amixer.write_text("#!/bin/sh\nexit 1\n")
    run("EN_AUDIO_IP_EU")
    assert not mark.exists()
    assert not (tmp_path / "raised.new").exists()
    # Without a mark the agent could not know: no raise then.
    amixer.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{log}"\n')
    env["C300X_SOUT_MARK"] = str(tmp_path / "missing" / "raised")
    assert run("EN_AUDIO_IP_EU") == []
