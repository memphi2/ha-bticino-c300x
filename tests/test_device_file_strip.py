"""Packaged display files lose comments and padding, never behaviour.

The display's QML and JS are written to the device as packaged. Nothing here
can execute QtQuick 1.1, so the strip is deliberately line based and its proof
is threefold: the kept lines are exactly the source's code lines, the stripped
JS still passes the executable display harness, and the on-device patch script
still installs and recognises the stripped files.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "device_qml"


def _load(name: str) -> ModuleType:
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        spec = importlib.util.spec_from_file_location(
            f"{name}_under_test", ROOT / "scripts" / f"{name}.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(ROOT / "scripts"))


strip = _load("device_file_strip")


def test_strip_removes_only_comment_lines_blank_lines_and_padding() -> None:
    source = (
        ".pragma library\n"
        "\n"
        "// explains the next line\n"
        "var url = \"http://127.0.0.1:8090\"   \n"
        "function f() {\n"
        "    // indented comment\n"
        "\n"
        "    return \"a // b\" + /[^0-9]/g.source  // trailing stays\n"
        "}\n"
    )

    assert strip.strip_device_source(source) == (
        ".pragma library\n"
        "var url = \"http://127.0.0.1:8090\"\n"
        "function f() {\n"
        "return \"a // b\" + /[^0-9]/g.source  // trailing stays\n"
        "}\n"
    )
    assert strip.strip_device_source("") == ""
    assert strip.strip_device_source("\n  // only a comment\n") == ""


@pytest.mark.parametrize(
    "source",
    [
        "var a = 1 /* inline */\n",
        "/*\n hidden()\n*/\n",
        "var text = \"first \\\n   second\"\n",
    ],
)
def test_strip_refuses_what_a_line_based_pass_cannot_judge(source: str) -> None:
    """A block comment or continued string must fail packaging, not be guessed."""

    with pytest.raises(strip.DeviceFileStripError):
        strip.strip_device_source(source, name="probe.js")


@pytest.mark.parametrize("relative", strip.DEVICE_SOURCE_FILES)
def test_every_display_file_keeps_exactly_its_code_lines(relative: str) -> None:
    source = (SOURCE_DIR / relative).read_text(encoding="utf-8")
    stripped = strip.strip_device_source(source, name=relative)

    expected = [
        line.strip()
        for line in source.splitlines()
        if line.strip() and not line.strip().startswith("//")
    ]
    assert stripped.splitlines() == expected
    assert stripped.endswith("\n")
    assert len(stripped) < len(source)
    # Device files are plain ASCII; the strip must not change that.
    assert stripped.isascii()
    if relative.endswith(".js"):
        assert stripped.startswith(".pragma library\n")


def test_strip_covers_every_file_the_bundle_stages() -> None:
    """A display file added to the bundle must not ship unstripped."""

    stager_source = (ROOT / "scripts" / "stage_device_agent_bundle.py").read_text(
        encoding="utf-8"
    )
    on_disk = sorted(
        str(path.relative_to(SOURCE_DIR))
        for path in SOURCE_DIR.rglob("*")
        if path.suffix in strip.STRIPPED_SUFFIXES
    )
    assert sorted(strip.DEVICE_SOURCE_FILES) == on_disk
    assert "strip_device_file(" in stager_source
    assert "device_qml" in stager_source


@pytest.mark.parametrize("harness", ["dashboard_controls.cjs", "alarm_controls.cjs"])
def test_stripped_display_code_passes_the_executable_harness(
    tmp_path: Path, harness: str
) -> None:
    """The stripped JS libraries must behave exactly like their sources.

    The harness finds the page functions inside the QML by their indentation,
    so it keeps reading the QML sources; only the libraries are swapped.
    """

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available")
    strip.strip_device_tree(tmp_path)

    result = subprocess.run(
        [node, str(ROOT / "tests" / "qml" / harness)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "C300X_DEVICE_JS_ROOT": str(tmp_path / "js")},
    )

    assert result.returncode == 0, result.stderr
    assert "passed" in result.stdout


def test_stripped_files_install_through_the_device_patch_script(tmp_path: Path) -> None:
    """The on-device script recognises its own files by fixed code markers."""

    patch_tests = _load_test_module("test_qml_patch_script")
    source_dir = tmp_path / "source"
    strip.strip_device_tree(source_dir)
    gui_dir = tmp_path / "gui"
    backup_dir = tmp_path / "backups"
    gui_dir.mkdir()
    patch_tests._write_original_gui(gui_dir)

    status = patch_tests._run_qml_patch(
        tmp_path, gui_dir, backup_dir, "apply", source_dir=source_dir
    )

    assert status["state"] == "patched"
    assert status["core_state"] == "patched"
    patch_tests._assert_complete_gui_patch(gui_dir, source_dir=source_dir)
    again = patch_tests._run_qml_patch(
        tmp_path, gui_dir, backup_dir, "apply", source_dir=source_dir
    )
    assert again["changed_files"] == 0


def _load_test_module(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"{name}_helpers", ROOT / "tests" / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
