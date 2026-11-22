"""Execute the actual device transaction on copies of the original firmware only."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from test_c100x_qml_adapter import ROOT, builder
from test_native_routing_firmware_restore import FIRMWARE_ROOT, original

SCRIPT = ROOT / "native_agent/scripts/c100x_display.sh"


@pytest.fixture
def tree(tmp_path):
    original("c100x-1.5.8")
    firmware = FIRMWARE_ROOT / "rootfs-c100x-1.5.8/home/bticino"
    gui = tmp_path / "gui"
    gui.mkdir()
    stock = {}
    for name in ("main.qml", "MainPage.qml", "EventManager.qml"):
        shutil.copy2(firmware / "bin/gui/skins/default" / name, gui / name)
        (gui / name).chmod(0o640)
        stock[name] = (gui / name).read_bytes()
    for source, name in (("bin/gui/BtClass100", "binary"), ("bin/BtClass100_qws", "wrapper")):
        shutil.copy2(firmware / source, tmp_path / name)
    source = tmp_path / "source"
    builder.build(source)
    env = {**os.environ, "C100X_GUI_DIR": str(gui), "C100X_SOURCE_DIR": str(source),
           "C100X_BACKUP_DIR": str(tmp_path / "backup"), "C100X_GUI_BIN": str(tmp_path / "binary"),
           "C100X_GUI_WRAPPER": str(tmp_path / "wrapper"), "C100X_NO_REMOUNT": "1",
           "C100X_HOOKS_AWK": str(ROOT / "native_agent/scripts/c100x_hooks.awk"), "TMPDIR": str(tmp_path)}
    return tmp_path, gui, stock, env


def run(tree, action, success=True):
    result = subprocess.run(["sh", str(SCRIPT), action], env=tree[3], capture_output=True, text=True, timeout=20)
    assert (result.returncode == 0) == success, result.stdout + result.stderr
    return result


def assert_original(tree):
    _, gui, stock, _ = tree
    for name, content in stock.items():
        assert (gui / name).read_bytes() == content
        assert (gui / name).stat().st_mode & 0o777 == 0o640


def installed(tree):
    return next(tree[1].glob(".c100x-*"))


def test_roundtrip_identity_modes_idempotence_and_stock_handlers(tree):
    root, gui, stock, _ = tree
    assert json.loads(run(tree, "status").stdout)["state"] == "stock"
    assert not (root / "backup").exists(), "stock status must be read-only"
    run(tree, "apply")
    assert json.loads(run(tree, "status").stdout)["state"] == "installed"
    before = {name: (gui / name).read_bytes() for name in stock}
    run(tree, "apply")
    assert before == {name: (gui / name).read_bytes() for name in stock}
    assert before["EventManager.qml"] == stock["EventManager.qml"]
    assert b"Keys.forwardTo: [eventManager]" in before["main.qml"]
    assert b"Commissioning.Commissioned" in before["main.qml"]
    assert b'AudioState.RingtoneMute' in before["main.qml"]
    release = installed(tree)
    assert release.name == ".c100x-" + hashlib.sha256((root / "source/SHA256SUMS").read_bytes()).hexdigest()
    assert b"BtClass_qws" not in before["main.qml"]
    run(tree, "restore")
    assert_original(tree)
    run(tree, "restore")
    assert_original(tree)
    assert (root / "backup/main.qml").read_bytes() == stock["main.qml"]
    assert release.is_dir(), "do not remove assets still referenced by an old GUI process"


@pytest.mark.parametrize("part", ["binary", "wrapper", "gui/EventManager.qml", "gui/main.qml",
                                  "gui/MainPage.qml", "source/C100XBridge.qml"])
def test_rejects_unknown_or_corrupt_sources_without_target_mutation(tree, part):
    path = tree[0] / part
    path.write_bytes(path.read_bytes() + b"\ncorrupt\n")
    before = {name: (tree[1] / name).read_bytes() for name in tree[2]}
    run(tree, "apply", False)
    assert before == {name: (tree[1] / name).read_bytes() for name in tree[2]}


@pytest.mark.parametrize("part", ["gui/main.qml", "source/C100XBridge.qml", "backup/main.qml", "binary"])
def test_rejects_symlinks_and_preserves_referent(tree, part):
    run(tree, "apply")
    run(tree, "restore")
    path = tree[0] / part
    sentinel = tree[0] / "sentinel"
    sentinel.write_bytes(path.read_bytes())
    before = sentinel.read_bytes()
    path.unlink()
    path.symlink_to(sentinel)
    run(tree, "apply", False)
    assert sentinel.read_bytes() == before


def test_corrupt_backup_cannot_overwrite_target(tree):
    run(tree, "apply")
    main = (tree[1] / "main.qml").read_bytes()
    (tree[0] / "backup/main.qml").write_text("invalid")
    run(tree, "restore", False)
    assert (tree[1] / "main.qml").read_bytes() == main


@pytest.mark.parametrize("version", ["1.7.19", "2.0.2", "3.0.6"])
def test_foreign_gui_binary_is_rejected(tree, version):
    binary = FIRMWARE_ROOT / f"rootfs-{version}/home/bticino/bin/gui/BtClass"
    if not binary.is_file():
        pytest.skip("Optional comparison firmware absent")
    shutil.copy2(binary, tree[0] / "binary")
    run(tree, "apply", False)
    assert_original(tree)


@pytest.mark.parametrize("kind", ["duplicate", "traversal", "extra_file", "hardlink", "directory_link"])
def test_manifest_and_path_integrity(tree, kind):
    root, _, _, env = tree
    source = root / "source"
    manifest = source / "SHA256SUMS"
    if kind == "duplicate":
        manifest.write_text(manifest.read_text() + manifest.read_text().splitlines()[0] + "\n")
    elif kind == "traversal":
        manifest.write_text(manifest.read_text() + "0" * 64 + "  ../sentinel.qml\n")
    elif kind == "extra_file":
        (source / "extra.qml").write_text("unmanifested")
    elif kind == "hardlink":
        os.link(root / "gui/main.qml", root / "sentinel")
    else:
        (root / "linked-source").symlink_to(source, target_is_directory=True)
        env["C100X_SOURCE_DIR"] = str(root / "linked-source")
    run(tree, "apply", False)
    assert_original(tree)


def test_unknown_current_target_is_not_clobbered_during_recovery(tree):
    run(tree, "apply")
    main = tree[1] / "main.qml"
    main.write_text(main.read_text() + "\n// independent change\n")
    before = main.read_bytes()
    run(tree, "recover", False)
    assert main.read_bytes() == before


def test_original_firmware_flock_supports_readonly_inode_lock(tree):
    qemu = shutil.which("qemu-arm")
    if not qemu:
        pytest.skip("Optional ARM emulator absent")
    rootfs = FIRMWARE_ROOT / "rootfs-c100x-1.5.8"
    binary = rootfs / "usr/bin/flock.util-linux"
    if not binary.is_file():
        pytest.skip("Original flock unavailable")
    with (tree[0] / "binary").open("rb") as descriptor:
        result = subprocess.run([qemu, "-L", str(rootfs), str(binary), "-n", str(descriptor.fileno())],
                                pass_fds=(descriptor.fileno(),), capture_output=True, timeout=5)
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("damage", ["corrupt", "missing", "symlink"])
def test_restore_works_with_failed_adapter_without_trusting_or_deleting_it(tree, damage):
    run(tree, "apply")
    page = installed(tree) / "C100XBridge.qml"
    if damage == "corrupt":
        page.write_text("invalid QML")
    else:
        page.unlink()
        if damage == "symlink":
            page.symlink_to(tree[0] / "wrapper")
    run(tree, "restore")
    assert_original(tree)


def fault_mv(tree, mode):
    root, gui, _, env = tree
    tools = root / "tools"
    tools.mkdir()
    script = tools / "mv"
    script.write_text('''#!/bin/sh
for target do :; done
if [ "$target" = "$FAULT_TARGET" ] && [ ! -e "$FAULT_ONCE" ]; then
    : > "$FAULT_ONCE"
    case "$FAULT_MODE" in
        fail) exit 1 ;;
        kill_before) kill -KILL "$PPID"; exit 1 ;;
        kill_after) /bin/mv "$@"; kill -KILL "$PPID"; exit 1 ;;
    esac
fi
exec /bin/mv "$@"
''')
    script.chmod(0o700)
    env.update(PATH=str(tools) + os.pathsep + env["PATH"], FAULT_TARGET=str(gui / "main.qml"),
               FAULT_ONCE=str(root / "failed-once"), FAULT_MODE=mode)


def test_write_failure_rolls_back_both_stock_files(tree):
    fault_mv(tree, "fail")
    run(tree, "apply", False)
    assert_original(tree)
    assert (tree[0] / "backup/main.qml").exists()


@pytest.mark.parametrize("mode", ["kill_before", "kill_after"])
def test_power_loss_recovery_at_main_switch(tree, mode):
    fault_mv(tree, mode)
    run(tree, "apply", False)
    run(tree, "recover")
    assert_original(tree)


def test_partial_backup_creation_can_resume_from_verified_stock(tree):
    (tree[0] / "backup").mkdir()
    shutil.copy2(tree[1] / "main.qml", tree[0] / "backup/main.qml")
    run(tree, "apply")
    run(tree, "restore")
    assert_original(tree)


def test_concurrent_transaction_is_rejected(tree):
    run(tree, "apply")
    with (tree[0] / "binary").open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run(tree, "restore", False)
    run(tree, "restore")
    assert_original(tree)


def test_readonly_remount_failure_rolls_back_and_reports_failure(tree):
    root, _, _, env = tree
    tools = root / "tools"
    tools.mkdir()
    mount = tools / "mount"
    mount.write_text('''#!/bin/sh
if [ "$2" = remount,ro ] && [ ! -e "$MOUNT_FAILED" ]; then
    : > "$MOUNT_FAILED"
    exit 1
fi
exit 0
''')
    mount.chmod(0o700)
    env.update(PATH=str(tools) + os.pathsep + env["PATH"], C100X_NO_REMOUNT="0", MOUNT_FAILED=str(root / "mount-failed"))
    run(tree, "apply", False)
    assert_original(tree)
