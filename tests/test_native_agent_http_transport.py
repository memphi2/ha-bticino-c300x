"""Behavioral checks for production native HTTP transport code."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("harness", ["http_request_test.c", "http_file_test.c"])
def test_native_http_transport(tmp_path: Path, harness: str) -> None:
    binary = tmp_path / "http-request-test"
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-O2",
            "-D_DEFAULT_SOURCE",
            "-D_POSIX_C_SOURCE=200809L",
            "-ffunction-sections",
            "-fdata-sections",
            "-Wl,--gc-sections",
            "-pthread",
            "-o",
            str(binary),
            str(ROOT / "native_agent/test" / harness),
            str(ROOT / "native_agent/src/system_metrics.c"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([str(binary)], check=True, timeout=10)
