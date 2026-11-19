"""The label write scripts are not killed after ten seconds.

`qml_patch.sh media-user-label-apply` and `media-user-label-restore` remount
the root filesystem writable, replace display files and restart the GUI. They
undo a failed write and remount read-only in shell traps. The agent used to
stop them with SIGKILL after ten seconds; no trap runs then, so a slow write
left the root filesystem writable and the transaction directory behind.
"""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "native_agent" / "src"


def test_capture_without_deadline_lets_the_script_finish(tmp_path):
    marker = tmp_path / "finished"
    script = tmp_path / "write.sh"
    script.write_text(
        "#!/bin/sh\n"
        '[ "$1" = fail ] && exit 3\n'
        "sleep 0.6\n"
        f"touch {marker}\n"
        "echo done\n"
    )
    script.chmod(0o755)
    binary = tmp_path / "command-capture-deadline-test"
    result = subprocess.run(
        [
            "cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
            "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
            "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
            str(ROOT / "native_agent/test/command_capture_deadline_test.c"),
            str(SOURCE / "command_job.c"),
            "-o", str(binary),
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run(
        [str(binary), str(script), str(marker)], capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr


def test_label_writes_have_no_deadline_and_the_status_read_keeps_its_own():
    calls = re.findall(
        r'c300x_command_capture\(\s*config->maintenance_qml_patch_script,\s*"([a-z-]+)",'
        r"\s*\w+,\s*sizeof\(\w+\),\s*([A-Z0-9_]+),",
        (SOURCE / "http.c").read_text(encoding="utf-8"),
    )
    assert calls == [
        ("status", "10000"),
        ("media-user-label-apply", "C300X_COMMAND_NO_DEADLINE"),
        ("media-user-label-restore", "C300X_COMMAND_NO_DEADLINE"),
    ]
