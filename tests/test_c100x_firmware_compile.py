"""Compile generated C100X QML with original ARM Qt 5.10.1, not host Qt.

Optional private input: C100X_QT5_FIRMWARE, or rootfs-c100x-1.5.8 beneath
C300X_FIRMWARE_WORK (default: sibling c300x-fwpatch/work). Scratch files live
in /var/tmp; case artifacts/logs are retained in pytest temporary directories.
Only public QtQuick imports are copied; no vendor skin, vendor/platform
plugin, substitutes, QML instances or GUI are loaded. QtQuick still links its
firmware GLES/GAL/VSC dependencies. This checks syntax/type APIs, not binding
evaluation, rendering, hardware keys, vendor hook integration or device runtime.
"""

import importlib.util
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def firmware_workspace():
    # qemu -L observes the firmware's /tmp -> /var/tmp symlink during Qt's
    # canonicalization. Use the same absolute directory in host and guest.
    with tempfile.TemporaryDirectory(prefix="c100x-firmware-compile-", dir="/var/tmp") as directory:
        yield Path(directory)


@pytest.fixture
def firmware_case(firmware_workspace, tmp_path):
    case = firmware_workspace / tmp_path.name
    case.mkdir()
    yield case
    shutil.copytree(case, tmp_path, dirs_exist_ok=True)


@pytest.fixture(scope="module")
def firmware_probe(firmware_workspace):
    rootfs = Path(os.environ.get(
        "C100X_QT5_FIRMWARE",
        Path(os.environ.get("C300X_FIRMWARE_WORK", ROOT.parent / "c300x-fwpatch/work"))
        / "rootfs-c100x-1.5.8",
    )).resolve()
    if not rootfs.is_dir():
        if "C100X_QT5_FIRMWARE" in os.environ:
            pytest.fail(f"Configured C100X firmware unavailable: {rootfs}")
        pytest.skip(f"Private C100X firmware unavailable: {rootfs}")
    for tool in ("arm-linux-gnueabihf-gcc", "qemu-arm"):
        if shutil.which(tool) is None:
            pytest.skip(f"Firmware compile probe requires {tool}")
    for name in ("Core", "Qml", "Quick", "Gui"):
        assert (rootfs / f"usr/lib/libQt5{name}.so.5.10.1").is_file()
        assert (rootfs / f"usr/lib/libQt5{name}.so.5").resolve() == (
            rootfs / f"usr/lib/libQt5{name}.so.5.10.1"
        )
    work = firmware_workspace
    imports = work / "imports"
    # These are unmodified firmware Qt plugins, not mock/vendor QML modules.
    for module in ("QtQuick.2", "QtQuick/Window.2", "QtQml/Models.2"):
        shutil.copytree(rootfs / "usr/lib/qt5/qml" / module, imports / module)
    probe = work / "compile-probe"
    compiled = subprocess.run([
        "arm-linux-gnueabihf-gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
        "-D_GNU_SOURCE", str(ROOT / "tests/qml/c100x_compile_probe.c"),
        str(ROOT / "native_agent/src/arm_start.S"), "-nostartfiles",
        f"-Wl,-rpath-link,{rootfs}/lib", f"-L{rootfs}/lib",
        "-l:libpthread.so.0", "-l:libdl.so.2", "-l:libc.so.6",
        "-l:ld-linux-armhf.so.3", "-o", str(probe),
    ], capture_output=True, text=True, timeout=30)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr

    def run(files, directory):
        # Do not inherit host Qt, loader, display or QEMU configuration.
        env = {"PATH": os.environ["PATH"], "HOME": str(work), "LANG": "C",
               "XDG_CACHE_HOME": str(work / "cache"), "XDG_CONFIG_HOME": str(work / "config")}
        result = subprocess.run([
            "qemu-arm", "-L", str(rootfs),
            "-E", f"LD_LIBRARY_PATH={rootfs}/usr/lib:{rootfs}/lib",
            "-E", "QML_DISABLE_DISK_CACHE=1", "-E", f"QML2_IMPORT_PATH={imports}",
            # Deliberately nonexistent: compile-only must not open a platform.
            "-E", "QT_QPA_PLATFORM=c100x_compile_only_no_platform",
            str(probe), str(imports), *(str(path) for path in files),
        ], env=env, cwd=directory, capture_output=True, text=True, timeout=120)
        (directory / "firmware-compile.log").write_text(result.stdout + result.stderr)
        assert "FIRMWARE_QT_VERSION=5.10.1\n" in result.stdout, result.stdout + result.stderr
        assert "MODE=compile-only\n" in result.stdout
        libraries = [line.removeprefix("LOADED_LIBRARY=") for line in result.stdout.splitlines()
                     if line.startswith("LOADED_LIBRARY=")]
        for name in ("Core", "Qml", "Quick", "Gui"):
            assert any(Path(path).resolve() == rootfs / f"usr/lib/libQt5{name}.so.5.10.1"
                       for path in libraries), result.stdout + result.stderr
        assert str(imports / "QtQuick.2/libqtquick2plugin.so") in libraries
        assert not any("/home/bticino/" in path or "/platforms/" in path for path in libraries)
        return result

    return run


def test_generated_c100x_pages_compile_with_firmware_qt5101(firmware_probe, firmware_case):
    spec = importlib.util.spec_from_file_location("c100x_builder", ROOT / "scripts/c100x_qml_builder.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    generated = firmware_case / "generated"
    builder.build(generated)
    files = sorted(generated.glob("*.qml"))
    assert {path.name for path in files} == set(builder.PAGES) | {
        path.name for path in (ROOT / "device_qml/c100x").glob("*.qml")
    }
    # Fail before loading any newly introduced vendor/external module.
    for path in files:
        for imported in re.findall(r"^\s*import\s+(.+)$", path.read_text(), re.MULTILINE):
            assert imported == "QtQuick 2.7" or re.fullmatch(
                r'"js/[a-zA-Z0-9_]+\.js" as [a-zA-Z0-9_]+', imported
            ), (path, imported)
    before = {path: path.read_bytes() for path in generated.rglob("*") if path.is_file()}
    result = firmware_probe(files, firmware_case)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "COMPILE_FAILURES=0\n" in result.stdout
    assert result.stdout.count("COMPILE_STATUS=1 FILE=") == len(files)
    assert before == {path: path.read_bytes() for path in generated.rglob("*") if path.is_file()}


@pytest.mark.parametrize(("name", "source", "diagnostic"), [
    ("Syntax", "import QtQuick 2.7\nItem { property int broken: }", "Expected token"),
    ("Version", "import QtQuick 2.11\nItem {}", 'module "QtQuick" version 2.11 is not installed'),
    ("Property", "import QtQuick 2.7\nItem { notAQtQuickProperty: true }", "non-existent property"),
])
def test_firmware_probe_rejects_invalid_qml(firmware_probe, firmware_case, name, source, diagnostic):
    valid = firmware_case / "Valid.qml"
    valid.write_text('import QtQuick 2.7\nItem { Component.onCompleted: { throw new Error("MUST_NOT_INSTANTIATE") } }')
    invalid = firmware_case / f"{name}.qml"
    invalid.write_text(source)
    result = firmware_probe([valid, invalid], firmware_case)
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"COMPILE_STATUS=1 FILE={valid}\n" in result.stdout
    assert f"COMPILE_STATUS=3 FILE={invalid}\n" in result.stdout
    assert "COMPILE_FAILURES=1\n" in result.stdout
    assert diagnostic in result.stderr
    assert "MUST_NOT_INSTANTIATE" not in result.stderr
