"""A Qt 5 write cut off for good is finished by the next run, activation included."""

import shutil

from tests import test_qml_patch_qt5_overlay as overlay
from tests.test_qml_patch_qt5_overlay import programs as programs
from tests.test_qml_patch_qt5_transactions import snapshot


def _killed_after_publishing(device, monkeypatch):
    source = overlay.SCRIPT.read_text()
    start, end = source.index("reload_gui() {"), source.index("\nremount_rw() {")
    script = device.root / "killed.sh"
    script.write_text(source[:start] + "reload_gui() { kill -KILL $$; }\n" + source[end:])
    script.chmod(0o700)
    monkeypatch.setattr(overlay, "SCRIPT", script)


def _transactions(device):
    return sorted(device.gui.glob(".c300x-qml-transaction.*"))


def test_a_write_killed_after_publishing_is_rolled_back_with_its_activation(tmp_path, programs, monkeypatch):
    device = overlay.Device(tmp_path, programs)
    device.ok("apply")
    before = snapshot(device)
    script = overlay.SCRIPT
    _killed_after_publishing(device, monkeypatch)
    assert device.run("media-user-label-apply").returncode != 0
    [leftover] = _transactions(device)
    assert (leftover / ".qt5/.published").exists()
    assert snapshot(device) != before
    monkeypatch.setattr(overlay, "SCRIPT", script)
    assert device.ok("status")["transaction"] == "pending"
    status = device.ok("recover")
    assert status["transaction"] == "recovered"
    assert status["qt5_overlay"] == "active"
    assert snapshot(device) == before
    assert _transactions(device) == []


def _legacy_leftover(device, *, rcc: bytes | None = None):
    leftover = device.gui / ".c300x-qml-transaction.999999"
    (leftover / ".qt5").mkdir(parents=True)
    shutil.copy2(device.gui / "HomePage.qml", leftover / "HomePage.qml")
    (leftover / ".qt5/rcc").write_bytes(device.rcc.read_bytes() if rcc is None else rcc)
    for name, path in (("library", device.lib), ("wrapper", device.wrapper), ("original", device.wrapper_backup)):
        shutil.copy2(path, leftover / ".qt5" / name)
    return leftover


def test_a_legacy_leftover_whose_activation_is_unchanged_is_finished(tmp_path, programs):
    device = overlay.Device(tmp_path, programs)
    device.ok("apply")
    before = snapshot(device)
    _legacy_leftover(device)
    assert device.ok("recover")["transaction"] == "recovered"
    assert snapshot(device) == before
    assert _transactions(device) == []


def test_a_legacy_leftover_with_changed_activation_stays_and_does_not_block(tmp_path, programs):
    device = overlay.Device(tmp_path, programs)
    device.ok("apply")
    before = snapshot(device)
    leftover = _legacy_leftover(device, rcc=b"an older resource file")
    assert device.ok("recover")["transaction"] == "stuck"
    assert snapshot(device) == before
    assert _transactions(device) == [leftover]
    assert device.ok("media-user-label-apply")["media_user_label_patched"] is True
