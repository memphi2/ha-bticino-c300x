"""Original wrapper/traps under original ARM /bin/sh, with a harmless child.

No vendor GUI, daemon, mount, framebuffer or hardware plugin is executed.
The child and local_alpha/killall are substitutes scoped to one process group.
"""

import os
import shutil
import signal
import subprocess
import time
from contextlib import suppress
from pathlib import Path

import pytest

from tests.test_qml_patch_qt5_overlay import Device
from tests.test_qml_patch_qt5_overlay import programs as programs


@pytest.fixture
def firmware():
    value = os.environ.get("C300X_QT5_FIRMWARE")
    if not value:
        pytest.skip("Private firmware shell and wrapper not supplied")
    return Path(value)


@pytest.mark.parametrize("shell", ["host", "firmware"])
@pytest.mark.parametrize("patched", [False, True])
@pytest.mark.parametrize("mode", ["error", "normal", "term", "usr1", "usr2", "late-error",
                                  "exit137", "exit138", "exit140", "exit143", "clock-step", "child"])
def test_original_wrapper_lifecycle(programs, tmp_path, firmware, shell, patched, mode):
    device = Device(tmp_path, programs)
    device.program = firmware / "home/bticino/bin/gui/BtClass"
    shutil.copy2(firmware / "home/bticino/bin/BtClass_qws", device.wrapper)
    uptime = tmp_path / "uptime"
    uptime.write_text("100.50 80.25\n")
    device.ok("apply", C300X_QML_UPTIME=str(uptime))
    # Function overrides retain the original wrapper body and signal traps.
    prefix = (
        'local_alpha() { :; }\n'
        'killall() { probe_signal=TERM; [ "$#" -le 1 ] || probe_signal="${1#-SIG}"; '
        'kill -s "$probe_signal" "$(cat "$PROBE_PID")"; }\n'
    )
    if mode == "clock-step":
        # The wall clock jumps forward during the start (hwclock, NTP).
        prefix += ('date() { if [ -f "$PROBE_CLOCK" ]; then echo 100000; '
                   'else : > "$PROBE_CLOCK"; echo 100; fi; }\n')
    wrapper = tmp_path / "wrapper-probe.sh"
    wrapper.write_text(prefix + (device.wrapper if patched else device.wrapper_backup).read_text())
    child = tmp_path / "bin/gui/BtClass"
    child.parent.mkdir(parents=True)
    child.write_text(
        '#!/bin/sh\n'
        'echo $$ > "$PROBE_PID"\n'
        'trap \'echo usr1 >> "$PROBE_LOG"\' USR1\n'
        'trap \'echo usr2 >> "$PROBE_LOG"\' USR2\n'
        'trap \'echo term >> "$PROBE_LOG"; exit 0\' TERM\n'
        'echo "start:${LD_PRELOAD:+overlay}" >> "$PROBE_LOG"\n'
        'case "$PROBE_MODE" in error|clock-step) exit 139;; normal) exit 0;; '
        'late-error) echo "161.75 90.00" > "$PROBE_UPTIME"; exit 139;; '
        # A child that keeps the display's error output open for 30 s.
        'child) [ -z "$LD_PRELOAD" ] || sleep 30 > /dev/null & exit 139;; '
        'exit*) exit "${PROBE_MODE#exit}";; esac\n'
        'while :; do sleep 0.05; done\n'
    )
    child.chmod(0o700)
    env = {**os.environ, "PROBE_PID": str(tmp_path / "child.pid"),
           "PROBE_LOG": str(tmp_path / "events"), "PROBE_MODE": mode,
           "PROBE_CLOCK": str(tmp_path / "clock"), "PROBE_UPTIME": str(uptime)}
    command = ["/bin/bash", "--posix", str(wrapper)]
    if shell == "firmware":
        # Original /bin/sh is an absolute link to /bin/bash.bash, not BusyBox.
        original_shell = firmware / "bin/sh"
        assert original_shell.is_symlink()
        target = os.readlink(original_shell)
        assert target == "/bin/bash.bash"
        command = ["qemu-arm", "-L", str(firmware), "-E",
                   f"LD_LIBRARY_PATH={firmware}/lib:{firmware}/usr/lib", "-0", "sh",
                   str(firmware / target.lstrip("/")), str(wrapper)]
    process = subprocess.Popen(command, cwd=tmp_path, env=env, start_new_session=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    events = Path(env["PROBE_LOG"])

    def wait_event(value):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if events.exists() and value in events.read_text().splitlines():
                return
            if process.poll() is not None:
                break
            time.sleep(0.025)
        pytest.fail(f"Missing {value}; child events: {events.read_text() if events.exists() else ''}")

    try:
        wait_event("start:overlay" if patched else "start:")
        if mode == "child" and patched:
            started = time.monotonic()
            wait_event("start:")
            # The fallback follows the display program, not its error output.
            assert time.monotonic() - started < 5
        if mode in {"term", "usr1", "usr2"}:
            if mode != "term":
                process.send_signal(signal.SIGUSR1 if mode == "usr1" else signal.SIGUSR2)
                wait_event(mode)
                assert process.poll() is None, "forwarded user signal must not terminate wrapper"
            process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=15)
    finally:
        # Only descendants of the isolated probe, never name-based host kills.
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate(timeout=5)
        (tmp_path / "wrapper.log").write_text(stdout + stderr)
    lines = events.read_text().splitlines()
    if mode in {"error", "clock-step", "child"} and patched:
        assert lines == ["start:overlay", "start:"]
        assert device.ok("status")["qt5_overlay"] == "failed"
    else:
        assert lines.count("start:overlay" if patched else "start:") == 1
        assert ("start:" if patched else "start:overlay") not in lines
        assert device.ok("status")["qt5_overlay"] == "active"
    # The original SIGTERM trap uses bare `trap SIGTERM`, which POSIX Bash
    # rejects. Preserve/report vendor behavior; do not call it overlay failure.
    expected = 2 if mode in {"term", "usr1", "usr2"} else 0
    if patched and mode == "late-error":
        expected = 139
    elif patched and mode.startswith("exit"):
        expected = int(mode[4:])
    assert process.returncode == expected, stdout + stderr
