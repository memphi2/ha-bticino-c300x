"""A script started by the agent must not inherit the agent's sockets.

The display patch script restarts the device GUI. A GUI that inherited the
agent's listening media socket keeps it open for its whole life, and the
next agent start can then not bind the port.
"""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_started_scripts_do_not_inherit_the_agents_sockets(tmp_path):
    script = tmp_path / "list-fds.sh"
    script.write_text(
        '#!/bin/sh\nfor fd in /proc/$$/fd/*; do printf "%s " "$(readlink "$fd")"; done\n'
    )
    script.chmod(0o755)
    binary = tmp_path / "command-job-fds-test"
    result = subprocess.run(
        [
            "cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
            "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
            "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
            str(ROOT / "native_agent/test/command_job_fds_test.c"),
            str(ROOT / "native_agent/src/command_job.c"),
            "-o", str(binary),
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(binary), str(script)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
