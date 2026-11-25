"""Build the host agent with the default make flags once per test run.

Many test modules start the unmodified agent, and each module that imports
one of their fixtures built it again into a directory of its own: the same
compile nineteen times per run. The first caller builds it below the run's shared temporary
directory; every other module, and every pytest-xdist worker, waits on the
lock and reuses that tree. Callers only read it: anything they compile or
write goes into a directory of their own.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native_agent"
# Make reads these from the environment; a different value is a different build.
_BUILD_ENVIRONMENT = ("CC", "CFLAGS", "LDFLAGS", "CPATH", "CURL_INCLUDE_DIR", "MAKEFLAGS")


def _run_directory(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The temporary directory all workers of this run share."""

    base = tmp_path_factory.getbasetemp()
    return base.parent if os.environ.get("PYTEST_XDIST_WORKER") else base


def default_host_build(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Return a build directory of `make all` with the Makefile's own flags."""

    key = hashlib.sha256(
        json.dumps({name: os.environ.get(name) for name in _BUILD_ENVIRONMENT}, sort_keys=True).encode()
    ).hexdigest()[:12]
    directory = _run_directory(tmp_path_factory) / f"native-default-build-{key}"
    with open(f"{directory}.lock", "w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        complete = directory / ".complete"
        if not complete.exists():
            directory.mkdir(exist_ok=True)
            result = subprocess.run(
                ["make", "-C", str(NATIVE), f"BUILD_DIR={directory}", "-j2", "all"],
                capture_output=True, text=True, timeout=300, check=False,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            complete.touch()
    return directory


def default_host_agent(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Return the agent executable of the shared default build."""

    return default_host_build(tmp_path_factory) / "host/c300x-agent-native"
