"""GUI restart by qml_patch.sh with real processes.

bt_daemon starts the display start script once and never again (its software
watchdog reboots the station instead), so the restart is the agent's job
alone. On the Qt 5 display (firmware 3.0.6) one detached worker serves all
restart requests: it stops every start script and display program, settles,
starts once, verifies, retries an apply's failed overlay once and falls back
to stock. Firmware 1.7.19 and 2.0.2 restart the display exactly as release
2.9.1 does.

Processes are found by their real name, as pidof/killall do on the station;
a marker in their environment keeps each test to its own processes.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import suppress
from pathlib import Path

import pytest

from tests.test_qml_patch_qt5_overlay import Device
from tests.test_qml_patch_qt5_overlay import programs as programs
from tests.test_qml_patch_script import SCRIPT

_FIND = f"""#!{sys.executable}
import os, signal, sys
marker = "C300X_TEST_STATION=" + os.environ.get("C300X_TEST_STATION", "")
# The stand-in display runs under a name of its own: a host killall BtClass
# (another test, another worktree) cannot reach it.
ALIASES = {{"BtClass": "c300x-tdisp"}}

def find(name):
    name = ALIASES.get(name, name)
    found = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{{entry}}/comm") as comm:
                if comm.read().strip() != name:
                    continue
            with open(f"/proc/{{entry}}/environ", "rb") as environ:
                if marker.encode() not in environ.read().split(b"\\0"):
                    continue
        except OSError:
            continue
        found.append(int(entry))
    return found
"""

PIDOF = _FIND + """
args = [a for a in sys.argv[1:] if not a.startswith("-")]
pids = find(args[0])
if pids:
    print(" ".join(map(str, pids)))
sys.exit(0 if pids else 1)
"""

KILLALL = _FIND + """
args = sys.argv[1:]
number = signal.SIGTERM
if args[0].startswith("-"):
    name = args.pop(0)[1:]
    number = getattr(signal, name if name.startswith("SIG") else "SIG" + name)
with open(os.environ["C300X_TEST_CALLS"], "a") as calls:
    calls.write("killall " + " ".join(sys.argv[1:]) + "\\n")
pids = find(args[0])
for pid in pids:
    try:
        os.kill(pid, number)
    except OSError:
        pass
sys.exit(0 if pids else 1)
"""

WRAPPER = """#!/bin/sh
echo "wrapper reload=${C300X_GUI_RELOAD:-} $$" >> "$C300X_TEST_LOG"
trap "killall BtClass; exit 0" TERM
./bin/gui/BtClass &
wait
"""

# The start script of 3876e2b4: a failed overlay start sleeps (3 s there, 6 s
# here so that the restart surely meets the pause), and the vendor trap of a
# SIGTERM taken then runs only after that sleep.
OLD_WRAPPER = """#!/bin/sh
echo "wrapper old $$" >> "$C300X_TEST_LOG"
trap "killall BtClass; exit 0" TERM
for try in 1 2; do
    [ $try = 1 ] || sleep 6
    LD_PRELOAD=overlay ./bin/gui/BtClass &
    wait $!
done
./bin/gui/BtClass &
wait
"""

# Started as bin/gui/BtClass like the vendor's; it goes on as c300x-tdisp
# (the same PID), a process name no host killall BtClass reaches.
DISPLAY_NAME = "c300x-tdisp"

PROGRAM = """#!/bin/sh
[ "${0##*/}" = BtClass ] && exec "${0%/*}/c300x-tdisp" "$@"
echo "start $$ ${LD_PRELOAD:-plain}" >> "$C300X_TEST_LOG"
if [ -n "${LD_PRELOAD:-}" ] && [ -f "$C300X_TEST_CRASHES" ]; then
    left=$(cat "$C300X_TEST_CRASHES")
    if [ "$left" -gt 0 ]; then
        echo $((left - 1)) > "$C300X_TEST_CRASHES"
        echo "crash $$" >> "$C300X_TEST_LOG"
        exit 134
    fi
fi
if [ -n "${LD_PRELOAD:-}" ] && [ -f "$C300X_TEST_CRASHES.late" ]; then
    left=$(cat "$C300X_TEST_CRASHES.late")
    if [ "$left" -gt 0 ]; then
        echo $((left - 1)) > "$C300X_TEST_CRASHES.late"
        : > "$C300X_TEST_ALIVE"
        sleep 4
        echo "crash $$" >> "$C300X_TEST_LOG"
        exit 134
    fi
fi
if [ -n "${LD_PRELOAD:-}" ] && [ -f "$C300X_TEST_CRASHES.hang" ]; then
    while :; do sleep 1; done
fi
sleep "${C300X_TEST_ALIVE_DELAY:-0}"
stop() {
    [ "${C300X_TEST_IGNORE_TERM:-0}" = 1 ] && return
    sleep "${C300X_TEST_TEARDOWN:-0}"
    echo "end $$" >> "$C300X_TEST_LOG"
    exit 143
}
trap stop TERM
if [ -z "${LD_PRELOAD:-}" ] && [ -f "$C300X_TEST_CRASHES.silent" ]; then
    while :; do sleep 0.2; done
fi
while :; do
    : > "$C300X_TEST_ALIVE"
    sleep 0.2
done
"""


class Station:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.marker = uuid.uuid4().hex
        self.log = root / "gui.log"
        tools = root / "tools"
        tools.mkdir()
        for name, text in (("pidof", PIDOF), ("killall", KILLALL)):
            (tools / name).write_text(text)
            (tools / name).chmod(0o755)
        self.wrapper = root / "bin/BtClass_qws"
        self.wrapper.parent.mkdir(parents=True, exist_ok=True)
        self.wrapper.write_text(WRAPPER)
        self.wrapper.chmod(0o755)
        self.program = root / "bin/gui/BtClass"
        self.program.parent.mkdir(parents=True, exist_ok=True)
        self.program.write_text(PROGRAM)
        self.program.chmod(0o755)
        shutil.copy(self.program, self.program.with_name(DISPLAY_NAME))
        self.run_dir = root / "gui-restart"
        self.crashes = root / "crashes"
        self.env = {
            **os.environ,
            "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
            "C300X_TEST_STATION": self.marker,
            "C300X_TEST_LOG": str(self.log),
            "C300X_TEST_CALLS": str(root / "calls.log"),
            "C300X_TEST_ALIVE": str(root / "alive"),
            "C300X_TEST_CRASHES": str(self.crashes),
        }
        (root / "libQt5Core.so.5").write_text("")
        (root / "boot_id").write_text("boot-1\n")

    def script_env(self, *, qt5: bool = True, **env: str) -> dict[str, str]:
        return {
            **self.env,
            "C300X_QML_QT5_MARKER": str(self.root / ("libQt5Core.so.5" if qt5 else "no-qt5")),
            "C300X_AGENT_DIR": str(self.root / "agent"),
            "C300X_BACKUP_ROOT": str(self.root / "backups"),
            "C300X_QML_QT5_LOG": str(self.root / "display-qt5.log"),
            "C300X_QML_BOOT_ID": str(self.root / "boot_id"),
            "C300X_QML_GUI_DIR": str(self.root / "gui"),
            "C300X_QML_BACKUP_DIR": str(self.root / "backup"),
            "C300X_QML_GUI_WRAPPER": str(self.wrapper),
            "C300X_QML_GUI_ROOT": str(self.root),
            "C300X_QML_GUI_ALIVE_FILE": str(self.root / "alive"),
            "C300X_QML_GUI_RUN_DIR": str(self.run_dir),
            "C300X_QML_RELOAD_GUI": "1",
            "C300X_QML_GUI_RELOAD_DELAY_SECONDS": "1",
            "C300X_QML_QT5_STABLE_SECONDS": "1",
            "C300X_QML_NO_REMOUNT": "1",
            **env,
        }

    def boot(self, *, wait: bool = True, **env: str) -> None:
        """Start the GUI the way bt_daemon does: the start script, once, not our child."""

        subprocess.run(["sh", "-c", f"setsid '{self.wrapper}' >/dev/null 2>&1 &"],
                       cwd=self.root, env={**self.env, **env}, check=True)
        if wait:
            assert _wait_for(lambda: bool(self.running()))

    def reload(self, *, qt5: bool = True, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([str(SCRIPT), "reload"], capture_output=True, text=True,
                              env=self.script_env(qt5=qt5, **env), check=False, timeout=90)

    def pids(self, name: str) -> list[int]:
        result = subprocess.run([str(self.root / "tools/pidof"), name], env=self.env,
                                capture_output=True, text=True, check=False)
        return [int(pid) for pid in result.stdout.split()]

    def running(self) -> list[int]:
        return self.pids("BtClass")

    def wrappers(self) -> list[int]:
        return self.pids(self.wrapper.name)

    def events(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def calls(self) -> list[str]:
        calls = self.root / "calls.log"
        return calls.read_text().splitlines() if calls.exists() else []

    def phase(self) -> str:
        phase = self.run_dir / "phase"
        return phase.read_text().strip() if phase.exists() else ""

    def worker_idle(self) -> bool:
        lock = self.run_dir / "lock"
        if not lock.exists():
            return True
        return subprocess.run(["flock", "-n", str(lock), "true"], check=False).returncode == 0

    def stop_all(self) -> None:
        for _ in range(3):
            for pid in self.pids("BtClass") + self.wrappers() + self.pids(SCRIPT.name):
                with suppress(OSError):
                    os.kill(pid, signal.SIGKILL)
            time.sleep(0.1)


def _wait_for(check: Callable[[], bool], seconds: float = 15) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.05)
    return check()


@pytest.fixture
def station(tmp_path: Path) -> Iterator[Station]:
    result = Station(tmp_path)
    yield result
    result.stop_all()


def _settled(station: Station) -> list[int]:
    assert _wait_for(station.worker_idle, 60)
    _wait_for(lambda: bool(station.running()), 5)
    time.sleep(0.3)
    return station.running()


def _kinds(station: Station) -> list[str]:
    return [event.split()[0] for event in station.events()]


def _starts(station: Station) -> list[str]:
    return ["plain" if event.split()[2] == "plain" else "overlay"
            for event in station.events() if event.startswith("start ")]


def test_the_new_display_starts_only_after_the_old_one_ended(station: Station) -> None:
    station.boot(C300X_TEST_TEARDOWN="2")
    old = station.running()
    result = station.reload()
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["gui_running"] is True
    running = _settled(station)
    assert len(running) == 1 and running != old
    assert _kinds(station) == ["wrapper", "start", "end", "wrapper", "start"]


def test_a_display_that_ignores_the_stop_request_is_ended_before_the_new_start(station: Station) -> None:
    station.boot(C300X_TEST_IGNORE_TERM="1")
    old = station.running()
    result = station.reload(C300X_QML_GUI_STOP_SECONDS="1")
    assert result.returncode == 0, result.stderr
    running = _settled(station)
    assert len(running) == 1 and running != old
    assert _kinds(station) == ["wrapper", "start", "wrapper", "start"]


def test_back_to_back_restarts_never_run_two_displays(station: Station) -> None:
    station.boot(C300X_TEST_TEARDOWN="1")
    for _ in range(2):
        result = station.reload()
        assert result.returncode == 0, result.stderr
        assert len(station.running()) == 1
    assert len(_settled(station)) == 1
    assert _kinds(station).count("start") == 3 and _kinds(station).count("end") == 2


def test_concurrent_restart_requests_share_one_cycle(station: Station) -> None:
    """Requests that wait while a cycle runs are served together by the next one."""

    station.boot(C300X_TEST_TEARDOWN="2")
    first = subprocess.Popen([str(SCRIPT), "reload"], env=station.script_env(),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert _wait_for(lambda: station.phase() == "stop")
    others = [subprocess.Popen([str(SCRIPT), "reload"], env=station.script_env(),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
              for _ in range(3)]
    for process in (first, *others):
        _, stderr = process.communicate(timeout=90)
        assert process.returncode == 0, stderr
    # An earlier requester may read its status while the next cycle restarts.
    assert len(_settled(station)) == 1
    # The boot start plus two cycles: the one in flight and one for the three waiting.
    assert _kinds(station).count("wrapper") == 3


def test_a_stop_during_an_old_start_scripts_pause_cannot_kill_the_next_display(station: Station) -> None:
    """A start script of the previous beta sleeps before its retry; its trap must never run later."""

    station.wrapper.write_text(OLD_WRAPPER)
    station.crashes.write_text("1\n")
    station.boot(wait=False)
    assert _wait_for(lambda: "crash" in _kinds(station))
    # The old start script now sleeps with no display program running.
    station.wrapper.write_text(WRAPPER)
    result = station.reload()
    assert result.returncode == 0, result.stderr
    running = _settled(station)
    time.sleep(7)
    assert station.running() == running and len(running) == 1
    assert _kinds(station)[-2:] == ["wrapper", "start"]


def test_without_any_display_left_the_restart_fails(station: Station) -> None:
    station.program.write_text("#!/bin/sh\nexit 1\n")
    result = station.reload(C300X_QML_QT5_START_SECONDS="3")
    assert result.returncode != 0
    assert "No display program could be started" in result.stderr


@pytest.mark.parametrize("phase", ["stop", "settle", "verify"])
@pytest.mark.parametrize("kill", ["TERM", "KILL"])
def test_the_job_deadline_in_any_phase_still_ends_with_one_display(
    station: Station, phase: str, kill: str
) -> None:
    """The agent signals the job's process group; the worker finishes the cycle.

    The reload trap of firmware 1.7.x/2.0.2 repeats the restart; on the Qt 5
    display it only exits, so the one filed request is the one restart."""

    station.boot(C300X_TEST_TEARDOWN="1")
    process = subprocess.Popen([str(SCRIPT), "reload"], env=station.script_env(
        C300X_QML_GUI_RELOAD_DELAY_SECONDS="2"), start_new_session=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert _wait_for(lambda: station.phase() == phase, 30), station.phase()
    os.killpg(process.pid, getattr(signal, f"SIG{kill}"))
    process.communicate(timeout=30)
    assert process.returncode == (131 if kill == "TERM" else -9)
    running = _settled(station)
    assert len(running) == 1
    assert station.wrappers()
    assert _kinds(station).count("wrapper") == 2


def test_firmware_1_7_and_2_0_stop_only_the_display_program_and_run_the_script_with_sh(
    station: Station,
) -> None:
    """2.9.1's restart: killall BtClass, then /bin/sh with the start script."""

    station.boot()
    old = station.running()
    result = station.reload(qt5=False, C300X_QML_GUI_RELOAD_DELAY_SECONDS="1")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["gui_running"] is True
    time.sleep(0.5)
    running = station.running()
    assert len(running) == 1 and running != old
    assert station.calls() == ["killall BtClass"]
    assert _kinds(station) == ["wrapper", "start", "end", "wrapper", "start"]
    assert not station.run_dir.exists()


def test_firmware_1_7_and_2_0_do_not_force_a_display_that_ignores_the_stop_request(
    station: Station,
) -> None:
    """No wait, no SIGKILL: a display program still running is left alone, as in 2.9.1."""

    station.boot(C300X_TEST_IGNORE_TERM="1")
    old = station.running()
    result = station.reload(qt5=False, C300X_QML_GUI_STOP_SECONDS="1")
    assert result.returncode == 0, result.stderr
    assert station.running() == old
    assert station.calls() == ["killall BtClass"]
    assert _kinds(station) == ["wrapper", "start"]


class OverlayStation(Station):
    """The start script a real apply installs on a Qt 5 fixture, run for real."""

    def __init__(self, root: Path, programs: dict[str, Path]) -> None:
        super().__init__(root)
        self.device = Device(root / "device", programs)
        self.wrapper = self.device.wrapper

    def script_env(self, *, qt5: bool = True, **env: str) -> dict[str, str]:
        base = super().script_env(qt5=qt5)
        own = {key: base[key] for key in (
            "PATH", "C300X_TEST_STATION", "C300X_TEST_LOG", "C300X_TEST_CALLS", "C300X_TEST_ALIVE",
            "C300X_TEST_CRASHES", "C300X_QML_GUI_ALIVE_FILE", "C300X_QML_GUI_RUN_DIR",
            "C300X_QML_GUI_RELOAD_DELAY_SECONDS", "C300X_QML_QT5_STABLE_SECONDS")}
        return self.device.environment(**{**own, "C300X_QML_GUI_ROOT": str(self.root),
                                          "C300X_QML_RELOAD_GUI": "1", **env})

    def run(self, action: str, **env: str) -> dict[str, object]:
        result = subprocess.run([str(SCRIPT), action], capture_output=True, text=True,
                                env=self.script_env(**env), check=False, timeout=120)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout.strip().splitlines()[-1])

    @property
    def mark(self) -> Path:
        return Path(f"{self.device.rcc}.failed")


@pytest.fixture
def overlay(tmp_path: Path, programs: dict[str, Path]) -> Iterator[OverlayStation]:
    (tmp_path / "device").mkdir()
    result = OverlayStation(tmp_path, programs)
    result.device.ok("apply")
    yield result
    result.stop_all()


def test_an_apply_retries_a_failed_overlay_start_once_and_keeps_it(overlay: OverlayStation) -> None:
    """The first start after a stop crashes (the restart race); the worker starts once more."""

    overlay.boot()
    overlay.mark.write_text("boot-1\n")
    overlay.crashes.write_text("1\n")
    status = overlay.run("core-apply")
    assert status["ok"] is True and status["qt5_overlay"] == "active", status
    assert len(_settled(overlay)) == 1
    assert not overlay.mark.exists()
    # Boot, the crash, the stock fallback of that start script, the retry.
    assert _starts(overlay) == ["overlay", "overlay", "plain", "overlay"]


def test_a_second_overlay_failure_quarantines_for_this_boot_and_keeps_the_stock_display(
    overlay: OverlayStation,
) -> None:
    overlay.boot()
    overlay.mark.write_text("boot-1\n")
    overlay.crashes.write_text("2\n")
    status = overlay.run("core-apply")
    assert status["qt5_overlay"] == "failed"
    assert len(_settled(overlay)) == 1
    assert overlay.mark.read_text() == "boot-1\n"
    assert _starts(overlay) == ["overlay", "overlay", "plain", "overlay", "plain"]
    # A plain reload keeps the quarantine and the stock display.
    assert overlay.run("reload")["qt5_overlay"] == "failed"
    assert len(_settled(overlay)) == 1
    assert _starts(overlay)[-1] == "plain"


def test_back_to_back_restarts_leave_no_quarantine(overlay: OverlayStation) -> None:
    """Installer core-apply then apply, then the update follow-up's reload."""

    overlay.boot(C300X_TEST_TEARDOWN="1")
    overlay.mark.write_text("boot-1\n")
    assert overlay.run("core-apply")["qt5_overlay"] == "active"
    assert overlay.run("apply", C300X_QML_DYNAMIC_HOME_PAGE="1")["qt5_overlay"] == "active"
    assert overlay.run("reload")["qt5_overlay"] == "active"
    assert len(_settled(overlay)) == 1
    assert not overlay.mark.exists()
    assert set(_starts(overlay)) == {"overlay"}


def test_a_start_script_that_starts_nothing_falls_back_to_the_original_one(
    overlay: OverlayStation,
) -> None:
    overlay.boot()
    overlay.wrapper.write_text("#!/bin/sh\n# c300x-qrc-overlay: broken\nexit 1\n")
    status = overlay.run("reload", C300X_QML_QT5_START_SECONDS="3")
    assert status["qt5_overlay"] == "failed"
    assert len(_settled(overlay)) == 1
    assert overlay.mark.read_text() == "boot-1\n"
    assert _starts(overlay)[-1] == "plain"


def _held_lock(station: Station) -> Path:
    """An flock stand-in that finds the lock always held: no worker is started."""

    held = station.root / "tools/flock-held"
    held.write_text("#!/bin/sh\nexit 1\n")
    held.chmod(0o755)
    return held


def test_an_answer_is_read_only_once_it_is_complete(station: Station) -> None:
    """The worker's answer may be seen while it is written; an empty one is not an answer."""

    station.boot()
    process = subprocess.Popen([str(SCRIPT), "reload"], env=station.script_env(
        C300X_QML_GUI_FLOCK=str(_held_lock(station))),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    requests = station.run_dir / "requests"
    assert _wait_for(lambda: any(not p.name.endswith(".tmp") for p in requests.glob("*")))
    request = next(p for p in requests.glob("*") if not p.name.endswith(".tmp"))
    answer = station.run_dir / "done" / request.name
    answer.write_text("")
    time.sleep(2.5)
    answer.write_text("0\n")
    _, stderr = process.communicate(timeout=60)
    assert process.returncode == 0, stderr
    assert "No display program could be started" not in stderr


def test_a_requester_that_stopped_waiting_leaves_no_answer_behind(station: Station) -> None:
    station.boot(C300X_TEST_TEARDOWN="1")
    result = station.reload(C300X_QML_GUI_BUDGET_SECONDS="0")
    assert result.returncode == 0, result.stderr
    assert len(_settled(station)) == 1
    assert _kinds(station).count("wrapper") == 2
    assert list((station.run_dir / "done").iterdir()) == []


def test_a_request_filed_while_a_worker_ends_is_still_served(station: Station) -> None:
    """The requester sees the lock held and starts no worker; the next status read does."""

    import fcntl

    station.boot(C300X_TEST_TEARDOWN="1")
    station.run_dir.mkdir()
    with open(station.run_dir / "lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result = station.reload(C300X_QML_GUI_BUDGET_SECONDS="0")
        assert result.returncode == 0, result.stderr
    assert _kinds(station).count("wrapper") == 1
    status = subprocess.run([str(SCRIPT), "status"], capture_output=True, text=True,
                            env=station.script_env(), check=False, timeout=30)
    assert status.returncode == 0, status.stderr
    assert _wait_for(lambda: _kinds(station).count("wrapper") == 2, 30)
    assert len(_settled(station)) == 1


def test_without_flock_the_restart_fails_and_leaves_the_display_alone(station: Station) -> None:
    station.boot()
    old = station.running()
    result = station.reload(C300X_QML_GUI_FLOCK=str(station.root / "no-flock"),
                            C300X_QML_GUI_BUDGET_SECONDS="3")
    assert result.returncode != 0
    assert "needs flock" in result.stderr
    assert station.running() == old
    assert _kinds(station) == ["wrapper", "start"]


def test_a_signal_bounds_the_restart_wait_of_a_write_to_5_seconds(overlay: OverlayStation) -> None:
    """The agent's SIGTERM is followed by SIGKILL after 15 s: the rollback must end before."""

    overlay.boot(C300X_TEST_TEARDOWN="8")
    overlay.mark.write_text("boot-1\n")
    process = subprocess.Popen([str(SCRIPT), "core-apply"], env=overlay.script_env(),
                               start_new_session=True, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert _wait_for(lambda: overlay.phase() == "stop", 60), overlay.phase()
    signalled = time.monotonic()
    os.killpg(process.pid, signal.SIGTERM)
    process.communicate(timeout=60)
    assert time.monotonic() - signalled < 9
    assert process.returncode in (130, 131)
    assert len(_settled(overlay)) == 1


def test_a_display_that_ends_soon_after_its_first_watchdog_write_is_not_ready(
    overlay: OverlayStation,
) -> None:
    """Ready needs the same program to keep running after its first write."""

    overlay.boot()
    overlay.mark.write_text("boot-1\n")
    Path(f"{overlay.crashes}.late").write_text("1\n")
    status = overlay.run("core-apply", C300X_QML_QT5_STABLE_SECONDS="6")
    assert status["qt5_overlay"] == "active", status
    assert len(_settled(overlay)) == 1
    assert not overlay.mark.exists()
    assert _starts(overlay) == ["overlay", "overlay", "plain", "overlay"]


def test_a_display_that_writes_no_watchdog_file_falls_back_to_stock(overlay: OverlayStation) -> None:
    """bt_daemon would reboot without the file: the start counts as failed."""

    overlay.boot()
    overlay.mark.write_text("boot-1\n")
    Path(f"{overlay.crashes}.hang").write_text("")
    status = overlay.run("core-apply", C300X_QML_QT5_START_SECONDS="3")
    assert status["qt5_overlay"] == "failed", status
    assert len(_settled(overlay)) == 1
    assert overlay.mark.read_text() == "boot-1\n"
    assert _starts(overlay)[-1] == "plain"


def test_a_second_display_pid_late_in_the_start_wait_ends_with_the_stock_display(
    overlay: OverlayStation, tmp_path: Path,
) -> None:
    """Kept on purpose: a changed PID set restarts the watchdog evidence, not the start
    window. Past it the start counts as failed and the original display takes over,
    one display at a time; testers measure whether BtClass ever shows a second PID."""

    overlay.boot()
    result = overlay.run("reload", C300X_QML_GUI_BUDGET_SECONDS="0", C300X_QML_QT5_START_SECONDS="4",
                         C300X_QML_QT5_STABLE_SECONDS="12")
    assert result["ok"] is True, result
    assert _wait_for(lambda: overlay.phase() == "verify", 30), overlay.phase()
    time.sleep(5.5)
    # A second process under the display's name for a moment (a fork of it).
    second = tmp_path / "fork" / DISPLAY_NAME
    second.parent.mkdir()
    second.write_text("#!/bin/sh\nsleep 3\n")
    second.chmod(0o755)
    fork = subprocess.Popen([str(second)], env=overlay.env, start_new_session=True)
    try:
        assert len(_settled(overlay)) == 1
    finally:
        fork.kill()
        fork.wait()
    assert overlay.mark.read_text() == "boot-1\n"
    assert _starts(overlay) == ["overlay", "overlay", "plain"]
    # Each display ended before the next one started.
    events = overlay.events()
    starts = [index for index, event in enumerate(events) if event.startswith("start ")]
    for before, after in zip(starts, starts[1:], strict=False):
        assert any(event.startswith("end ") for event in events[before:after]), events


def test_a_write_during_a_restart_is_not_taken_for_a_failed_overlay(overlay: OverlayStation) -> None:
    """A write marks the overlay while it changes the files; a running cycle
    must neither read that as a failed start nor start the display meanwhile."""

    overlay.boot()
    overlay.mark.write_text("boot-1\n")
    # The first restart returns at once and its display writes the watchdog file only after 8 s.
    assert overlay.run("core-apply", C300X_QML_GUI_BUDGET_SECONDS="0",
                       C300X_TEST_ALIVE_DELAY="8")["ok"] is True
    assert _wait_for(lambda: overlay.phase() == "verify", 30), overlay.phase()
    status = overlay.run("apply", C300X_QML_DYNAMIC_HOME_PAGE="0")
    assert status["qt5_overlay"] == "active" and status["changed_files"], status
    assert len(_settled(overlay)) == 1
    assert not overlay.mark.exists()
    # The boot, the first restart, and one restart with the written files.
    assert _starts(overlay) == ["overlay", "overlay", "overlay"]


def test_a_restart_still_running_is_reported_as_pending(overlay: OverlayStation) -> None:
    """A write whose wait ended before its restart says so; a later status read tells the outcome."""

    overlay.boot(C300X_TEST_TEARDOWN="3")
    overlay.mark.write_text("boot-1\n")
    status = overlay.run("core-apply", C300X_QML_GUI_BUDGET_SECONDS="0")
    assert status["ok"] is True and status["gui_restart"] == "pending", status
    assert len(_settled(overlay)) == 1
    later = overlay.run("status")
    assert later["gui_restart"] == "idle" and later["gui_running"] is True
    assert later["qt5_overlay"] == "active"


def test_a_request_of_a_worker_that_died_is_served_by_the_next_worker(station: Station) -> None:
    """A worker killed mid-cycle leaves its request in serving/; the next worker serves it
    in the same cycle as the new request."""

    station.boot(C300X_TEST_TEARDOWN="1")
    for name in ("requests", "serving", "done"):
        (station.run_dir / name).mkdir(parents=True)
    orphan = f"{os.getpid()}.1"
    (station.run_dir / "serving" / orphan).write_text("keep\n")
    result = station.reload()
    assert result.returncode == 0, result.stderr
    assert len(_settled(station)) == 1
    assert (station.run_dir / "done" / orphan).read_text() == "0\n"
    assert _kinds(station).count("wrapper") == 2
    assert not list((station.run_dir / "serving").iterdir())


def test_a_note_of_a_killed_writer_whose_pid_was_reused_does_not_block_the_restart(
    station: Station,
) -> None:
    """The note's PID runs, but it is not this script: no write, the note goes."""

    station.boot(C300X_TEST_TEARDOWN="1")
    foreign = subprocess.Popen(["sleep", "120"])
    try:
        station.run_dir.mkdir()
        (station.run_dir / "writing").write_text(f"{foreign.pid}\n")
        result = station.reload()
        assert result.returncode == 0, result.stderr
        assert _wait_for(lambda: _kinds(station).count("wrapper") == 2, 20), station.events()
        assert len(_settled(station)) == 1
        assert not (station.run_dir / "writing").exists()
    finally:
        foreign.kill()
        foreign.wait()


def test_a_note_whose_pid_was_reused_by_the_worker_itself_does_not_block_the_restart(
    station: Station,
) -> None:
    """A killed writer's note names the PID the worker got later: the worker never writes,
    so it neither waits on itself nor counts the note."""

    station.boot(C300X_TEST_TEARDOWN="1")
    note = station.run_dir / "writing"
    flock = station.root / "tools/flock-own-note"
    # Called by the worker for its lock: its parent is the worker's shell.
    flock.write_text(
        "#!/bin/sh\n"
        f"if [ \"$1\" = -n ] && [ \"$2\" = 9 ] && mkdir '{station.root}/note-written' 2>/dev/null; then\n"
        f"    printf '%s\\n' \"$PPID\" > '{note}'\n"
        "fi\n"
        f"exec '{shutil.which('flock')}' \"$@\"\n"
    )
    flock.chmod(0o755)
    result = station.reload(C300X_QML_GUI_FLOCK=str(flock), C300X_QML_GUI_BUDGET_SECONDS="3")
    assert result.returncode == 0, result.stderr
    assert (station.root / "note-written").exists()
    assert _wait_for(lambda: _kinds(station).count("wrapper") == 2, 20), station.events()
    assert len(_settled(station)) == 1
    assert not note.exists()


def test_a_request_filed_as_the_worker_unlocks_is_served_before_it_exits(station: Station) -> None:
    """The worker found nothing to do and lets go of its lock; a request filed right then
    (its requester saw the lock held and started no worker) is served by this worker.

    The request is filed once the reload command, whose closing status read would
    start a worker, has returned: only the worker's own re-check is left to serve it.
    """

    station.boot(C300X_TEST_TEARDOWN="1")
    late = f"{os.getpid()}.7"
    released = station.root / "reload-returned"
    flock = station.root / "tools/flock-late-request"
    flock.write_text(
        "#!/bin/sh\n"
        f"if [ \"$1\" = -u ] && [ \"$2\" = 9 ] && mkdir '{station.root}/late-filed' 2>/dev/null; then\n"
        f"    '{shutil.which('flock')}' -u 9\n"
        f"    while [ ! -e '{released}' ]; do sleep 0.1; done\n"
        f"    printf 'keep\\n' > '{station.run_dir}/requests/{late}'\n"
        "    exit 0\n"
        "fi\n"
        f"exec '{shutil.which('flock')}' \"$@\"\n"
    )
    flock.chmod(0o755)
    result = station.reload(C300X_QML_GUI_FLOCK=str(flock))
    assert result.returncode == 0, result.stderr
    released.write_text("")
    answer = station.run_dir / "done" / late
    assert _wait_for(answer.exists, 30), station.events()
    assert answer.read_text() == "0\n"
    assert _kinds(station).count("wrapper") == 3
    assert len(_settled(station)) == 1


def test_the_stand_in_displays_are_out_of_reach_of_a_host_killall(station: Station) -> None:
    """Concurrent runs elsewhere call the real killall BtClass; it must not hit these."""

    station.boot()
    for pid in station.running():
        assert Path(f"/proc/{pid}/comm").read_text().strip() == DISPLAY_NAME


def test_the_shipped_display_after_a_failed_overlay_needs_a_watchdog_write_of_its_own(
    overlay: OverlayStation,
) -> None:
    """The overlay wrote the file, then crashed; the shipped display that the start script
    starts then is ready only on its own write, not on the overlay's."""

    overlay.boot()
    Path(f"{overlay.crashes}.late").write_text("1\n")
    Path(f"{overlay.crashes}.silent").write_text("")
    result = subprocess.run([str(SCRIPT), "reload"], capture_output=True, text=True, timeout=120,
                            env=overlay.script_env(C300X_QML_QT5_STABLE_SECONDS="6",
                                                   C300X_QML_QT5_START_SECONDS="3"), check=False)
    assert result.returncode != 0, overlay.events()
    assert "No display program could be started" in result.stderr
    assert _starts(overlay)[:3] == ["overlay", "overlay", "plain"]


def test_an_overlay_that_fails_before_the_first_look_is_still_retried(overlay: OverlayStation) -> None:
    """Every look at the mark waits on a slow lock: the crashing start has written
    the mark before the worker first reads it, and is still taken for its failure."""

    slow = overlay.root / "tools/flock-slow"
    slow.write_text(f'#!/bin/sh\nsleep 0.7\nexec "{shutil.which("flock")}" "$@"\n')
    slow.chmod(0o755)
    overlay.boot()
    overlay.mark.write_text("boot-1\n")
    overlay.crashes.write_text("1\n")
    status = overlay.run("core-apply", C300X_QML_GUI_FLOCK=str(slow))
    assert status["ok"] is True and status["qt5_overlay"] == "active", status
    assert len(_settled(overlay)) == 1
    assert not overlay.mark.exists()
    assert _starts(overlay) == ["overlay", "overlay", "plain", "overlay"]


def test_a_request_still_being_filed_waits_and_one_left_by_a_dead_requester_is_removed(
    station: Station,
) -> None:
    """A request is written as <pid>.<n>.tmp and then renamed: the worker never takes
    the half-written file, and drops it once the process that wrote it is gone."""

    station.boot(C300X_TEST_TEARDOWN="1")
    requests = station.run_dir / "requests"
    requests.mkdir(parents=True)
    ended = subprocess.Popen(["true"])
    ended.wait()
    filing = requests / f"{os.getpid()}.1.tmp"
    filing.write_text("retry\n")
    dead = requests / f"{ended.pid}.1.tmp"
    dead.write_text("retry\n")
    result = station.reload()
    assert result.returncode == 0, result.stderr
    assert len(_settled(station)) == 1
    assert _kinds(station).count("wrapper") == 2
    assert filing.read_text() == "retry\n"
    assert not dead.exists()
    assert not any(path.name.endswith(".tmp") for path in (station.run_dir / "done").iterdir())


@pytest.mark.parametrize("action", [["gui-worker"], ["qt5-prepare"], ["qt5-import", "/nonexistent"]])
def test_the_internal_qt5_steps_are_refused_on_firmware_1_7_and_2_0(station: Station, action: list[str]) -> None:
    result = subprocess.run([str(SCRIPT), *action], capture_output=True, text=True,
                            env=station.script_env(qt5=False), check=False, timeout=30)
    assert result.returncode == 2
    assert json.loads(result.stdout) == {"ok": False, "available": False, "state": "invalid_action"}
    assert "unbound" not in result.stderr
    assert not station.run_dir.exists()
