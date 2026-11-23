"""Boot-bound C100X display trials, on copies of the original firmware only."""

import pytest
from test_c100x_display_transaction import BOOT_ID, assert_original, fault_mv, run
from test_c100x_display_transaction import tree as tree

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
