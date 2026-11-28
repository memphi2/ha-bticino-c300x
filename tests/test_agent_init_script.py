"""Execute init control flow with isolated paths and a fake daemon controller."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "custom_components/bticino_c300x/device_agent/init/c300x-native-agent"


@pytest.mark.parametrize("action,start_rc,stop_rc,expected,calls", [
    ("start", 23, 0, 23, ["--start"]),
    ("stop", 0, 24, 24, ["--stop"]),
    ("restart", 0, 24, 24, ["--stop"]),
    ("restart", 23, 0, 23, ["--stop", "--start"]),
    ("start", 0, 0, 0, ["--start"]),
    ("stop", 0, 0, 0, ["--stop"]),
    # The fake controller starts nothing, so restart finds no running agent.
    ("restart", 0, 0, 1, ["--stop", "--start"]),
])
def test_init_propagates_failures(tmp_path, action, start_rc, stop_rc, expected, calls):
    commands = tmp_path / "commands"
    commands.mkdir()
    daemon = commands / "start-stop-daemon"
    daemon.write_text('#!/bin/sh\nprintf "%s\\n" "$1" >> "$CALL_LOG"\n'
                      'case "$1" in --start) exit "$START_RC";; --stop) exit "$STOP_RC";; esac\n')
    daemon.chmod(0o700)
    delay = commands / "usleep"
    delay.write_text("#!/bin/sh\nexit 0\n")
    delay.chmod(0o700)
    agent = tmp_path / "c300x-agent-native"
    agent.write_text("#!/bin/sh\nexit 99\n")
    agent.chmod(0o700)
    (tmp_path / "config.json").write_text("{}")
    pid = tmp_path / "c300x-agent-native.pid"
    pid.write_text("123\n")
    script = tmp_path / "init"
    script.write_text(SCRIPT.read_text().replace(
        "PATH=/sbin:/usr/sbin:/bin:/usr/bin", f"PATH={commands}:/bin:/usr/bin"
    ))
    script.chmod(0o700)
    log = tmp_path / "calls"
    result = subprocess.run([str(script), action], capture_output=True, text=True,
                            timeout=60, env={**os.environ, "C300X_AGENT_DIR": str(tmp_path),
                            "C300X_AGENT_ENV": str(tmp_path / "absent-env"),
                            "START_RC": str(start_rc), "STOP_RC": str(stop_rc), "CALL_LOG": str(log)})
    assert result.returncode == expected, result.stderr
    assert log.read_text().splitlines() == calls
    if stop_rc:
        assert pid.read_text() == "123\n"


# The station's busybox start-stop-daemon (1.24 on 1.7.19) ignores --retry: --stop
# sends one TERM and returns at once. The script itself must wait for the old agent to
# exit, and only ever signal a PID that is still the agent binary.


# Each firmware's own system image. On all of them /bin/sh is bash (run as sh,
# in POSIX mode), start-stop-daemon and usleep are busybox applets and cat, rm
# and readlink are coreutils; /etc/init.d/functions is the firmware's own, a
# bash file of Red Hat's initscripts on 1.7.19, 2.0.2 and the C100X, a short
# one defining status() and killproc() on 3.0.6. The tests run the init script
# with exactly these programs under qemu-arm.
FIRMWARES = {
    # firmware: (folder below C300X_FIRMWARE_WORK, variable naming the folder, busybox, bash)
    "1.7.19": ("rootfs-1.7.19", "C300X_QT4_ROOTFS", "1.24.1", "4.4.12"),
    "2.0.2": ("rootfs-2.0.2", "", "1.24.1", "4.4.12"),
    "3.0.6": ("rootfs-3.0.6", "C300X_QT5_FIRMWARE", "1.35.0", "5.1.16"),
    "c100x-1.5.8": ("rootfs-c100x-1.5.8", "C100X_QT5_FIRMWARE", "1.27.2", "4.4.12"),
}


def _device_rootfs(firmware: str = "1.7.19") -> Path | None:
    """The firmware's private system image (C300X_FIRMWARE_WORK, default the sibling c300x-fwpatch/work)."""
    folder, variable = FIRMWARES[firmware][:2]
    if variable and os.environ.get(variable):
        return Path(os.environ[variable])
    candidate = Path(os.environ.get("C300X_FIRMWARE_WORK", ROOT.parent / "c300x-fwpatch/work")) / folder
    if candidate.is_dir():
        return candidate
    if firmware != "1.7.19":
        return None
    from scripts.setup_qt4_runtime import runtime_paths

    paths = runtime_paths()
    return Path(paths[1]) if paths else None


def station_script(source: str, commands: Path, rootfs: Path) -> str:
    """The init script as the station runs it, with the test's applets first in PATH.

    It sources the firmware's own /etc/init.d/functions, which on 1.7.19,
    2.0.2 and the C100X sets PATH again and on 3.0.6 defines status() and
    killproc(); the test's applets are put back in front afterwards.
    """
    functions = rootfs / "etc/init.d/functions"
    assert functions.is_file(), functions
    loaded = (f". {functions} || exit 97\n"
              "type status >/dev/null 2>&1 && type killproc >/dev/null 2>&1 || exit 97\n"
              f"PATH={commands}:$PATH")
    line = "[ -f /etc/init.d/functions ] && . /etc/init.d/functions"
    if line in source:
        source = source.replace(line, loaded)
    return source.replace("#!/bin/sh", f"#!{commands}/sh", 1).replace(
        "PATH=/sbin:/usr/sbin:/bin:/usr/bin", f"PATH={commands}:/bin:/usr/bin")


STUB_AGENT = r"""
#include <arpa/inet.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>
static volatile sig_atomic_t term;
static void on_term(int s) { (void)s; term = 1; }
int main(void) {
    FILE *log = fopen(getenv("STUB_LOG"), "a");
    int fd = socket(AF_INET, SOCK_STREAM, 0), one = 1;
    struct sockaddr_in a;
    sigset_t blocked, waiting;
    setvbuf(log, NULL, _IONBF, 0);
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    memset(&a, 0, sizeof a);
    a.sin_family = AF_INET;
    a.sin_port = htons(atoi(getenv("STUB_PORT")));
    a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (bind(fd, (struct sockaddr *)&a, sizeof a) != 0 || listen(fd, 1) != 0) {
        fprintf(log, "api_bind_failed %d\n", (int)getpid());
        return 1;
    }
    /* Before the start line: the test may stop the agent as soon as it reads it.
     * TERM stays blocked outside sigsuspend, so it cannot slip in between the
     * check of the flag and the wait. */
    signal(SIGTERM, getenv("STUB_IGNORE_TERM") ? SIG_IGN : on_term);
    sigemptyset(&blocked);
    sigaddset(&blocked, SIGTERM);
    sigprocmask(SIG_BLOCK, &blocked, &waiting);
    sigdelset(&waiting, SIGTERM);
    fprintf(log, "started %d\n", (int)getpid());
    while (!term) sigsuspend(&waiting);
    for (int ms = getenv("STUB_TERM_MS") ? atoi(getenv("STUB_TERM_MS")) : 600; ms > 0; ms -= 100)
        usleep(100000);
    fprintf(log, "stopped %d\n", (int)getpid());
    return 0;
}
"""


START_STOP_DAEMON = r"""#!/bin/sh
{run}
rc=$?
case " $* " in
    *" --start "*" --background "*) ;;
    *) exit "$rc" ;;
esac
tries=1200
while [ "$tries" -gt 0 ]; do
    pid="$(cat {pidfile} 2>/dev/null)"
    if [ -n "$pid" ]; then
        exe="$(readlink /proc/"$pid"/exe 2>/dev/null)" || break
        [ "$exe" = {qemu} ] || break
    fi
    tries=$((tries - 1))
    sleep 0.05
done
exit "$rc"
"""


def _station_program(rootfs: Path, name: str) -> Path | None:
    """The file the station runs for a command name, its links followed inside the image."""
    for folder in ("bin", "sbin", "usr/bin", "usr/sbin"):
        path = rootfs / folder / name
        for _ in range(8):
            if not path.is_symlink():
                break
            target = os.readlink(path)
            path = rootfs / target.lstrip("/") if target.startswith("/") else path.parent / target
        if path.is_file() and not path.is_symlink():
            return path
    return None


def _device_init(tmp_path: Path, source: str | None = None, firmware: str = "1.7.19"):
    import shutil

    from native_agent.test.smoke import free_tcp_port

    rootfs = _device_rootfs(firmware)
    qemu, compiler = shutil.which("qemu-arm"), shutil.which("cc")
    busybox = rootfs / "bin/busybox.nosuid" if rootfs else None
    if not qemu or not compiler or busybox is None or not busybox.is_file():
        pytest.skip(f"needs qemu-arm, cc and the {firmware} system image (C300X_FIRMWARE_WORK)")
    assert f"BusyBox v{FIRMWARES[firmware][2]} ".encode() in busybox.read_bytes(), busybox
    # Only the libraries: qemu would otherwise read the image's empty /proc.
    sysroot = tmp_path / "sysroot"
    sysroot.mkdir()
    for part in ("lib", "usr"):
        (sysroot / part).symlink_to(rootfs / part)
    commands = tmp_path / "commands"
    commands.mkdir()
    for applet in ("sh", "start-stop-daemon", "readlink", "cat", "usleep", "rm"):
        program = _station_program(rootfs, applet)
        assert program is not None, (firmware, applet)
        if applet == "sh":
            assert program.name == "bash.bash"
            assert f"@(#)Bash version {FIRMWARES[firmware][3]}".encode() in program.read_bytes()
        else:
            assert program.name == ("busybox.nosuid" if applet in ("start-stop-daemon", "usleep")
                                    else f"{applet}.coreutils"), (firmware, applet, program)
        wrapper = commands / applet
        run = (f'{qemu} -L {sysroot} -E LD_LIBRARY_PATH={rootfs}/lib:{rootfs}/usr/lib '
               f'-0 {applet} {program} "$@"')
        if applet == "start-stop-daemon":
            # On the station --background forks with vfork, so the call returns
            # once the child has written the PID file and become the agent. The
            # emulator runs vfork as a plain fork and returns at once; the wait
            # gives back what the station guarantees.
            wrapper.write_text(START_STOP_DAEMON.format(run=run, qemu=qemu,
                                                        pidfile=tmp_path / "c300x-agent-native.pid"))
        else:
            wrapper.write_text(f'#!/bin/sh\nexec {run}\n')
        wrapper.chmod(0o700)
    (tmp_path / "c300x-agent-native.c").write_text(STUB_AGENT)
    subprocess.run([compiler, "-O", "-o", str(tmp_path / "c300x-agent-native"),
                    str(tmp_path / "c300x-agent-native.c")], check=True)
    (tmp_path / "config.json").write_text("{}")
    script = tmp_path / "init"
    script.write_text(station_script(source or SCRIPT.read_text(), commands, rootfs))
    script.chmod(0o700)
    port = free_tcp_port()
    log = tmp_path / "agent.log"
    # The station has no locale files; the emulator would read the host's.
    env = {**os.environ, "C300X_AGENT_DIR": str(tmp_path), "C300X_AGENT_ENV": str(tmp_path / "absent"),
           "STUB_LOG": str(log), "STUB_PORT": str(port), "NOLOCALE": "1"}

    def run(action: str, **extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([str(script), action], capture_output=True, text=True,
                              timeout=300, env={**env, **extra}, check=False)

    return run, log, tmp_path / "c300x-agent-native.pid", port


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return Path(f"/proc/{pid}/status").read_text().split("State:")[1].split()[0] != "Z"


def _wait_started(pidfile: Path, log: Path, seconds: float = 60) -> int:
    """The PID of the started agent, once that agent has written its start line.

    start-stop-daemon writes the PID file before the agent has opened its log,
    and under the emulator on a busy machine both can take seconds.
    """

    import time

    deadline = time.monotonic() + seconds
    while True:
        pid = pidfile.read_text().strip() if pidfile.exists() else ""
        if pid and log.exists() and f"started {pid}" in log.read_text().splitlines():
            return int(pid)
        assert time.monotonic() < deadline, log.read_text() if log.exists() else "no agent log"
        time.sleep(0.05)


def _reap_all(tmp_path: Path) -> None:
    import signal

    for line in (tmp_path / "agent.log").read_text().splitlines() if (tmp_path / "agent.log").exists() else []:
        pid = int(line.split()[1])
        if _alive(pid):
            os.kill(pid, signal.SIGKILL)


@pytest.mark.parametrize("firmware", FIRMWARES)
def test_restart_waits_for_the_old_agent_on_the_station_busybox(tmp_path, firmware):
    run, log, pidfile, _port = _device_init(tmp_path, firmware=firmware)
    try:
        assert run("start").returncode == 0
        first = _wait_started(pidfile, log)
        assert _alive(first)
        restart = run("restart")
        events = log.read_text()
        assert "api_bind_failed" not in events, events
        assert restart.returncode == 0, restart.stderr + events
        second = _wait_started(pidfile, log)
        assert second != first and not _alive(first) and _alive(second)
        assert run("status").returncode == 0
        assert run("stop").returncode == 0
        assert not _alive(second) and not pidfile.exists()
        assert f"stopped {second}" in log.read_text()
    finally:
        _reap_all(tmp_path)


@pytest.mark.parametrize("firmware", FIRMWARES)
def test_restart_reports_an_agent_that_does_not_come_up(tmp_path, firmware):
    import socket

    run, log, pidfile, port = _device_init(tmp_path, firmware=firmware)
    with socket.socket() as busy:
        busy.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        busy.bind(("127.0.0.1", port))
        busy.listen(1)
        try:
            restart = run("restart")
            assert "api_bind_failed" in log.read_text()
            assert restart.returncode != 0
            assert run("status").returncode == 3
        finally:
            _reap_all(tmp_path)


@pytest.mark.parametrize("firmware", FIRMWARES)
def test_stop_kills_an_agent_that_ignores_term_and_spares_a_foreign_pid(tmp_path, firmware):
    import time

    run, log, pidfile, _port = _device_init(tmp_path, firmware=firmware)
    try:
        assert run("start", STUB_IGNORE_TERM="1").returncode == 0
        agent = _wait_started(pidfile, log)
        started = time.monotonic()
        assert run("stop").returncode == 0
        assert not _alive(agent) and not pidfile.exists()
        assert time.monotonic() - started >= 20
        assert f"stopped {agent}" not in log.read_text()
    finally:
        _reap_all(tmp_path)
    # A stale pidfile whose PID now belongs to another program (on the station
    # possibly a watched bt_* process) must not be signalled at all.
    foreign = subprocess.Popen(["sleep", "30"])
    try:
        pidfile.write_text(f"{foreign.pid}\n")
        assert run("status").returncode == 3
        assert run("stop").returncode == 0
        assert foreign.poll() is None
        assert not pidfile.exists()
    finally:
        foreign.kill()
        foreign.wait()


@pytest.mark.parametrize("firmware", FIRMWARES)
def test_stop_lets_an_agent_finish_a_shutdown_within_the_display_write_grace(tmp_path, firmware):
    """An agent ending a display write or C100X activation needs up to its 15 s
    grace after TERM; a SIGKILL then would orphan the job's processes. The
    stand-in needs 12 s: under the emulator the old 50 polls took 6 to 9 s."""
    import time

    run, log, pidfile, _port = _device_init(tmp_path, firmware=firmware)
    try:
        assert run("start", STUB_TERM_MS="12000").returncode == 0
        agent = _wait_started(pidfile, log)
        started = time.monotonic()
        assert run("stop").returncode == 0
        assert f"stopped {agent}" in log.read_text()
        assert not _alive(agent) and not pidfile.exists()
        assert time.monotonic() - started >= 12
    finally:
        _reap_all(tmp_path)
