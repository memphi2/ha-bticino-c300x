"""Beta update must retain Qt5 recovery until full, verified overlay removal.

All changes are in temporary copies. Staged agent payloads are never executed.
Original firmware wrappers are optional private read-only inputs.
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
from test_native_agent_update_legacy_bootstrap import _compile_updater

from tests.test_qml_patch_qt5_overlay import Device
from tests.test_qml_patch_qt5_overlay import programs as programs

ROOT = Path(__file__).resolve().parents[1]
STABLE_COMMIT = "40cb1aa4"


@pytest.fixture(scope="module", params=[False, True], ids=["host", "asan-ubsan"])
def updater(request, tmp_path_factory):
    return _compile_updater(tmp_path_factory.mktemp("downgrade-updater"), False, request.param)


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    with pytest.MonkeyPatch.context() as context:
        context.syspath_prepend(str(ROOT / "scripts"))
        import stage_device_agent_bundle as stager

    directory = tmp_path_factory.mktemp("downgrade-bundle")
    binary = directory / "never-executed"
    binary.write_bytes(b"synthetic beta payload, never execute")
    stager.stage_bundle(directory / "bundle", version="test", skip_build=True, agent_binary=binary)
    return directory / "bundle"


@pytest.fixture(scope="module")
def stable_bundle(tmp_path_factory):
    directory = tmp_path_factory.mktemp("stable-282-source")
    archived = subprocess.run(["git", "archive", STABLE_COMMIT], cwd=ROOT, capture_output=True, check=True)
    with tarfile.open(fileobj=io.BytesIO(archived.stdout)) as archive:
        archive.extractall(directory, filter="data")
    assert b"QT5_DISPLAY" not in (directory / "native_agent/scripts/qml_patch.sh").read_bytes()
    binary = directory / "never-executed"
    binary.write_bytes(b"synthetic stable payload, never execute")
    # Import the historical stager in isolation, not the current module cache.
    subprocess.run([sys.executable, "-c", "import stage_device_agent_bundle as s; "
                    "assert s.agent_version() == '2.8.2'; "
                    "s.stage_bundle(s.ROOT / 'bundle', version='2.8.2', skip_build=True, "
                    "agent_binary=s.ROOT / 'never-executed')"],
                   cwd=directory / "scripts", check=True, capture_output=True, text=True)
    return directory / "bundle"


@pytest.fixture
def device(tmp_path, bundle):
    agent = tmp_path / "agent"
    shutil.copytree(bundle, agent / ".update")
    for name, content in {
        "c300x-agent-native": b"previous beta runtime",
        "qml_patch.sh": b"previous beta recovery script",
        "config.json": b'{"retained":true}',
        "bundle.json": b'{"bundle_hash":"previous"}',
        "init-script": b"previous init",
    }.items():
        (agent / name).write_bytes(content)
    (agent / "init-link").symlink_to(agent / "init-script")
    return agent


def original_wrapper(agent, firmware="3.0.6"):
    work = Path(os.environ.get("C300X_FIRMWARE_WORK", ROOT.parent / "c300x-fwpatch/work"))
    source = work / f"rootfs-{firmware}/home/bticino/bin/BtClass_qws"
    if not source.is_file():
        pytest.skip("Private original firmware wrapper unavailable")
    target = agent / "BtClass_qws"
    shutil.copy2(source, target)
    assert target.stat().st_mode & 0o111
    return target


def manifest(agent, capability=None):
    path = agent / ".update/device_agent/bundle.json"
    body = json.loads(path.read_text())
    body.pop("qt5_recovery_version", None)
    if capability is not None:
        body["qt5_recovery_version"] = capability
    path.write_text(json.dumps(body))
    return path


def snapshot(agent):
    result = {}
    for path in agent.rglob("*"):
        relative = path.relative_to(agent)
        if relative.parts[0] == ".update":
            continue
        info = path.lstat()
        body = os.readlink(path) if path.is_symlink() else path.read_bytes() if path.is_file() else None
        result[str(relative)] = (body, info.st_mode, info.st_ino, info.st_mtime_ns)
    return result


def apply(updater, agent, expected, *, qt5=True):
    result = subprocess.run([str(updater), str(agent), str(agent / ".update/device_agent/bundle.json"),
                             str(int(expected))], capture_output=True, text=True, timeout=15,
                            env={**os.environ, "C300X_TEST_QT5": "1" if qt5 else "0"})
    assert result.returncode == 0, result.stdout + result.stderr
    body = json.loads(result.stdout)
    if not expected:
        assert body["remount_calls"] == body["activation_calls"] == 0
    return body, result.stderr


@pytest.mark.parametrize("artifact", ["display-qt5.rcc", "c300x-qrc-overlay.so", "display-qt5.rcc.failed"])
@pytest.mark.parametrize("kind", ["regular", "empty", "symlink", "directory"])
def test_unsupported_target_cannot_replace_any_overlay_recovery(updater, device, artifact, kind):
    original_wrapper(device)
    manifest(device)
    target = device / artifact
    if kind == "directory":
        target.mkdir()
    elif kind == "symlink":
        target.symlink_to(device / "missing-link-target")
    else:
        target.write_bytes(b"retained overlay" if kind == "regular" else b"")
    before = snapshot(device)
    body, error = apply(updater, device, False)
    assert body["changed_files"] == 0
    assert "qt5_recovery_required" in error
    assert snapshot(device) == before
    assert not list(device.rglob("*.update-backup"))


@pytest.mark.parametrize("artifact", ["display-qt5.rcc", "c300x-qrc-overlay.so", "display-qt5.rcc.failed", None])
def test_a_qt4_station_updates_as_in_292(updater, device, artifact):
    """Firmware 1.7.x/2.0.2 hold no Qt 5 overlay: no recovery guard, as in 2.9.2.

    Neither a stray overlay file nor a start script of unknown content stops
    an update to a bundle without the Qt 5 recovery capability there.
    """
    wrapper = device / "BtClass_qws"
    wrapper.write_bytes(b"#!/bin/sh\n# a Qt 4 start script\nexit 0\n")
    wrapper.chmod(0o755)
    manifest(device)
    if artifact is not None:
        (device / artifact).write_bytes(b"left over")
    body, error = apply(updater, device, True, qt5=False)
    assert body["changed_files"] > 0 and body["activation_calls"] == 1
    assert "qt5_recovery_required" not in error
    # The same station with the Qt 5 display refuses it.
    if artifact is not None:
        (device / artifact).write_bytes(b"left over")
        manifest(device)
        assert "qt5_recovery_required" in apply(updater, device, False)[1]


@pytest.mark.parametrize("state", ["missing", "unknown", "same-size", "no-execute", "symlink", "fifo"])
def test_unknown_or_orphan_wrapper_blocks_unsupported_target(updater, device, state):
    wrapper = original_wrapper(device)
    manifest(device)
    if state == "missing":
        wrapper.unlink()
    elif state == "unknown":
        wrapper.write_bytes(b"#!/bin/sh\n# c300x-qrc-overlay\nexit 0\n")
    elif state == "same-size":
        wrapper.write_bytes(wrapper.read_bytes().replace(b"eglfs", b"other", 1))
    elif state == "no-execute":
        wrapper.chmod(0o600)
    else:
        wrapper.unlink()
        if state == "symlink":
            wrapper.symlink_to(device / "missing")
        else:
            os.mkfifo(wrapper)
    before = snapshot(device)
    apply(updater, device, False)
    assert snapshot(device) == before


@pytest.mark.parametrize("capability", [0, 2, True, "1", 1.0, {}, []])
def test_unknown_capability_does_not_authorize_recovery_loss(updater, device, capability):
    (device / "display-qt5.rcc").write_bytes(b"active")
    manifest(device, capability)
    before = snapshot(device)
    apply(updater, device, False)
    assert snapshot(device) == before


@pytest.mark.parametrize("declaration", [
    '"qt5_recovery_version": 1, "qt5_recovery_version": 0',
    '"qt5_recovery_version": 1, "qt5_recovery_versi\\u006fn": 0',
    '"nested": {"qt5_recovery_version": 1}',
])
def test_ambiguous_or_nested_capability_is_not_trusted(updater, device, declaration):
    path = manifest(device, 1)
    path.write_text(path.read_text().replace('"qt5_recovery_version": 1', declaration))
    (device / "display-qt5.rcc.failed").write_bytes(b"quarantine")
    before = snapshot(device)
    apply(updater, device, False)
    assert snapshot(device) == before


def test_verified_stock_allows_target_without_qt5_capability(updater, device):
    original_wrapper(device, "3.0.6")
    manifest(device)
    # Disposable extraction cache and original backup remain after restore-all.
    (device / "display-qt5/vendor").mkdir(parents=True)
    (device / "display-qt5/vendor/MainApp.qml").write_bytes(b"retained extraction cache")
    body, _ = apply(updater, device, True)
    assert body["changed_files"] > 0
    assert apply(updater, device, True)[0]["changed_files"] == 0


@pytest.mark.parametrize("firmware", ["1.7.19", "2.0.2"])
def test_a_qt4_start_script_on_the_qt5_display_is_no_proof_of_removal(updater, device, firmware):
    """Only 3.0.x has a Qt 5 display; a 1.7.x/2.0.x start script there is foreign."""

    original_wrapper(device, firmware)
    manifest(device)
    before = snapshot(device)
    assert "qt5_recovery_required" in apply(updater, device, False)[1]
    assert snapshot(device) == before


def test_declared_beta_recovery_allows_update_and_retry_with_quarantine(updater, device):
    manifest(device, 1)
    (device / "display-qt5.rcc").write_bytes(b"retained resource")
    (device / "display-qt5.rcc.failed").write_bytes(b"retained quarantine")
    before = {name: (device / name).read_bytes() for name in ("display-qt5.rcc", "display-qt5.rcc.failed")}
    assert apply(updater, device, True)[0]["changed_files"] > 0
    assert apply(updater, device, True)[0]["changed_files"] == 0
    assert all((device / name).read_bytes() == value for name, value in before.items())


def test_stager_declares_recovery_contract(bundle):
    body = json.loads((bundle / "device_agent/bundle.json").read_text())
    assert type(body.get("qt5_recovery_version")) is int
    assert body["qt5_recovery_version"] == 1
    assert body["update_file_set_version"] == 7


def test_capability_is_part_of_bundle_identity(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import stage_device_agent_bundle as stager

    arguments = {"agent_version": "test", "api_version": "1", "files": [], "group_hashes": {}}
    capable = stager._bundle_hash(**arguments)
    monkeypatch.setattr(stager, "QT5_RECOVERY_VERSION", 0)
    assert stager._bundle_hash(**arguments) != capable


def test_capability_does_not_bypass_payload_validation(updater, device):
    manifest(device, 1)
    (device / "display-qt5.rcc.failed").write_text("quarantine")
    (device / ".update/device_agent/scripts/qml_patch.sh").write_text("corrupt recovery")
    before = snapshot(device)
    apply(updater, device, False)
    assert snapshot(device) == before


@pytest.mark.parametrize("name", ["C300X_AGENT_DIR", "C300X_QML_GUI_WRAPPER",
                                 "C300X_QML_QT5_RCC", "C300X_QML_QT5_OVERLAY_LIB"])
def test_unverified_activation_paths_fail_closed(updater, device, monkeypatch, name):
    original_wrapper(device)
    manifest(device)
    monkeypatch.setenv(name, str(device / "other-path"))
    before = snapshot(device)
    apply(updater, device, False)
    assert snapshot(device) == before
    manifest(device, 1)
    assert apply(updater, device, True)[0]["changed_files"] > 0


def test_stat_error_is_not_absent_wrapper(updater, device, monkeypatch):
    original_wrapper(device)
    manifest(device)
    loop = device / "loop"
    loop.symlink_to(loop)
    monkeypatch.setenv("C300X_TEST_GUI_WRAPPER", str(loop / "BtClass_qws"))
    before = snapshot(device)
    apply(updater, device, False)
    assert snapshot(device) == before


def test_actual_stable_requires_real_firmware_full_restore(
    updater, device, stable_bundle, programs, tmp_path,
):
    work = Path(os.environ.get("C300X_FIRMWARE_WORK", ROOT.parent / "c300x-fwpatch/work"))
    original = work / "rootfs-3.0.6/home/bticino/bin/gui/BtClass"
    if not original.is_file():
        pytest.skip("Private original firmware executable unavailable")
    root = tmp_path / "display"
    root.mkdir()
    display = Device(root, programs)
    display.program = original
    display.wrapper = original_wrapper(device)
    display.rcc = device / "display-qt5.rcc"
    display.lib = device / "c300x-qrc-overlay.so"
    display.qt5_root = device / "display-qt5"
    display.gui = display.qt5_root / "skins/default"
    original_bytes = display.wrapper.read_bytes()
    assert display.ok("apply")["qt5_overlay"] == "active"
    quarantine = display.rcc.with_suffix(".rcc.failed")
    quarantine.write_text("retained quarantine")
    shutil.rmtree(device / ".update")
    shutil.copytree(stable_bundle, device / ".update")
    before = snapshot(device)
    body, error = apply(updater, device, False)
    assert body["changed_files"] == 0 and "qt5_recovery_required" in error
    assert snapshot(device) == before
    display.wrapper_backup.chmod(0o600)
    assert display.run("restore-all").returncode != 0
    assert snapshot(device) == before
    apply(updater, device, False)
    display.wrapper_backup.chmod(0o755)
    assert display.ok("restore-all")["qt5_overlay"] == "off"
    assert display.wrapper.read_bytes() == original_bytes
    assert display.wrapper.stat().st_mode & 0o111
    assert not any(path.exists() for path in (display.rcc, display.lib, quarantine))
    assert apply(updater, device, True)[0]["changed_files"] > 0
    assert b"QT5_DISPLAY" not in (device / "qml_patch.sh").read_bytes()
    assert apply(updater, device, True)[0]["changed_files"] == 0
