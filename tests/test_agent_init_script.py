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
    ("restart", 0, 0, 0, ["--stop", "--start"]),
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
