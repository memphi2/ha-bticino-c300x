"""The firmware root file system check that backs multi-firmware support."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROUTING = b"routing-build"
ROUTING_SHA = hashlib.sha256(ROUTING).hexdigest()


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_firmware_rootfs", ROOT / "scripts" / "check_firmware_rootfs.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _rootfs(root: Path, checker: ModuleType, version: str = "1.7.19") -> Path:
    for library in checker.LIBRARIES:
        path = root / library
        path.parent.mkdir(parents=True, exist_ok=True)
        real = path.with_name(path.name + ".real")
        real.write_bytes(library.encode())
        # Absolute links, as in an extracted device image.
        path.symlink_to("/" + real.relative_to(root).as_posix())
    gui = root / checker.GUI_TREE / "default"
    (gui / "js").mkdir(parents=True)
    (gui / "MainApp.qml").write_text("Item {}\n", encoding="utf-8")
    (gui / "js" / "logic.js").write_text("var a = 1\n", encoding="utf-8")
    programs = root / checker.VENDOR_PROGRAMS
    (programs / "bt_answering_machine").write_bytes(ROUTING)
    (programs / "bt_av_media").write_bytes(b"media")
    info = root / checker.FIRMWARE_INFO
    info.parent.mkdir(parents=True)
    info.write_text(f"<a><ver_webserver> {version} </ver_webserver></a>", encoding="utf-8")
    (root / "usr/bin").mkdir(parents=True, exist_ok=True)
    (root / "bin").mkdir(exist_ok=True)
    (root / "bin/busybox").write_bytes(b"busybox")
    for tool in checker.TOOLS:
        (root / "usr/bin" / tool).symlink_to("/bin/busybox")
    return root


def test_identical_dependencies_pass_and_changed_programs_are_listed(tmp_path: Path) -> None:
    checker = _load()
    baseline = _rootfs(tmp_path / "a", checker)
    candidate = _rootfs(tmp_path / "b", checker, "2.0.2")
    (candidate / checker.VENDOR_PROGRAMS / "bt_av_media").write_bytes(b"rebuilt")

    failures, notes = checker.compare(baseline, candidate, {ROUTING_SHA})

    assert failures == []
    assert "baseline firmware: 1.7.19" in notes
    assert "candidate firmware: 2.0.2" in notes
    assert notes[-1] == "vendor programs to cover in the device test: bt_av_media"


@pytest.mark.parametrize("change", [
    "library", "library_missing", "gui_changed", "gui_added", "gui_removed",
    "gui_missing", "tool", "routing", "routing_missing", "version",
])
def test_each_dependency_difference_fails(tmp_path: Path, change: str) -> None:
    checker = _load()
    baseline = _rootfs(tmp_path / "a", checker)
    candidate = _rootfs(tmp_path / "b", checker)
    gui = candidate / checker.GUI_TREE / "default"
    library = candidate / checker.LIBRARIES[0]
    routing = candidate / checker.ROUTING_TARGET
    if change == "library":
        library.with_name(library.name + ".real").write_bytes(b"other")
    elif change == "library_missing":
        library.unlink()
    elif change == "gui_changed":
        (gui / "MainApp.qml").write_text("Item { id: a }\n", encoding="utf-8")
    elif change == "gui_added":
        (gui / "New.qml").write_text("Item {}\n", encoding="utf-8")
    elif change == "gui_removed":
        (gui / "js" / "logic.js").unlink()
    elif change == "gui_missing":
        for path in sorted(gui.parent.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        gui.parent.rmdir()
    elif change == "tool":
        (candidate / "usr/bin/setsid").unlink()
    elif change == "routing":
        routing.write_bytes(b"unknown build")
    elif change == "routing_missing":
        routing.unlink()
    elif change == "version":
        (candidate / checker.FIRMWARE_INFO).write_text("<a/>", encoding="utf-8")

    failures, _notes = checker.compare(baseline, candidate, {ROUTING_SHA})

    assert len(failures) == 1, failures


def test_links_never_leave_the_root_file_system(tmp_path: Path) -> None:
    checker = _load()
    root = tmp_path / "root"
    (root / "lib").mkdir(parents=True)
    outside = tmp_path / "libc.so.6"
    outside.write_bytes(b"host file")
    (root / "lib/libc.so.6").symlink_to("../../libc.so.6")
    (root / "lib/loop").symlink_to("loop")

    assert checker.resolve(root, "lib/libc.so.6") is None
    assert checker.resolve(root, "lib/loop") is None

    # A linked folder stays inside the root as well.
    (tmp_path / "hostlib").mkdir()
    (tmp_path / "hostlib" / "libm.so.6").write_bytes(b"host file")
    (root / "usr").mkdir()
    (root / "usr/lib").symlink_to(str(tmp_path / "hostlib"))
    assert checker.resolve(root, "usr/lib/libm.so.6") is None
    (root / "real").mkdir()
    (root / "real/libm.so.6").write_bytes(b"device file")
    (root / "alias").symlink_to("/real")
    assert checker.resolve(root, "alias/libm.so.6") == root / "real/libm.so.6"


def test_a_tool_whose_link_target_is_absent_counts_as_missing(tmp_path: Path) -> None:
    checker = _load()
    baseline = _rootfs(tmp_path / "a", checker)
    candidate = _rootfs(tmp_path / "b", checker)
    (candidate / "bin/busybox").unlink()
    (candidate / "usr/bin/setsid").unlink()
    (candidate / "usr/bin/setsid").write_bytes(b"tool")

    failures, _notes = checker.compare(baseline, candidate, {ROUTING_SHA})

    assert len(failures) == len(checker.TOOLS) - 1
    assert all("device tool" in failure for failure in failures)


def test_routing_hashes_come_from_the_patch_builder() -> None:
    checker = _load()
    builder = (ROOT / "scripts" / "device_routing_builder.py").read_text(encoding="utf-8")

    hashes = checker.known_routing_hashes()

    assert len(hashes) == 3
    assert all(len(value) == 64 and value in builder for value in hashes)
