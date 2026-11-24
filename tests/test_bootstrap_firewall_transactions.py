"""Exercise bootstrap firewall transactions without touching a device or firewall."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "native_agent/scripts/bootstrap_firewall.sh"
ORIGINAL = "#!/bin/sh\n# Firmware rules\niptables -P INPUT DROP\n"


def _run(tmp_path: Path, fault: str = "", **env: str) -> subprocess.CompletedProcess[str]:
    # Shell functions intercept every privileged operation, even with a fixed PATH.
    harness = """
mount() { printf '%s\\n' "$*" >> "$MOUNT_LOG"; }
iptables() { printf '%s\n' "$*" >> "$IPTABLES_LOG"; [ "$1" = "-A" ]; }
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
            "IPTABLES_LOG": str(tmp_path / "iptables.log"),
            "C300X_QML_C100X_MARKER": str(tmp_path / "BtClass100"),
            **env,
        },
    )


def _live(tmp_path: Path) -> Path:
    path = tmp_path / "iptables"
    path.write_text(ORIGINAL, encoding="utf-8")
    path.chmod(0o750)
    return path


@pytest.mark.parametrize(("c100x", "enabled", "want_media"), [
    (True, None, False), (True, "0", False), (True, "1", True), (False, None, True),
])
def test_bootstrap_media_policy_matches_live_and_persistent_rules(
    tmp_path, c100x, enabled, want_media,
):
    path = _live(tmp_path)
    if c100x:
        (tmp_path / "BtClass100").touch()
    env = {"C300X_RTSP_PORT": "7654"}
    if enabled is not None:
        env["C300X_VIDEO_ENABLED"] = enabled
    result = _run(tmp_path, **env)
    assert result.returncode == 0, result.stderr
    for rules in (path.read_text(), (tmp_path / "iptables.log").read_text()):
        assert "-A INPUT -p tcp --dport 8089" in rules
        for port in ("tcp --dport 7654", "udp --dport 40004"):
            assert (port in rules) is want_media


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


@pytest.mark.parametrize("copy_status", [0, 1])
def test_incomplete_backup_is_never_published_and_retry_is_safe(
    tmp_path: Path, copy_status: int
) -> None:
    live = _live(tmp_path)
    fault = """
cp() {
    case "${1:-}" in
        /tmp/c300x-firewall-original.*)
            printf '# incomplete backup\\n' > "$2"
            return COPY_STATUS ;;
    esac
    command cp "$@"
}
""".replace("COPY_STATUS", str(copy_status))

    result = _run(tmp_path, fault)

    assert result.returncode != 0
    assert live.read_text() == ORIGINAL
    assert not (tmp_path / "backup").exists()
    assert not list(tmp_path.glob("backup.c300x.*"))
    assert not (tmp_path / "mount.log").exists()
    retry = _run(tmp_path)
    assert retry.returncode == 0, retry.stderr
    backup = tmp_path / "backup"
    assert backup.read_text() == ORIGINAL
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600


@pytest.mark.parametrize("already_patched", [False, True])
def test_existing_corrupt_backup_fails_closed(
    tmp_path: Path, already_patched: bool
) -> None:
    live = _live(tmp_path)
    if already_patched:
        assert _run(tmp_path).returncode == 0
        (tmp_path / "mount.log").unlink()
    before = live.read_bytes()
    backup = tmp_path / "backup"
    backup.write_text("# corrupt backup\n", encoding="utf-8")

    result = _run(tmp_path)

    assert result.returncode != 0
    assert "backup cannot be verified" in result.stderr
    assert live.read_bytes() == before
    assert backup.read_text() == "# corrupt backup\n"
    assert not (tmp_path / "mount.log").exists()


def test_existing_verified_backup_is_retained(tmp_path: Path) -> None:
    _live(tmp_path)
    backup = tmp_path / "backup"
    backup.write_text(ORIGINAL, encoding="utf-8")
    before = backup.stat()

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "changed_files=1\n"
    assert backup.read_text() == ORIGINAL
    assert backup.stat().st_ino == before.st_ino
    assert backup.stat().st_mtime_ns == before.st_mtime_ns


def test_existing_backup_symlink_fails_closed(tmp_path: Path) -> None:
    live = _live(tmp_path)
    (tmp_path / "backup").symlink_to(live)

    result = _run(tmp_path)

    assert result.returncode != 0
    assert live.read_text() == ORIGINAL
    assert not (tmp_path / "mount.log").exists()


@pytest.mark.parametrize("video", ["0", "1"])
def test_missing_hook_opens_the_live_ports_and_writes_nothing(tmp_path: Path, video: str) -> None:
    # Some rooted stations have no boot hook at all (moved away by other tools).
    result = _run(tmp_path, C300X_VIDEO_ENABLED=video)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "changed_files=0\n"
    assert not (tmp_path / "iptables").exists()
    assert not (tmp_path / "backup").exists()
    assert not (tmp_path / "mount.log").exists()
    rules = (tmp_path / "iptables.log").read_text()
    assert "-A INPUT -p tcp --dport 8089 -j ACCEPT" in rules
    assert ("--dport 6554" in rules) is (video == "1")


def test_a_hook_that_is_no_regular_file_still_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "iptables").mkdir()

    result = _run(tmp_path)

    assert result.returncode != 0
    assert not (tmp_path / "iptables.log").exists()
    assert not (tmp_path / "mount.log").exists()
