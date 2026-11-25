"""Device clock corrections must not expire or extend native runtime deadlines."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ringer_and_command_deadlines_ignore_wall_clock_changes(tmp_path):
    binary = tmp_path / "monotonic-time-test"
    result = subprocess.run(
        [
            "cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
            "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
            "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
            str(ROOT / "native_agent/test/monotonic_time_test.c"),
            str(ROOT / "native_agent/src/ringer_control.c"),
            str(ROOT / "native_agent/src/command_job.c"),
            "-o", str(binary),
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr


def test_last_contact_age_is_measured_on_the_monotonic_clock():
    """The station gets its time from NTP after boot; a step must not move "Last contact"."""
    source = (ROOT / "native_agent/src/http.c").read_text(encoding="utf-8")
    mark = source[source.index("static void mark_home_assistant_callback_seen(struct agent_runtime *runtime, time_t now)\n{"):]
    mark = mark[:mark.index("\n}\n")]
    assert "runtime->home_assistant_last_seen_monotonic = c300x_monotonic_seconds();" in mark
    status = source[source.index('strcmp(request->path, "/ui/status") == 0'):]
    status = status[:status.index("return 1;")]
    assert "time(NULL)" not in status and "home_assistant_last_seen_at" not in status
    assert "(long)runtime->home_assistant_last_seen_monotonic" in status
    assert "(long)c300x_monotonic_seconds(), body" in status
