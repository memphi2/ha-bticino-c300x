from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_frontend_node_tests_pass() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    test_files = sorted(ROOT.glob("tests/frontend/*.test.mjs"))

    result = subprocess.run(
        [
            node,
            "--test",
            *(str(path.relative_to(ROOT)) for path in test_files),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
