"""The 2.9.1 Display patch recovery never writes on a C100X.

qml_patch.sh refuses every action but status on a C100X before it looks at
a transaction. A leftover in the C300X format (here a v2 one from a dead
writer that would roll MainApp.qml back) is neither rolled back nor removed,
no new transaction folder appears, nothing is remounted and the root mark is
left as it was.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_qml_patch_script import _dead_pid, _run_qml_patch_raw, _write_original_gui


def _files(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("action", ["recover", "restore-all", "apply", "restore"])
def test_c100x_leftover_and_root_stay_untouched(tmp_path: Path, action: str) -> None:
    gui, backup = tmp_path / "gui", tmp_path / "backups"
    gui.mkdir()
    _write_original_gui(gui)
    pid = _dead_pid()
    leftover = gui / f".c300x-qml-transaction.{pid}"
    leftover.mkdir()
    (leftover / ".c300x-v2").write_text("")
    (leftover / ".c300x-files").write_text("+MainApp.qml\n")
    (leftover / "MainApp.qml").write_text("rolled back\n")
    marker = tmp_path / "BtClass100"
    marker.write_bytes(b"")
    tools = tmp_path / "bin"
    tools.mkdir()
    calls = tmp_path / "calls"
    for name in ("mount", "killall"):
        tool = tools / name
        tool.write_text(f'#!/bin/sh\necho "{name} $*" >> "{calls}"\n')
        tool.chmod(0o700)
    temp = tmp_path / "tmp"
    temp.mkdir()
    mark = temp / "c300x-qml-root-rw"
    mark.write_text(f"{pid} {gui}\n")
    before = _files(gui)
    env = {"C300X_QML_C100X_MARKER": str(marker), "TMPDIR": str(temp),
           "PATH": f"{tools}:/usr/bin:/bin"}

    result = _run_qml_patch_raw(tmp_path, gui, backup, action, no_remount=False, env_overrides=env)

    assert result.returncode == 3, result.stderr
    assert json.loads(result.stdout)["state"] == "unsupported_display"
    assert _files(gui) == before
    assert sorted(path.name for path in gui.glob(".c300x-qml-transaction.*")) == [leftover.name]
    assert not backup.exists()
    assert not calls.exists()
    assert mark.read_text() == f"{pid} {gui}\n"
    status = _run_qml_patch_raw(tmp_path, gui, backup, "status", no_remount=False, env_overrides=env)
    assert status.returncode == 0, status.stderr
    assert json.loads(status.stdout)["transaction"] == "pending"
    assert _files(gui) == before
    assert not calls.exists()
