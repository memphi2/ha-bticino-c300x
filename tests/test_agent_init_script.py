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
                            timeout=5, env={**os.environ, "C300X_AGENT_DIR": str(tmp_path),
                            "C300X_AGENT_ENV": str(tmp_path / "absent-env"),
                            "START_RC": str(start_rc), "STOP_RC": str(stop_rc), "CALL_LOG": str(log)})
    assert result.returncode == expected, result.stderr
    assert log.read_text().splitlines() == calls
    if stop_rc:
        assert pid.read_text() == "123\n"


# The station's busybox 1.24 start-stop-daemon ignores --retry: --stop sends one
# TERM and returns at once. The script itself must wait for the old agent to
# exit, and only ever signal a PID that is still the agent binary.


def _device_rootfs() -> Path | None:
    """The 1.7.19 system image of the local Qt 4 setup (scripts/setup_qt4_runtime.py)."""
    if os.environ.get("C300X_QT4_ROOTFS"):
        return Path(os.environ["C300X_QT4_ROOTFS"])
    from scripts.setup_qt4_runtime import runtime_paths

    paths = runtime_paths()
    return Path(paths[1]) if paths else None


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
    fprintf(log, "started %d\n", (int)getpid());
    signal(SIGTERM, getenv("STUB_IGNORE_TERM") ? SIG_IGN : on_term);
    while (!term) pause();
    usleep(600000);
    fprintf(log, "stopped %d\n", (int)getpid());
    return 0;
}
"""


def _device_init(tmp_path: Path, source: str | None = None):
    import shutil
    import socket

    rootfs = _device_rootfs()
    qemu, compiler = shutil.which("qemu-arm"), shutil.which("cc")
    busybox = rootfs / "bin/busybox.nosuid" if rootfs else None
    if not qemu or not compiler or busybox is None or not busybox.is_file():
        pytest.skip("needs qemu-arm, cc and the station's busybox (scripts/setup_qt4_runtime.py)")
    commands = tmp_path / "commands"
    commands.mkdir()
    for applet in ("sh", "start-stop-daemon", "readlink", "cat", "usleep", "rm"):
        wrapper = commands / applet
        wrapper.write_text(f'#!/bin/sh\nexec {qemu} -L {rootfs} {busybox} {applet} "$@"\n')
        wrapper.chmod(0o700)
    (tmp_path / "c300x-agent-native.c").write_text(STUB_AGENT)
    subprocess.run([compiler, "-O", "-o", str(tmp_path / "c300x-agent-native"),
                    str(tmp_path / "c300x-agent-native.c")], check=True)
    (tmp_path / "config.json").write_text("{}")
    script = tmp_path / "init"
    # The emulator falls back to host files, so the station's init functions
    # would source host locale files; they are not part of this check.
    script.write_text((source or SCRIPT.read_text()).replace(
        "[ -f /etc/init.d/functions ] && . /etc/init.d/functions", "").replace(
        "#!/bin/sh", f"#!{commands}/sh", 1).replace(
        "PATH=/sbin:/usr/sbin:/bin:/usr/bin", f"PATH={commands}:/bin:/usr/bin"))
    script.chmod(0o700)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    log = tmp_path / "agent.log"
    env = {**os.environ, "C300X_AGENT_DIR": str(tmp_path), "C300X_AGENT_ENV": str(tmp_path / "absent"),
           "STUB_LOG": str(log), "STUB_PORT": str(port)}

    def run(action: str, **extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([str(script), action], capture_output=True, text=True,
                              timeout=60, env={**env, **extra}, check=False)

    return run, log, tmp_path / "c300x-agent-native.pid", port


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return Path(f"/proc/{pid}/status").read_text().split("State:")[1].split()[0] != "Z"


def _reap_all(tmp_path: Path) -> None:
    import signal

    for line in (tmp_path / "agent.log").read_text().splitlines() if (tmp_path / "agent.log").exists() else []:
        pid = int(line.split()[1])
        if _alive(pid):
            os.kill(pid, signal.SIGKILL)


def test_restart_waits_for_the_old_agent_on_the_station_busybox(tmp_path):
    run, log, pidfile, _port = _device_init(tmp_path)
    try:
        assert run("start").returncode == 0
        first = None
        for _ in range(50):
            if pidfile.exists() and "started" in log.read_text():
                first = int(pidfile.read_text())
                break
            __import__("time").sleep(0.1)
        assert first is not None and _alive(first)
        restart = run("restart")
        events = log.read_text()
        assert "api_bind_failed" not in events, events
        assert restart.returncode == 0, restart.stderr + events
        second = int(pidfile.read_text())
        assert second != first and not _alive(first) and _alive(second)
        assert run("status").returncode == 0
        assert run("stop").returncode == 0
        assert not _alive(second) and not pidfile.exists()
        assert f"stopped {second}" in log.read_text()
    finally:
        _reap_all(tmp_path)


def test_restart_reports_an_agent_that_does_not_come_up(tmp_path):
    import socket

    run, log, pidfile, port = _device_init(tmp_path)
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


def test_stop_kills_an_agent_that_ignores_term_and_spares_a_foreign_pid(tmp_path):
    import time

    run, log, pidfile, _port = _device_init(tmp_path)
    try:
        assert run("start", STUB_IGNORE_TERM="1").returncode == 0
        for _ in range(50):
            if pidfile.exists() and "started" in log.read_text():
                break
            time.sleep(0.1)
        agent = int(pidfile.read_text())
        started = time.monotonic()
        assert run("stop").returncode == 0
        assert not _alive(agent) and not pidfile.exists()
        assert time.monotonic() - started >= 4
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
