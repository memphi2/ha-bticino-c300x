"""A forwarding label of an older release is renewed by the display apply.

The label is written once, when the media user is set up. A label that an
older release wrote (without the Spanish texts) must not count as current:
the status reports it as not patched, and the next core or full apply, as
the agent-update Repair runs them, writes the current one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import test_qml_patch_script as patch
from test_c300x_same_as_2_10_0 import without_spanish

POPUP = "Components/Settings/CallBlockPopup.qml"


def _station(tmp_path: Path) -> tuple[Path, Path, bytes]:
    gui, backups = tmp_path / "gui", tmp_path / "backups"
    gui.mkdir()
    patch._write_original_gui(gui)
    patch._run_qml_patch(tmp_path, gui, backups, "media-user-label-apply")
    return gui, backups, (gui / POPUP).read_bytes()


def _make_label_of_2_10_0(gui: Path) -> None:
    current = (gui / POPUP).read_bytes()
    (gui / POPUP).write_bytes(without_spanish(current))
    assert (gui / POPUP).read_bytes() != current


def test_the_status_does_not_take_an_older_label_for_the_current_one(tmp_path: Path) -> None:
    gui, backups, _current = _station(tmp_path)
    assert patch._run_qml_patch(tmp_path, gui, backups, "status")["media_user_label_patched"] is True
    _make_label_of_2_10_0(gui)
    status = patch._run_qml_patch(tmp_path, gui, backups, "status")
    assert status["media_user_label_state"] == "partial"
    assert status["media_user_label_patched"] is None


@pytest.mark.parametrize("action", ["core-apply", "apply"])
def test_the_display_apply_renews_an_older_label(tmp_path: Path, action: str) -> None:
    gui, backups, current = _station(tmp_path)
    _make_label_of_2_10_0(gui)
    status = patch._run_qml_patch(tmp_path, gui, backups, action)
    assert status["media_user_label_state"] == "patched"
    assert (gui / POPUP).read_bytes() == current


def test_the_display_apply_leaves_a_current_label_alone(tmp_path: Path) -> None:
    gui, backups, current = _station(tmp_path)
    patch._run_qml_patch(tmp_path, gui, backups, "core-apply")
    status = patch._run_qml_patch(tmp_path, gui, backups, "core-apply")
    assert status["changed_files"] == 0
    assert (gui / POPUP).read_bytes() == current


def test_the_display_apply_sets_no_label_the_user_did_not_ask_for(tmp_path: Path) -> None:
    gui, backups = tmp_path / "gui", tmp_path / "backups"
    gui.mkdir()
    patch._write_original_gui(gui)
    for action in ("core-apply", "apply"):
        status = patch._run_qml_patch(tmp_path, gui, backups, action)
        assert status["media_user_label_state"] == "original"
    assert (gui / POPUP).read_text() == patch.ORIGINAL_CALL_BLOCK_POPUP


# The real skins: 1.7.19 and 2.0.2 from C300X_FIRMWARE_WORK, 3.0.6 from the
# files inside its BtClass (C300X_QT5_SKIN, scripts/extract_btclass_resources.py),
# imported as the agent does. Private firmware files; the tests skip without them.
@pytest.mark.parametrize("firmware", ["1.7.19", "2.0.2", "3.0.6"])
def test_the_label_on_the_real_skin_is_set_renewed_and_removed(tmp_path: Path, firmware: str) -> None:
    import shutil

    from test_c300x_same_as_2_10_0 import _skin

    from tests.test_qml_patch_qt5_overlay import LABELS, forwarding_texts

    skin = _skin(firmware)
    if skin is None or not skin.is_dir():
        pytest.skip(f"firmware {firmware} skin not available (C300X_FIRMWARE_WORK, C300X_QT5_SKIN)")
    gui, backups = tmp_path / "gui", tmp_path / "backups"
    if firmware == "3.0.6":
        gui.mkdir()
        patch._run_qml_patch(tmp_path, gui, backups, "qt5-import", extra_args=[str(skin)])
    else:
        shutil.copytree(skin, gui)
    stock = (gui / POPUP).read_bytes()
    status = patch._run_qml_patch(tmp_path, gui, backups, "media-user-label-apply")
    assert (status["media_user_label_state"], status["media_user_label_patched"]) == ("patched", True)
    current = (gui / POPUP).read_bytes()
    assert forwarding_texts(current.decode()) == LABELS
    for action in ("core-apply", "apply"):
        _make_label_of_2_10_0(gui)
        assert patch._run_qml_patch(tmp_path, gui, backups, "status")["media_user_label_state"] == "partial"
        assert patch._run_qml_patch(tmp_path, gui, backups, action)["media_user_label_state"] == "patched"
        assert (gui / POPUP).read_bytes() == current
    status = patch._run_qml_patch(tmp_path, gui, backups, "media-user-label-restore")
    assert status["media_user_label_state"] == "original"
    assert (gui / POPUP).read_bytes() == stock
