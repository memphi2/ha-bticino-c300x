"""Reconcile Qt 5 activation independently of changed QML, without device access."""

import pytest

from tests import test_qml_patch_qt5_overlay as overlay
from tests.test_qml_patch_qt5_overlay import Device
from tests.test_qml_patch_qt5_overlay import programs as programs
from tests.test_qml_patch_qt5_transactions import artifacts, snapshot


@pytest.fixture
def device(tmp_path, programs):
    return Device(tmp_path, programs)


@pytest.mark.parametrize("action", ["apply", "core-apply"])
@pytest.mark.parametrize("drift", ["rcc-missing", "rcc-stale", "library-missing", "library-stale",
                                  "wrapper-missing", "wrapper-stock", "wrapper-stale", "wrapper-mode"])
def test_unchanged_qml_repairs_missing_or_stale_activation(device, action, drift):
    device.ok("apply")
    expected = snapshot(device)
    name, change = drift.split("-")
    path = artifacts(device)[name]
    if change == "missing":
        path.unlink()
    elif change == "stock":
        path.write_bytes(device.wrapper_backup.read_bytes())
        path.chmod(device.wrapper_backup.stat().st_mode & 0o777)
    elif change == "mode":
        path.chmod(0o600)
    else:
        path.write_bytes(path.read_bytes() + b"\n# stale\n")
    result = device.ok(action)
    assert result["changed_files"] == 0
    assert result["qt5_overlay"] == "active"
    assert snapshot(device) == expected


@pytest.mark.parametrize("quarantined", [False, True])
def test_noop_keeps_artifact_identity_and_does_not_reload(device, quarantined, monkeypatch):
    device.ok("apply")
    if quarantined:
        artifacts(device)["failed"].write_bytes(b"original quarantine")
    before = snapshot(device)
    identity = {name: (p.stat().st_ino, p.stat().st_mtime_ns)
                for name, p in artifacts(device).items() if p.exists()}
    source = overlay.SCRIPT.read_text()
    start, end = source.index("reload_gui() {"), source.index("\nremount_rw() {")
    script = device.root / "reload-forbidden.sh"
    script.write_text(source[:start] + "reload_gui() { return 1; }\n" + source[end:])
    script.chmod(0o700)
    monkeypatch.setattr(overlay, "SCRIPT", script)
    result = device.ok("apply")
    assert result["changed_files"] == 0
    assert result["qt5_overlay"] == ("failed" if quarantined else "active")
    assert snapshot(device) == before
    assert {name: (p.stat().st_ino, p.stat().st_mtime_ns)
            for name, p in artifacts(device).items() if p.exists()} == identity


def test_artifact_repair_never_releases_quarantine(device):
    device.ok("apply")
    artifacts(device)["failed"].write_bytes(b"failed activation\n")
    device.lib.write_bytes(b"old embedded library")
    assert device.ok("core-apply")["qt5_overlay"] == "failed"
    assert device.lib.read_bytes() == (device.programs["agent"].parent / "c300x-qrc-overlay.so").read_bytes()
    assert artifacts(device)["failed"].read_bytes() == b"failed activation\n"


def test_candidate_failure_keeps_active_artifacts(device):
    device.ok("apply")
    before = snapshot(device)
    result = device.run("apply", QT5_TEST_PACK_FAILS="1")
    assert result.returncode != 0
    assert snapshot(device) == before


def test_missing_original_is_not_replaced_with_a_patched_wrapper(device):
    device.ok("apply")
    device.wrapper_backup.unlink()
    before = snapshot(device)
    assert device.ok("status")["qt5_overlay"] == "incomplete"
    assert device.run("apply").returncode != 0
    assert snapshot(device) == before


@pytest.mark.parametrize("name", ["rcc", "library", "wrapper"])
def test_status_does_not_advertise_incomplete_activation_as_active(device, name):
    device.ok("apply")
    artifacts(device)[name].unlink()
    assert device.ok("status")["qt5_overlay"] == "incomplete"


def test_noop_rejects_symlink_activation_artifacts(device):
    device.ok("apply")
    original = device.rcc.read_bytes()
    target = device.root / "other.rcc"
    target.write_bytes(original)
    device.rcc.unlink()
    device.rcc.symlink_to(target)
    result = device.run("apply")
    assert result.returncode != 0
    assert "Unsupported display activation file" in result.stderr
    assert target.read_bytes() == original


@pytest.mark.parametrize("action", ["restore", "core-restore", "media-user-label-restore"])
def test_unchanged_partial_restore_repairs_the_remaining_overlay(device, action):
    device.ok("apply")
    device.ok(action)
    expected = snapshot(device)
    device.rcc.unlink()
    status = device.ok(action)
    assert status["changed_files"] == 0
    assert status["qt5_overlay"] == "active"
    assert snapshot(device) == expected


def test_restore_all_can_recover_a_missing_stock_wrapper(device):
    device.ok("apply")
    device.ok("restore-all")
    expected = snapshot(device)
    device.wrapper.unlink()
    assert device.ok("status")["qt5_overlay"] == "incomplete"
    assert device.ok("restore-all")["qt5_overlay"] == "off"
    assert snapshot(device) == expected
