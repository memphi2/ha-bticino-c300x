"""Exercise bootstrap firewall transactions without touching a device or firewall."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "native_agent/scripts/bootstrap_firewall.sh"
ORIGINAL = "#!/bin/sh\n# Firmware rules\niptables -P INPUT DROP\n"


def _run(tmp_path: Path, fault: str = "") -> subprocess.CompletedProcess[str]:
    # Shell functions intercept every privileged operation, even with a fixed PATH.
    harness = """
mount() { printf '%s\\n' "$*" >> "$MOUNT_LOG"; }
iptables() { return 0; }
"""
    return subprocess.run(
        ["/bin/sh"],
        input=harness + fault + SCRIPT.read_text(encoding="utf-8"),
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "C300X_IPTABLES": str(tmp_path / "iptables"),
            "C300X_IPTABLES_BACKUP": str(tmp_path / "backup"),
            "C300X_API_PORT": "8089",
            "MOUNT_LOG": str(tmp_path / "mount.log"),
        },
    )


def _live(tmp_path: Path) -> Path:
    path = tmp_path / "iptables"
    path.write_text(ORIGINAL, encoding="utf-8")
    path.chmod(0o750)
    return path


@pytest.mark.parametrize("failure", ["write", "rename", "metadata"])
def test_live_failure_preserves_original(tmp_path: Path, failure: str) -> None:
    live = _live(tmp_path)
    faults = {
        "write": """
cat() {
    case "${1:-}" in
        /tmp/c300x-firewall.[0-9]*) printf '# partial write\\n'; return 1 ;;
    esac
    command cat "$@"
}
""",
        "rename": """
mv() {
    if [ "${3:-}" = "$C300X_IPTABLES" ]; then return 1; fi
    command mv "$@"
}
""",
        "metadata": """
cp() {
    if [ "${1:-}" = "-p" ]; then return 1; fi
    command cp "$@"
}
""",
    }

    result = _run(tmp_path, faults[failure])

    assert result.returncode != 0
    assert live.read_text() == ORIGINAL
    assert stat.S_IMODE(live.stat().st_mode) == 0o750
    assert not list(tmp_path.glob("iptables.c300x.*"))
    assert (tmp_path / "mount.log").read_text().splitlines() == [
        "-o remount,rw /",
        "-o remount,ro /",
    ]


def test_success_preserves_metadata_and_is_idempotent(tmp_path: Path) -> None:
    live = _live(tmp_path)
    before = live.stat()

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    assert live.read_text().startswith(ORIGINAL)
    assert "--dport 8089" in live.read_text()
    after = live.stat()
    assert stat.S_IMODE(after.st_mode) == stat.S_IMODE(before.st_mode)
    assert (after.st_uid, after.st_gid) == (before.st_uid, before.st_gid)
    assert not list(tmp_path.glob("iptables.c300x.*"))
    assert (tmp_path / "backup").read_text() == ORIGINAL
    assert _run(tmp_path).stdout == "changed_files=0\n"
