"""Run the real memo library against the stock memo model.

The stock model's remove() is the stock delete path: it deletes the memo on
the station. The memo page sync must therefore only mirror deletions the agent
itself reports, never treat a short or empty list as "these memos are gone".
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_memo_sync_only_removes_memos_the_agent_deleted() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    result = subprocess.run(
        [node, str(ROOT / "tests/qml/memos_sync.cjs")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "removes only agent-deleted memos passed" in result.stdout


def test_memo_sync_with_firmware_qt4() -> None:
    from scripts.setup_qt4_runtime import probe_command, runtime_paths

    paths = runtime_paths()
    if paths is None:
        pytest.skip("Local firmware Qt 4 runtime not configured")
    run = subprocess.run(
        probe_command(paths, ROOT / "tests/qml/memos_sync_qt4.qml"),
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert "QT4_COMPONENT_CREATED" in run.stdout, run.stdout + run.stderr
    assert "QT4_MEMO_SYNC_PASS" in run.stdout + run.stderr
