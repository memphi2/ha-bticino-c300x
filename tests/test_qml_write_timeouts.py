"""Home Assistant's waits for a QML write follow the agent's deadline and grace."""

from __future__ import annotations

import re
from pathlib import Path

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
    assert "C300X_QML_WRITE_TIMEOUT_MS : 10000" in maintenance
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
