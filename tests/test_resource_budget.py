from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"],
        capture_output=True,
        check=True,
        text=True,
    )
    return [ROOT / line for line in result.stdout.splitlines() if line]


def test_native_agent_http_module_stays_within_interim_budget() -> None:
    """Keep pressure on the remaining monolithic native HTTP module."""

    path = ROOT / "native_agent" / "src" / "http.c"

    assert path.stat().st_size <= 425_000
    assert path.read_text(encoding="utf-8").count("\n") <= 12_450


def test_large_python_modules_stay_within_interim_budget() -> None:
    """Catch accidental HA-side module bloat before it reaches a release."""

    oversized = [
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "custom_components" / "bticino_c300x").glob("*.py")
        if path.stat().st_size > 75_000
    ]

    assert oversized == []


def test_tracked_runtime_payload_budget_excludes_generated_archives() -> None:
    """Repository releases must not keep generated archives or device payload blobs."""

    forbidden_suffixes = {
        ".7z",
        ".apk",
        ".bin",
        ".deb",
        ".ext4",
        ".fwz",
        ".gz",
        ".img",
        ".ipk",
        ".o",
        ".rpm",
        ".so",
        ".tar",
        ".tgz",
        ".xz",
        ".zip",
    }
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in _tracked_files()
        if path.suffix.lower() in forbidden_suffixes
    ]

    assert offenders == []
