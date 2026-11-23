"""Boot-bound C100X display trials, on copies of the original firmware only."""

import shutil
import subprocess

import pytest
from test_c100x_bundle_delivery import payload
from test_c100x_display_transaction import BOOT_ID, SCRIPT, assert_original, fault_mv, run
from test_c100x_display_transaction import tree as tree
from test_c100x_qml_adapter import ROOT

LATER_BOOT = "7d1e0b3c-55aa-4e0f-8b2d-0c9a6f1e2d34"


def reboot(tree, boot_id=LATER_BOOT):
    (tree[0] / "boot_id").write_text(boot_id + "\n")


def marker(tree, name):
    path = tree[0] / "backup" / name
    return path.read_text() if path.exists() else None


def test_prepare_records_its_boot_and_clears_a_stale_trial_mark(tree):
    (tree[0] / "backup").mkdir()
    (tree[0] / "backup/pending.trial-boot").write_text(LATER_BOOT + "\n")
    run(tree, "prepare")
    assert marker(tree, "pending.prepare-boot") == BOOT_ID + "\n"
    assert marker(tree, "pending.trial-boot") is None
    assert not list((tree[0] / "backup").glob("boot-stage.*"))


@pytest.mark.parametrize("boot_id", [None, "", "not-a-boot-id", BOOT_ID.upper(), BOOT_ID + "0",
                                     BOOT_ID.replace("-", "x")])
def test_prepare_refuses_without_a_valid_boot_id(tree, boot_id):
    if boot_id is None:
        (tree[0] / "boot_id").unlink()
    else:
        reboot(tree, boot_id)
    run(tree, "prepare", False)
    assert not (tree[0] / "backup/pending").exists()
    assert marker(tree, "pending.prepare-boot") is None
    assert_original(tree)


@pytest.mark.parametrize("action", ["recover", "restore"])
def test_ending_a_trial_clears_both_boot_marks(tree, action):
    run(tree, "prepare")
    (tree[0] / "backup/pending.trial-boot").write_text(LATER_BOOT + "\n")
    run(tree, action)
    assert_original(tree)
    assert marker(tree, "pending.prepare-boot") is None
    assert marker(tree, "pending.trial-boot") is None


def test_death_while_publishing_the_mark_leaves_no_partial_mark_or_trial(tree):
    fault_mv(tree, "kill_before")
    tree[3]["FAULT_TARGET"] = str(tree[0] / "backup/pending.prepare-boot")
    run(tree, "prepare", False)
    assert marker(tree, "pending.prepare-boot") is None
    assert not (tree[0] / "backup/pending").exists()
    assert_original(tree)
    run(tree, "prepare")
    assert marker(tree, "pending.prepare-boot") == BOOT_ID + "\n"


def test_mark_is_published_before_the_trial_journal(tree):
    fault_mv(tree, "kill_before")
    tree[3]["FAULT_TARGET"] = str(tree[0] / "backup/pending")
    run(tree, "prepare", False)
    assert marker(tree, "pending.prepare-boot") == BOOT_ID + "\n"
    assert not (tree[0] / "backup/pending").exists()
    assert_original(tree)


def trial_files(tree):
    return {name: (tree[1] / name).read_bytes() for name in tree[2]}


@pytest.mark.parametrize("sequence", ["prepare_boot", "first_boot", "trial_boot", "agent_restart_in_trial"])
def test_boot_rule_keeps_the_trial_in_its_own_boots(tree, sequence):
    run(tree, "prepare")
    trial = trial_files(tree)
    if sequence != "prepare_boot":
        reboot(tree)
    run(tree, "boot")
    if sequence == "agent_restart_in_trial":
        run(tree, "boot")
    assert (tree[0] / "backup/pending").is_dir()
    assert trial_files(tree) == trial
    expected = None if sequence == "prepare_boot" else LATER_BOOT + "\n"
    assert marker(tree, "pending.trial-boot") == expected
    assert marker(tree, "pending.prepare-boot") == BOOT_ID + "\n"


def test_boot_rule_rolls_back_in_a_further_boot(tree):
    run(tree, "prepare")
    reboot(tree)
    run(tree, "boot")
    reboot(tree, "2b8e4f6a-0c1d-4e2f-a3b4-c5d6e7f80912")
    run(tree, "boot")
    assert_original(tree)
    assert not (tree[0] / "backup/pending").exists()
    assert marker(tree, "pending.prepare-boot") is None
    assert marker(tree, "pending.trial-boot") is None
    release = (next(tree[0].glob("backup/trial-history.*/snapshot/release"))).read_text().strip()
    assert marker(tree, "last-result") == f"rolled_back {release}\n"


@pytest.mark.parametrize("damage", ["no_prepare_mark", "garbage_prepare_mark", "symlink_prepare_mark",
                                    "large_prepare_mark", "garbage_trial_mark", "symlink_trial_mark",
                                    "no_boot_id", "bad_boot_id"])
def test_boot_rule_recovers_when_the_marks_cannot_be_trusted(tree, damage):
    run(tree, "prepare")
    backup = tree[0] / "backup"
    target = backup / ("pending.prepare-boot" if "prepare" in damage else "pending.trial-boot")
    if damage == "no_prepare_mark":
        target.unlink()
    elif damage.startswith("garbage"):
        target.write_text("garbage\n")
    elif damage.startswith("symlink"):
        if target.exists():
            target.unlink()
        (tree[0] / "elsewhere").write_text(LATER_BOOT + "\n")
        target.symlink_to(tree[0] / "elsewhere")
        reboot(tree)
    elif damage == "large_prepare_mark":
        target.write_text(LATER_BOOT + "\n" + " " * 200 + "\n")
        reboot(tree)
    elif damage == "no_boot_id":
        (tree[0] / "boot_id").unlink()
    else:
        reboot(tree, "garbage")
    if damage.endswith("trial_mark"):
        reboot(tree)
    run(tree, "boot")
    assert_original(tree)
    assert not (backup / "pending").exists()
    result = "rolled_back" if damage.endswith("trial_mark") else "interrupted"
    assert marker(tree, "last-result").startswith(result + " .c100x-")


def test_boot_rule_without_a_trial_changes_nothing(tree):
    run(tree, "apply")
    installed = trial_files(tree)
    (tree[0] / "backup/pending.prepare-boot").write_text(LATER_BOOT + "\n")
    run(tree, "boot")
    assert trial_files(tree) == installed
    assert marker(tree, "pending.trial-boot") is None
    assert marker(tree, "last-result") is None


def test_stale_prepare_mark_from_an_interrupted_prepare_is_overwritten(tree):
    (tree[0] / "backup").mkdir()
    (tree[0] / "backup/pending.prepare-boot").write_text(LATER_BOOT + "\n")
    run(tree, "prepare")
    assert marker(tree, "pending.prepare-boot") == BOOT_ID + "\n"
    run(tree, "boot")
    assert (tree[0] / "backup/pending").is_dir()


@pytest.mark.parametrize("step", ["trial_mark", "rollback_main"])
def test_death_inside_the_boot_rule_is_decided_again_at_the_next_start(tree, step):
    run(tree, "prepare")
    trial = trial_files(tree)
    reboot(tree)
    fault_mv(tree, "kill_before")
    if step == "trial_mark":
        tree[3]["FAULT_TARGET"] = str(tree[0] / "backup/pending.trial-boot")
        run(tree, "boot", False)
        assert marker(tree, "pending.trial-boot") is None
        run(tree, "boot")
        assert marker(tree, "pending.trial-boot") == LATER_BOOT + "\n"
        assert trial_files(tree) == trial
        return
    run(tree, "boot")
    reboot(tree, "2b8e4f6a-0c1d-4e2f-a3b4-c5d6e7f80912")
    run(tree, "boot", False)
    assert (tree[0] / "backup/pending").is_dir()
    run(tree, "boot")
    assert_original(tree)


def test_payload_boot_rule_needs_no_package_sources(tree):
    directory, _, _, env = tree
    script = payload.build(directory / "payload.sh")
    content = script.read_bytes()
    needle = b"property bool c100xFullScreen: true"
    assert content.count(needle) == 1
    script.write_bytes(content.replace(needle, b"property bool c100xFullScreen: false"))
    env = {**env, "C100X_SOURCE_DIR": str(directory / "absent"),
           "C100X_IDENTITY_SCRIPT": str(directory / "absent"), "C100X_HOOKS_AWK": str(directory / "absent")}
    run(tree, "prepare")
    trial = trial_files(tree)
    for boot_id, kept in ((LATER_BOOT, True), ("2b8e4f6a-0c1d-4e2f-a3b4-c5d6e7f80912", False)):
        reboot(tree, boot_id)
        result = subprocess.run(["sh", str(script), "boot"], env=env, capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
        assert not list(directory.glob("c100x-payload.*"))
        if kept:
            assert trial_files(tree) == trial
    assert_original(tree)


FIRMWARE = ROOT.parent / "c300x-fwpatch/work/rootfs-c100x-1.5.8"
FIRMWARE_TOOLS = {
    "stat": "bin/stat.coreutils", "mktemp": "usr/bin/mktemp.coreutils", "sha256sum": "usr/bin/sha256sum.coreutils",
    "mv": "bin/mv.coreutils", "rm": "bin/rm.coreutils", "cp": "bin/cp.coreutils", "cat": "bin/cat.coreutils",
    "mkdir": "bin/mkdir.coreutils", "wc": "usr/bin/wc.coreutils", "awk": "bin/busybox.nosuid",
    "find": "bin/busybox.nosuid", "cmp": "bin/busybox.nosuid", "flock": "usr/bin/flock.util-linux",
}


@pytest.mark.parametrize("shell", ["bash", "busybox"])
def test_original_firmware_shell_and_tools_run_the_boot_rule(tree, shell):
    qemu = shutil.which("qemu-arm")
    if not qemu or not (FIRMWARE / "bin/bash.bash").is_file():
        pytest.skip("Optional ARM emulator or original firmware absent")
    run(tree, "prepare")
    trial = trial_files(tree)
    tools = tree[0] / "tools"
    # Only the libraries: the firmware's own /tmp symlink must not shadow test paths.
    sysroot = tree[0] / "sysroot"
    (sysroot / "usr").mkdir(parents=True)
    (sysroot / "lib").symlink_to(FIRMWARE / "lib", target_is_directory=True)
    (sysroot / "usr/lib").symlink_to(FIRMWARE / "usr/lib", target_is_directory=True)
    for name, binary in FIRMWARE_TOOLS.items():
        applet = f" {name}" if "busybox" in binary else ""
        (tools / name).write_text(f'#!/bin/sh\nexec "{qemu}" -L "{sysroot}" "{FIRMWARE / binary}"{applet} "$@"\n')
        (tools / name).chmod(0o700)
    command = [qemu, "-L", str(sysroot), *((str(FIRMWARE / "bin/bash.bash"),) if shell == "bash"
               else (str(FIRMWARE / "bin/busybox.nosuid"), "sh")), str(SCRIPT), "boot"]
    for boot_id in (LATER_BOOT, LATER_BOOT, "2b8e4f6a-0c1d-4e2f-a3b4-c5d6e7f80912"):
        reboot(tree, boot_id)
        result = subprocess.run(command, env=tree[3], capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        if boot_id == LATER_BOOT:
            assert trial_files(tree) == trial
            assert marker(tree, "pending.trial-boot") == LATER_BOOT + "\n"
    assert_original(tree)
    assert marker(tree, "last-result").startswith("rolled_back .c100x-")
