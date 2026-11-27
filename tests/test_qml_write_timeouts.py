"""Home Assistant's waits for a QML write follow the agent's deadline and grace."""

from __future__ import annotations

import re
from pathlib import Path

from custom_components.bticino_c300x import device_installer
from custom_components.bticino_c300x._api_maintenance import (
    _GUI_RELOAD_JOB_TIMEOUT,
    _QML_WRITE_JOB_TIMEOUT,
)
from custom_components.bticino_c300x.agent_update import MAINTENANCE_BUSY_WAIT_SECONDS

SRC = Path(__file__).resolve().parents[1] / "native_agent" / "src"


def _define(text: str, name: str) -> int:
    match = re.search(rf"^#define {name} (\d+)$", text, re.MULTILINE)
    assert match is not None, name
    return int(match.group(1))


def test_home_assistant_outwaits_a_qml_write_and_its_rollback() -> None:
    header = (SRC / "http_maintenance.h").read_text(encoding="utf-8")
    deadline_ms = _define(header, "C300X_QML_WRITE_TIMEOUT_MS")
    grace_ms = _define(header, "C300X_QML_WRITE_TERM_GRACE_MS")
    longest = (deadline_ms + grace_ms) / 1000
    # The write request waits for the 504 after the rollback.
    assert longest + 5 <= _QML_WRITE_JOB_TIMEOUT
    # A read that meets a write (or the start-up recovery) waits it out.
    assert longest < MAINTENANCE_BUSY_WAIT_SECONDS <= longest + 5
    # Both agent jobs use these constants, not their own numbers.
    maintenance = (SRC / "http_maintenance.c").read_text(encoding="utf-8")
    recovery = (SRC / "qml_recovery.c").read_text(encoding="utf-8")
    limit = (SRC / "maintenance_job_limit.h").read_text(encoding="utf-8")
    assert "c300x_maintenance_job_timeout_ms(records_write, gui_reload)" in maintenance
    assert "C300X_QML_WRITE_TIMEOUT_MS : 10000" in limit
    assert "records_write || gui_reload ? C300X_QML_WRITE_TERM_GRACE_MS : 0" in maintenance
    # A GUI reload: 10 s, then the same grace; its request waits for the answer.
    assert 10 + grace_ms / 1000 + 5 <= _GUI_RELOAD_JOB_TIMEOUT < MAINTENANCE_BUSY_WAIT_SECONDS
    assert '"recover", -1, C300X_QML_WRITE_TIMEOUT_MS' in recovery
    # The device-user label writes are such jobs too; their requests wait 50 s.
    label = (SRC / "device_user_label.c").read_text(encoding="utf-8")
    assert "out, out_len, C300X_QML_WRITE_TIMEOUT_MS" in label
    assert "term_grace_ms = C300X_QML_WRITE_TERM_GRACE_MS" in label
    assert "command_transaction" not in (SRC / "http_device_user.c").read_text(encoding="utf-8")
    assert "term_grace_ms = C300X_QML_WRITE_TERM_GRACE_MS" in recovery


def test_the_ssh_installer_gives_a_display_write_the_agents_deadline_and_grace() -> None:
    """Over SSH the script has no agent job around it; the installer stands in
    for it with the same two numbers."""

    header = (SRC / "http_maintenance.h").read_text(encoding="utf-8")
    assert _define(
        header, "C300X_QML_WRITE_TIMEOUT_MS") == device_installer._SSH_DISPLAY_WRITE_TIMEOUT * 1000
    assert _define(
        header, "C300X_QML_WRITE_TERM_GRACE_MS") == device_installer._SSH_DISPLAY_WRITE_TERM_GRACE * 1000


def _init_stop_waits() -> tuple[str, int, int]:
    init = (SRC.parents[1] / "custom_components/bticino_c300x/device_agent/init"
            / "c300x-native-agent").read_text(encoding="utf-8")
    assert "usleep 100000" in init
    stop_wait, kill_wait = (int(n) for n in re.findall(r'wait_gone "\$pid" (\d+)', init))
    return init, stop_wait, kill_wait


def test_the_init_scripts_stop_outwaits_the_agents_shutdown_of_a_display_write() -> None:
    """The agent ends a running display write or C100X activation with SIGTERM
    and waits its grace; a SIGKILL inside it leaves the job's processes running
    next to the new agent. The stop waits that and 5 s for the rest of the
    shutdown, polling every 100 ms."""

    grace_ms = _define((SRC / "http_maintenance.h").read_text(encoding="utf-8"),
                       "C300X_QML_WRITE_TERM_GRACE_MS")
    _init, stop_wait, _kill_wait = _init_stop_waits()
    assert stop_wait * 100 >= grace_ms + 5000
    activation = (SRC / "c100x_activation.c").read_text(encoding="utf-8")
    assert "job.term_grace_ms = C300X_QML_WRITE_TERM_GRACE_MS" in activation


def test_the_ssh_command_limit_covers_the_init_scripts_restart() -> None:
    """restart = stop (wait, SIGKILL, wait) + start + status checks, each wait
    one pause of 100 ms; the limit leaves it three times that. Other commands
    keep the shorter limit."""

    init, stop_wait, kill_wait = _init_stop_waits()
    status_checks = int(re.search(r"^        tries=(\d+)$", init, re.MULTILINE).group(1))
    longest = (stop_wait + kill_wait + 1 + status_checks) * 0.1
    assert longest * 3 <= device_installer._SSH_AGENT_STOP_TIMEOUT
    timeout = device_installer._command_timeout
    assert timeout("/etc/init.d/c300x-native-agent restart") == device_installer._SSH_AGENT_STOP_TIMEOUT
    assert timeout("sh -s stop || exit 1; rm -f x") == device_installer._SSH_AGENT_STOP_TIMEOUT
    assert timeout("true") == device_installer._SSH_COMMAND_TIMEOUT == 30.0
