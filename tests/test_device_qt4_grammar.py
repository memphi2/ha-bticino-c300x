"""Display files must stay inside the QML grammar of the device's Qt 4.8.

The local render harness runs Qt 6, which accepts more. Two forms that Qt 6
takes and the device rejects with "Syntax error", so the whole file and the
page that loads it stay blank:

* ``property int name: { ...statements... }``: a property declaration takes
  an expression only, so the brace starts an object literal there.
* ``name: for (...) ...`` and other statements as a binding: a binding takes
  a block, an expression or an ``if`` only.

2.6.0 shipped the first form in C300XEnergy.qml and the energy page no
longer loaded.
"""

import re
from pathlib import Path

import pytest

DEVICE_QML = Path(__file__).resolve().parents[1] / "device_qml"
FILES = sorted(DEVICE_QML.glob("*.qml"))
PROPERTY_BLOCK = re.compile(r"^\s*(?:default\s+|readonly\s+)?property\s+[\w<>.]+\s+\w+\s*:\s*\{")
STATEMENT_BINDING = re.compile(r"^\s*[A-Za-z_][\w.]*\s*:\s*(?:for|while|do|switch|var|return|try|throw)\b")


def _violations(text: str) -> list[str]:
    return [
        f"{number}: {line.strip()}"
        for number, line in enumerate(text.splitlines(), 1)
        if PROPERTY_BLOCK.match(line) or STATEMENT_BINDING.match(line)
    ]


def test_the_check_knows_both_forms():
    assert _violations("    property int base: {\n        return 0\n    }\n") == ["1: property int base: {"]
    assert _violations("    onClicked: for (var i = 0; i < 2; i++) run(i)\n")
    assert not _violations(
        "    property variant hours: ({})\n"
        "    property int step: Math.max(1, count)\n"
        "    onClicked: if (ready) run()\n"
        "    width: {\n        return 4\n    }\n"
    )


@pytest.mark.parametrize("path", FILES, ids=lambda path: path.name)
def test_display_file_uses_only_qt4_binding_forms(path):
    assert len(FILES) >= 10
    assert not _violations(path.read_text(encoding="utf-8"))


def test_display_files_compile_on_the_device_qt():
    """Compile the packaged files with the device's own Qt 4.8, when it is at hand.

    Needs an ARM emulator, an unpacked device system image, a compile probe
    and copies of the device's skin directory and of placeholder modules for
    its compiled-in imports. None of these belong in the repository.
    """

    import os
    import shutil
    import subprocess
    import tempfile

    from test_device_file_strip import strip

    names = ("QEMU", "ROOTFS", "COMPILE_PROBE", "COMPILE_IMPORTS", "GUI")
    paths = [os.environ.get("C300X_QT4_" + name) for name in names]
    if not all(paths):
        pytest.skip("Optional Qt 4 runtime requires C300X_QT4_" + "/".join(names))
    qemu, rootfs, probe, imports, gui = paths
    # The system image links /tmp elsewhere, so the emulator cannot resolve imports below it.
    work = Path(tempfile.mkdtemp(prefix="c300x-qt4-compile-", dir="/var/tmp"))
    try:
        shutil.copytree(gui, work, dirs_exist_ok=True)
        shutil.copytree(imports, work, dirs_exist_ok=True)
        for relative in strip.DEVICE_SOURCE_FILES:
            strip.strip_device_file(strip.DEVICE_SOURCE_DIR / relative, work / relative)
        failed = {}
        for path in FILES:
            result = subprocess.run(
                [qemu, "-L", rootfs, "-E", f"LD_LIBRARY_PATH={rootfs}/usr/lib:{rootfs}/lib",
                 probe, str(work / path.name), str(work)],
                capture_output=True, text=True, timeout=120, check=False,
            )
            if "compile_failed=0" not in result.stdout:
                failed[path.name] = (result.stdout + result.stderr)[-400:]
        assert not failed
    finally:
        shutil.rmtree(work, ignore_errors=True)
