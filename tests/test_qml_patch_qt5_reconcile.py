"""Reconcile Qt 5 activation independently of changed QML, without device access."""

import json

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


@pytest.mark.parametrize("earlier_boot", [False, True])
def test_noop_keeps_artifact_identity_and_does_not_reload(device, earlier_boot, monkeypatch):
    device.ok("apply")
    if earlier_boot:
        artifacts(device)["failed"].write_bytes(b"boot-0\n")
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
    assert result["qt5_overlay"] == "active"
    assert snapshot(device) == before
    assert {name: (p.stat().st_ino, p.stat().st_mtime_ns)
            for name, p in artifacts(device).items() if p.exists()} == identity


def test_artifact_repair_also_retries_a_quarantined_overlay(device):
    device.ok("apply")
    artifacts(device)["failed"].write_bytes(b"boot-1\n")
    device.lib.write_bytes(b"old embedded library")
    assert device.ok("core-apply")["qt5_overlay"] == "active"
    assert device.lib.read_bytes() == (device.programs["agent"].parent / "c300x-qrc-overlay.so").read_bytes()
    assert not artifacts(device)["failed"].exists()


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
    # A damaged installation of a known display is not an unknown display.
    assert "qt5_unsupported" not in device.ok("status")


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


@pytest.mark.parametrize("case", ["vendor-update", "edited-vendor-lines"])
def test_restore_all_leaves_a_start_script_that_is_not_ours_alone(device, case):
    device.ok("apply")
    if case == "vendor-update":
        # A firmware update ships its own start script in place of ours.
        script = overlay.WRAPPER.replace("./bin/gui/BtClass &", "export QT_NEW=1\n./bin/gui/BtClass &")
    else:
        # Our block, but the vendor's lines around it are no longer the original.
        script = device.wrapper.read_text().replace("export QT_QPA_PLATFORM=eglfs", "export QT_QPA_PLATFORM=linuxfb")
    device.wrapper.write_text(script)
    device.wrapper.chmod(0o750)
    result = device.run("restore-all")
    assert result.returncode == 0, result.stderr
    assert device.wrapper.read_text() == script
    assert device.wrapper.stat().st_mode & 0o777 == 0o750
    assert "Display start script is not the one installed here" in result.stderr
    status = json.loads(result.stdout.strip().splitlines()[-1])
    assert status["qt5_unsupported"] == "display_wrapper_unknown"
    assert not device.rcc.exists() and not device.lib.exists()


# The blocks earlier betas inserted: 2.9.0b1/b2 (sticky mark) and 3876e2b4
# (boot id, retry after a 3 s pause; shortened to its shape), as their
# qt5_wrapper_text wrote them.
OLD_BLOCKS = {
    "2.9.0b2": (
        "# c300x-qrc-overlay: display pages of the Home Assistant integration\n"
        "if [ -f '{lib}' ] && [ -f '{rcc}' ] && [ ! -e '{rcc}.failed' ]; then\n"
        "    c300x_start=$(date +%s)\n"
        "    rm -f '{log}.rc'\n"
        "    {{ {{ LD_PRELOAD='{lib}' C300X_QRC_OVERLAY='{rcc}' QML_DISABLE_DISK_CACHE=1 ./bin/gui/BtClass 2>&1 1>&3 3>&-; "
        "echo $? > '{log}.rc'; }} | {{ head -c 65536 > '{log}'; cat > /dev/null; }}; }} 3>&1 &\n"
        "    wait $!\n"
        "    c300x_rc=$(cat '{log}.rc' 2>/dev/null || echo 0)\n"
        "    case $c300x_rc in 0|137|138|140|143) exit $c300x_rc ;; esac\n"
        "    [ $(($(date +%s) - c300x_start)) -lt 60 ] || exit $c300x_rc\n"
        "    : > '{rcc}.failed'\n"
        "fi\n"
    ),
    "3876e2b4": (
        "# c300x-qrc-overlay: display pages of the Home Assistant integration\n"
        "c300x_boot=$(cat '{boot}' 2>/dev/null)\n"
        "if [ -f '{lib}' ] && [ -f '{rcc}' ] && {{ [ ! -e '{rcc}.failed' ] || [ \"$(cat '{rcc}.failed' 2>/dev/null)\" != \"$c300x_boot\" ]; }}; then\n"
        "    for c300x_try in 1 ${{C300X_GUI_RELOAD:+2}}; do\n"
        "        [ $c300x_try = 1 ] || sleep 3\n"
        "        c300x_start=$(date +%s)\n"
        "        wait $!\n"
        "        case $c300x_rc in 0|137|138|140|143) exit $c300x_rc ;; esac\n"
        "    done\n"
        "    printf '%s\\n' \"$c300x_boot\" > '{rcc}.failed'\n"
        "fi\n"
    ),
}


@pytest.mark.parametrize("version", sorted(OLD_BLOCKS))
def test_restore_all_removes_the_start_script_of_an_earlier_beta(device, version):
    """An update that was not followed by an apply leaves the earlier block in place."""

    device.ok("apply")
    block = OLD_BLOCKS[version].format(lib=device.lib, rcc=device.rcc, log=device.root / "display-qt5.log",
                                       boot=device.boot_id)
    device.wrapper.write_text(overlay.WRAPPER.replace("./bin/gui/BtClass &", block + "./bin/gui/BtClass &"))
    status = device.ok("restore-all")
    assert device.wrapper.read_text() == overlay.WRAPPER
    assert "qt5_unsupported" not in status and status["qt5_overlay"] == "off"


def test_restore_all_can_recover_a_missing_stock_wrapper(device):
    device.ok("apply")
    device.ok("restore-all")
    expected = snapshot(device)
    device.wrapper.unlink()
    assert device.ok("status")["qt5_overlay"] == "incomplete"
    assert device.ok("restore-all")["qt5_overlay"] == "off"
    assert snapshot(device) == expected
