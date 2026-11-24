"""GUI restart by qml_patch.sh: one starter, and only after the old display program ended.

bt_daemon starts the display start script once and never starts it again (its
software watchdog reboots the station instead), so the restart is the agent's
job alone. Real processes stand in for the start script and the display program.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path

import pytest

from tests.test_qml_patch_script import SCRIPT

PIDOF = """#!/bin/sh
found=1
for entry in "$C300X_TEST_REGISTRY/$1".*; do
    [ -e "$entry" ] || continue
    pid=${entry##*.}
    if kill -0 "$pid" 2>/dev/null; then printf '%s ' "$pid"; found=0; fi
done
[ "$found" = 0 ] && echo
exit $found
"""

KILLALL = """#!/bin/sh
signal=TERM
case "$1" in -*) signal=${1#-}; shift ;; esac
found=1
for entry in "$C300X_TEST_REGISTRY/$1".*; do
    [ -e "$entry" ] || continue
    kill -"$signal" "${entry##*.}" 2>/dev/null && found=0
done
exit $found
"""

WRAPPER = """#!/bin/sh
: > "$C300X_TEST_REGISTRY/BtClass_qws.$$"
echo "wrapper reload=${C300X_GUI_RELOAD:-} $$" >> "$C300X_TEST_LOG"
trap "killall BtClass; exit 0" TERM
"$C300X_TEST_PROGRAM" &
wait
"""

PROGRAM = """#!/bin/sh
: > "$C300X_TEST_REGISTRY/BtClass.$$"
echo "start $$" >> "$C300X_TEST_LOG"
stop() {
    [ "${C300X_TEST_IGNORE_TERM:-0}" = 1 ] && return
    sleep "${C300X_TEST_TEARDOWN:-0}"
    echo "end $$" >> "$C300X_TEST_LOG"
    rm -f "$C300X_TEST_REGISTRY/BtClass.$$"
    exit 143
}
trap stop TERM
while :; do sleep 0.1; done
"""


class Station:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.registry = root / "registry"
        self.registry.mkdir()
        self.log = root / "gui.log"
        tools = root / "tools"
        tools.mkdir()
        for name, text in (("pidof", PIDOF), ("killall", KILLALL)):
            (tools / name).write_text(text)
            (tools / name).chmod(0o755)
        self.wrapper = root / "bin/BtClass_qws"
        self.wrapper.parent.mkdir()
        self.wrapper.write_text(WRAPPER)
        self.wrapper.chmod(0o755)
        self.program = root / "BtClass"
        self.program.write_text(PROGRAM)
        self.program.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
            "C300X_TEST_REGISTRY": str(self.registry),
            "C300X_TEST_LOG": str(self.log),
            "C300X_TEST_PROGRAM": str(self.program),
        }

    def boot(self, **env: str) -> None:
        """Start the GUI the way bt_daemon does: the start script, once."""

        subprocess.Popen([str(self.wrapper)], cwd=self.root, env={**self.env, **env}, start_new_session=True)
        deadline = time.monotonic() + 10
        while not self.running() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert self.running()

    def reload(self, **env: str) -> subprocess.CompletedProcess[str]:
        environment = {
            **self.env,
            "C300X_QML_QT5_MARKER": str(self.root / "no-qt5"),
            "C300X_QML_GUI_DIR": str(self.root / "gui"),
            "C300X_QML_BACKUP_DIR": str(self.root / "backup"),
            "C300X_QML_GUI_WRAPPER": str(self.wrapper),
            "C300X_QML_GUI_ROOT": str(self.root),
            "C300X_QML_RELOAD_GUI": "1",
            "C300X_QML_GUI_RELOAD_DELAY_SECONDS": "0",
            "C300X_QML_NO_REMOUNT": "1",
            **env,
        }
        return subprocess.run([str(SCRIPT), "reload"], capture_output=True, text=True,
                              env=environment, check=False, timeout=60)

    def running(self) -> list[int]:
        pids = []
        for entry in self.registry.glob("BtClass.*"):
            pid = int(entry.suffix[1:])
            try:
                os.kill(pid, 0)
            except OSError:
                continue
            pids.append(pid)
        return pids

    def events(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def stop_all(self) -> None:
        for entry in self.registry.iterdir():
            with suppress(OSError, ValueError):
                os.kill(int(entry.suffix[1:]), signal.SIGKILL)


@pytest.fixture
def station(tmp_path: Path) -> Iterator[Station]:
    result = Station(tmp_path)
    yield result
    result.stop_all()


def _settled(station: Station) -> list[int]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        running = station.running()
        if running:
            time.sleep(0.3)
            return station.running()
        time.sleep(0.05)
    return station.running()


def test_the_new_display_starts_only_after_the_old_one_ended(station: Station) -> None:
    station.boot(C300X_TEST_TEARDOWN="2")
    old = station.running()
    result = station.reload()
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["gui_running"] is True
    running = _settled(station)
    assert len(running) == 1 and running != old
    events = [event.split()[0] for event in station.events()]
    assert events == ["wrapper", "start", "end", "wrapper", "start"]
    assert station.events()[3].startswith("wrapper reload=1 ")


def test_a_display_that_ignores_the_stop_request_is_ended_before_the_new_start(station: Station) -> None:
    station.boot(C300X_TEST_IGNORE_TERM="1")
    old = station.running()
    result = station.reload(C300X_QML_GUI_STOP_SECONDS="1")
    assert result.returncode == 0, result.stderr
    running = _settled(station)
    assert len(running) == 1 and running != old
    assert [event.split()[0] for event in station.events()] == ["wrapper", "start", "wrapper", "start"]


def test_back_to_back_restarts_never_run_two_displays(station: Station) -> None:
    station.boot(C300X_TEST_TEARDOWN="1")
    for _ in range(2):
        result = station.reload()
        assert result.returncode == 0, result.stderr
        assert len(station.running()) == 1
    assert len(_settled(station)) == 1
    starts = [event for event in station.events() if event.startswith("start ")]
    ends = [event for event in station.events() if event.startswith("end ")]
    assert len(starts) == 3 and len(ends) == 2
