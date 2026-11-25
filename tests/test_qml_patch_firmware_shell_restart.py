"""The GUI restart paths of qml_patch.sh under the firmware's own shells.

The station runs qml_patch.sh with its /bin/sh, bash in POSIX mode: 5.1.16 on
3.0.6, 4.4.12 on 1.7.19. BusyBox sh 1.35.0 of 3.0.6 is run too. BusyBox 1.24.1
of 1.7.19 is left out: it has no `command` builtin, so 2.9.1's restart
(`command -v killall`) cannot run under it, and nothing on the station runs
the script with it. The original ARM shells run under qemu-arm; the commands
they start (pidof/killall stand-ins, flock, setsid, sleep) are host programs.
The restart worker is started through the same firmware shell.
"""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path

import pytest

from tests.test_qml_patch_gui_reload import (
    OverlayStation,
    Station,
    _kinds,
    _restart_pause,
    _settled,
    _starts,
    _wait_for,
    watched_restart,
)
from tests.test_qml_patch_qt5_overlay import programs as programs
from tests.test_qml_patch_script import SCRIPT

SHELLS = {
    "3.0.6-bash": ("C300X_QT5_FIRMWARE", "bin/bash.bash"),
    "3.0.6-busybox": ("C300X_QT5_FIRMWARE", "bin/busybox.nosuid"),
    "1.7.19-bash": ("C300X_DEVICE_SYSROOT", "bin/bash.bash"),
}


def _firmware_shell(tmp_path: Path, name: str) -> Path:
    variable, binary = SHELLS[name]
    value = os.environ.get(variable)
    if not value:
        pytest.skip(f"{variable} (private firmware root) not supplied")
    root = Path(value)
    # Only the libraries: qemu would otherwise read the root's empty /proc.
    sysroot = tmp_path / f"sysroot-{name}"
    sysroot.mkdir()
    for part in ("lib", "usr"):
        (sysroot / part).symlink_to(root / part)
    launcher = tmp_path / f"sh-{name}"
    launcher.write_text(
        "#!/bin/sh\n"
        f'exec qemu-arm -L "{sysroot}" -E "LD_LIBRARY_PATH={root}/lib:{root}/usr/lib" '
        f'-0 sh "{root / binary}" "$@"\n'
    )
    launcher.chmod(0o755)
    return launcher


def _run(station: Station, shell: Path, action: str, env: dict[str, str]) -> subprocess.Popen[str]:
    return subprocess.Popen([str(shell), str(SCRIPT), action],
                            env={**env, "C300X_QML_SHELL": str(shell)}, start_new_session=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


@pytest.fixture(params=sorted(SHELLS))
def shell(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    return _firmware_shell(tmp_path, request.param)


@pytest.fixture
def station(tmp_path: Path):
    result = Station(tmp_path)
    yield result
    result.stop_all()


def test_a_qt5_restart_stops_the_old_display_before_the_new_one(station: Station, shell: Path) -> None:
    station.boot(C300X_TEST_TEARDOWN="1")
    process = _run(station, shell, "reload", station.script_env())
    _, stderr = process.communicate(timeout=120)
    assert process.returncode == 0, stderr
    assert len(_settled(station)) == 1
    assert _kinds(station) == ["wrapper", "start", "end", "wrapper", "start"]


@pytest.mark.parametrize("phase", ["stop", "verify"])
def test_a_job_kill_during_a_qt5_restart_still_ends_with_one_display(
    station: Station, shell: Path, phase: str
) -> None:
    station.boot(C300X_TEST_TEARDOWN="1")
    process = _run(station, shell, "reload", station.script_env())
    assert _wait_for(lambda: station.phase() == phase, 60), station.phase()
    os.killpg(process.pid, signal.SIGKILL)
    process.communicate(timeout=30)
    assert len(_settled(station)) == 1
    assert _kinds(station).count("wrapper") == 2


def test_the_qt4_restart_of_2_9_1(station: Station, shell: Path) -> None:
    station.boot()
    process = _run(station, shell, "reload", station.script_env(qt5=False))
    _, stderr = process.communicate(timeout=120)
    assert process.returncode == 0, stderr
    assert station.calls() == ["killall BtClass"]
    assert _wait_for(lambda: len(station.running()) == 1)
    assert _kinds(station) == ["wrapper", "start", "end", "wrapper", "start"]


def test_an_apply_retries_the_overlay_under_the_firmware_shell(
    tmp_path: Path, programs: dict[str, Path], shell: Path
) -> None:
    (tmp_path / "device").mkdir()
    station = OverlayStation(tmp_path, programs)
    try:
        station.device.ok("apply")
        station.boot()
        station.mark.write_text("boot-1\n")
        station.crashes.write_text("1\n")
        process = _run(station, shell, "core-apply", station.script_env())
        stdout, stderr = process.communicate(timeout=180)
        assert process.returncode == 0, stderr
        assert '"qt5_overlay":"active"' in stdout
        assert len(_settled(station)) == 1
        assert not station.mark.exists()
        assert _starts(station) == ["overlay", "overlay", "plain", "overlay"]
    finally:
        station.stop_all()


def test_the_qt5_display_starts_after_a_pause_of_5_s(station: Station, shell: Path) -> None:
    station.boot(C300X_TEST_TEARDOWN="0")

    def run(env: dict[str, str]) -> None:
        process = _run(station, shell, "reload", env)
        _, stderr = process.communicate(timeout=120)
        assert process.returncode == 0, stderr

    assert 4.7 <= _restart_pause(station, run, qt5=True) < 6.5


def test_a_display_that_writes_only_after_the_next_watchdog_check_under_the_firmware_shell(
    tmp_path: Path, programs: dict[str, Path], shell: Path
) -> None:
    (tmp_path / "device").mkdir()
    station = OverlayStation(tmp_path, programs)

    def run(env: dict[str, str]) -> None:
        process = _run(station, shell, "apply", env)
        _, stderr = process.communicate(timeout=180)
        assert process.returncode == 0, stderr

    try:
        watched_restart(station, run)
    finally:
        station.stop_all()
