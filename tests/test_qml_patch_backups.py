"""Stock backups are checked before a restore or an apply uses them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_qml_patch_script import _gui_files, _run_qml_patch_raw, _write_original_gui

BACKUPS = [
    ("restore", "MainApp.qml"),
    ("restore", "HomePage.qml"),
    ("restore", "MemoPage.qml"),
    ("restore", "Components/Settings/GeneralsChoice.qml"),
    ("restore-all", "EventManager.qml"),
    ("media-user-label-restore", "Components/Settings/CallBlockPopup.qml"),
]


def _patched(tmp_path: Path) -> tuple[Path, Path]:
    gui, backup = tmp_path / "gui", tmp_path / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    for action in ("apply", "media-user-label-apply"):
        _run_qml_patch_raw(tmp_path, gui, backup, action).check_returncode()
    return gui, backup


@pytest.mark.parametrize("cut", ["empty", "half"])
@pytest.mark.parametrize(("action", "rel"), BACKUPS)
def test_a_restore_refuses_an_empty_or_cut_off_backup(
    tmp_path: Path, action: str, rel: str, cut: str,
) -> None:
    """The reviewer's case: an emptied MainApp.qml backup was copied over the
    stock file and reported as "original"."""

    gui, backup = _patched(tmp_path)
    original = (backup / rel).read_bytes()
    (backup / rel).write_bytes(b"" if cut == "empty" else original[: len(original) // 2])
    before = _gui_files(gui)
    result = _run_qml_patch_raw(tmp_path, gui, backup, action)
    assert result.returncode != 0 and result.stdout == ""
    # An empty settings backup was refused before; the message names the file.
    assert rel in result.stderr
    assert _gui_files(gui) == before
    status = json.loads(_run_qml_patch_raw(tmp_path, gui, backup, "status").stdout)
    assert status["state"] == "patched" and status["core_state"] == "patched"


def test_an_apply_refuses_a_cut_off_backup(tmp_path: Path) -> None:
    gui, backup = _patched(tmp_path)
    _run_qml_patch_raw(tmp_path, gui, backup, "restore-all").check_returncode()
    before = _gui_files(gui)
    original = (backup / "MainApp.qml").read_bytes()
    (backup / "MainApp.qml").write_bytes(original[: len(original) // 2])
    result = _run_qml_patch_raw(tmp_path, gui, backup, "apply")
    assert result.returncode != 0 and result.stdout == ""
    assert "Incomplete stock file" in result.stderr
    assert _gui_files(gui) == before
