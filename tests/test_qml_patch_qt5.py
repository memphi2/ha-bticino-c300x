"""The display patch on firmware 3.0.x, whose Qt 5 display writes handlers as functions."""

from __future__ import annotations

import re
from pathlib import Path

from tests.test_qml_patch_script import (
    _run_qml_patch,
    _run_qml_patch_raw,
    _write_original_gui,
)

VENDOR_FILES = (
    "EventManager.qml",
    "HomePage.qml",
    "MainApp.qml",
    "MemoPage.qml",
    "Components/Settings/GeneralsChoice.qml",
    "Components/Settings/CallBlockPopup.qml",
)
_HANDLER = re.compile(r"^(\s*)(on[A-Z]\w*):(?: (.*))?$")


def _qt5_form(text: str) -> str:
    """The same file as firmware 3.0.x ships it: QtQuick 2.7, handlers in Connections as functions."""

    lines = text.split("\n")
    if lines[0] == "import QtQuick 1.1":
        lines[0] = "import QtQuick 2.7"
    stack: list[bool] = []
    for index, line in enumerate(lines):
        match = _HANDLER.match(line)
        if stack and stack[-1] and match:
            indent, name, rest = match.groups()
            lines[index] = f"{indent}function {name} ()" + (f" {rest}" if rest else "")
        connections = bool(re.match(r"^\s*Connections\s*\{", line))
        for char in line:
            if char == "{":
                stack.append(connections)
                connections = False
            elif char == "}" and stack:
                stack.pop()
    return "\n".join(lines)


def _qt5_import_dir(tmp_path: Path) -> Path:
    import_dir = tmp_path / "qt5-files"
    import_dir.mkdir(parents=True, exist_ok=True)
    _write_original_gui(import_dir)
    for rel in VENDOR_FILES:
        path = import_dir / rel
        path.write_text(_qt5_form(path.read_text()))
    return import_dir


def _patched_tree(tmp_path: Path, name: str, *, qt5: bool) -> Path:
    root = tmp_path / name
    gui_dir, backup_dir = root / "gui", root / "backup"
    gui_dir.mkdir(parents=True)
    if qt5:
        result = _run_qml_patch_qt5_import(root, gui_dir, backup_dir, _qt5_import_dir(root))
        assert result["ok"] is True
    else:
        _write_original_gui(gui_dir)
    _run_qml_patch(root, gui_dir, backup_dir, "core-apply")
    _run_qml_patch(root, gui_dir, backup_dir, "apply")
    return gui_dir


def _run_qml_patch_qt5_import(root: Path, gui_dir: Path, backup_dir: Path, import_dir: Path) -> dict[str, object]:
    return _run_qml_patch(root, gui_dir, backup_dir, "qt5-import", extra_args=[str(import_dir)])


def test_fixture_conversion_reaches_every_connections_handler(tmp_path: Path) -> None:
    import_dir = _qt5_import_dir(tmp_path)
    event_manager = (import_dir / "EventManager.qml").read_text()
    assert event_manager.startswith("import QtQuick 2.7\n")
    assert "        function onCallEnded () {" in event_manager
    assert "        onCallEnded:" not in event_manager


def test_qt5_files_get_the_same_patch_as_the_qt4_files(tmp_path: Path) -> None:
    qt4 = _patched_tree(tmp_path, "qt4", qt5=False)
    qt5 = _patched_tree(tmp_path, "qt5", qt5=True)
    qt4_files = sorted(str(path.relative_to(qt4)) for path in qt4.rglob("*") if path.is_file())
    qt5_files = sorted(str(path.relative_to(qt5)) for path in qt5.rglob("*") if path.is_file())
    assert qt5_files == qt4_files
    for rel in qt4_files:
        assert (qt5 / rel).read_text() == (qt4 / rel).read_text(), rel


def test_qt5_import_keeps_a_working_copy_that_is_already_there(tmp_path: Path) -> None:
    gui_dir, backup_dir = tmp_path / "gui", tmp_path / "backup"
    gui_dir.mkdir()
    (gui_dir / "EventManager.qml").write_text("import QtQuick 1.1\n// patched before\n")
    _run_qml_patch_qt5_import(tmp_path, gui_dir, backup_dir, _qt5_import_dir(tmp_path))
    assert (gui_dir / "EventManager.qml").read_text() == "import QtQuick 1.1\n// patched before\n"
    assert (gui_dir / "HomePage.qml").read_text().startswith("import QtQuick 1.1\n")


def test_qt5_import_leaves_functions_outside_connections_alone(tmp_path: Path) -> None:
    import_dir = _qt5_import_dir(tmp_path)
    home = import_dir / "HomePage.qml"
    home.write_text(home.read_text().replace("Page {\n", "Page {\n    function onlyHere() { return 1 }\n    function onHelper () {\n        return 2\n    }\n", 1))
    gui_dir = tmp_path / "gui"
    gui_dir.mkdir()
    _run_qml_patch_qt5_import(tmp_path, gui_dir, tmp_path / "backup", import_dir)
    text = (gui_dir / "HomePage.qml").read_text()
    assert "    function onHelper () {\n" in text
    assert "    function onlyHere() { return 1 }\n" in text


def test_qt5_import_refuses_an_incomplete_set_of_files(tmp_path: Path) -> None:
    import_dir = _qt5_import_dir(tmp_path)
    (import_dir / "MemoPage.qml").unlink()
    gui_dir = tmp_path / "gui"
    gui_dir.mkdir()
    result = _run_qml_patch_raw(tmp_path, gui_dir, tmp_path / "backup", "qt5-import", extra_args=[str(import_dir)])
    assert result.returncode != 0
    assert "Missing Qt 5 display file: MemoPage.qml" in result.stderr
    assert not any(gui_dir.iterdir())
