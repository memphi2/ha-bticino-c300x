"""Qt 5 activation fault injection; no real GUI, mount, or device operations."""

import os
import shutil
import stat
from pathlib import Path

import pytest

from tests import test_qml_patch_qt5_overlay as overlay
from tests.test_qml_patch_qt5_overlay import programs as programs


@pytest.fixture
def device(tmp_path, programs):
    return overlay.Device(tmp_path, programs)


def artifacts(device):
    return {
        "rcc": device.rcc, "library": device.lib, "wrapper": device.wrapper,
        "original": device.wrapper_backup, "failed": Path(f"{device.rcc}.failed"),
    }


def snapshot(device):
    paths = artifacts(device) | {
        f"gui/{p.relative_to(device.gui)}": p for p in device.gui.rglob("*")
        if p.is_file() and ".c300x-qml-transaction." not in str(p)
    }
    return {name: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
            for name, path in paths.items() if path.is_file()}


def command_failure(device, command, condition, *, effect="exit 1"):
    directory = device.root / "commands"
    directory.mkdir(exist_ok=True)
    script = directory / command
    script.write_text(
        f"#!/bin/sh\nif {condition}; then {effect}; fi\n"
        f'exec "{shutil.which(command)}" "$@"\n'
    )
    script.chmod(0o700)
    return {"PATH": str(directory) + os.pathsep + os.environ["PATH"]}


@pytest.mark.parametrize("quarantined", [False, True])
@pytest.mark.parametrize("action", ["core-restore", "restore-all", "media-user-label-apply"])
def test_reload_failure_restores_every_activation_artifact(device, monkeypatch, action, quarantined):
    device.ok("apply")
    if quarantined:
        artifacts(device)["failed"].write_bytes(b"quarantined\n")
    for path in artifacts(device).values():
        if path.exists():
            path.chmod(0o751 if path == device.wrapper_backup else 0o640)
    before = snapshot(device)
    # Only the readiness boundary is injected. Transaction/publication run unchanged.
    source = overlay.SCRIPT.read_text()
    start, end = source.index("reload_gui() {"), source.index("\nremount_rw() {")
    script = device.root / "reload-failure.sh"
    script.write_text(source[:start] + "reload_gui() { return 1; }\n" + source[end:])
    script.chmod(0o700)
    monkeypatch.setattr(overlay, "SCRIPT", script)
    status = device.ok(action)
    assert status["state"] == "reload_failed"
    assert snapshot(device) == before
    assert not list(device.gui.glob(".c300x-qml-transaction.*"))


@pytest.mark.parametrize("artifact", ["rcc", "wrapper", "library", "original", "failed"])
def test_snapshot_failure_never_changes_active_files(device, artifact):
    device.ok("apply")
    artifacts(device)["failed"].touch()
    before = snapshot(device)
    env = command_failure(device, "cp", f'case "$3" in */.qt5/{artifact}) true;; *) false;; esac')
    assert device.run("restore-all", **env).returncode != 0
    assert snapshot(device) == before


@pytest.mark.parametrize("failure", ["pack", "overlay", "original", "wrapper"])
def test_first_activation_failure_restores_absent_artifacts(device, failure):
    device.ok("apply")
    device.ok("restore-all")
    device.wrapper_backup.unlink()
    before = snapshot(device)
    env = {}
    if failure == "pack":
        env["QT5_TEST_PACK_FAILS"] = "1"
    elif failure == "overlay":
        Path(f"{device.lib}.tmp").mkdir()
    elif failure == "original":
        env = command_failure(device, "cp", f'[ "$3" = "{device.wrapper_backup}.tmp" ]')
    else:
        env = command_failure(device, "mv", f'[ "$2" = "{device.wrapper}.c300x.tmp" ]')
    assert device.run("apply", **env).returncode != 0
    assert snapshot(device) == before


@pytest.mark.parametrize("failure", ["pack", "overlay", "wrapper", "restore-wrapper", "restore-library", "signal"])
@pytest.mark.parametrize("quarantined", [False, True])
def test_publication_failures_restore_activation_and_quarantine(device, failure, quarantined):
    device.ok("apply")
    if quarantined:
        artifacts(device)["failed"].write_bytes(b"quarantined\n")
    # A different valid ELF forces the overlay replacement rather than its no-op.
    device.lib.write_bytes(device.lib.read_bytes() + b"\0")
    before = snapshot(device)
    action = "core-restore"
    env = {}
    if failure == "pack":
        env["QT5_TEST_PACK_FAILS"] = "1"
    elif failure == "overlay":
        Path(f"{device.lib}.tmp").mkdir()
    elif failure in ("wrapper", "restore-wrapper", "signal"):
        env = command_failure(
            device, "mv", f'[ "$2" = "{device.wrapper}.c300x.tmp" ]',
            effect='kill -TERM "$PPID"; exit 1' if failure == "signal" else "exit 1",
        )
        if failure == "wrapper":
            # Force regeneration of the wrapper without altering its vendor backup.
            device.wrapper.write_text(device.wrapper.read_text() + "# previous version\n")
            before = snapshot(device)
        else:
            action = "restore-all"
    else:
        action = "restore-all"
        env = command_failure(device, "rm", f'[ "$2" = "{device.lib}" ]')
    result = device.run(action, **env)
    assert result.returncode != 0, result.stdout
    assert snapshot(device) == before
    assert not list(device.gui.glob(".c300x-qml-transaction.*"))


@pytest.mark.parametrize("artifact", ["rcc", "library", "original", "wrapper", "failed"])
def test_failed_rollback_keeps_recovery_and_blocks_overlay(device, artifact):
    device.ok("apply")
    artifacts(device)["failed"].write_bytes(b"quarantined\n")
    before = snapshot(device)
    env = command_failure(
        device, "mv", f'case "$2" in "{artifacts(device)[artifact]}.c300x-recovery."*) true;; *) false;; esac',
    )
    env["QT5_TEST_PACK_FAILS"] = "1"
    result = device.run("core-restore", **env)
    assert result.returncode != 0
    assert "recovery files retained" in result.stderr
    assert artifacts(device)["failed"].is_file()
    recovery = list(device.gui.glob(".c300x-qml-transaction.*/.qt5"))
    assert len(recovery) == 1
    for name in artifacts(device):
        assert (recovery[0] / name).read_bytes() == before[name][0]


@pytest.mark.parametrize("artifact", ["rcc", "library", "original", "wrapper", "failed"])
@pytest.mark.parametrize("kind", ["symlink", "directory"])
def test_activation_rejects_nonregular_files_without_following_them(device, artifact, kind):
    device.ok("apply")
    target = artifacts(device)[artifact]
    target.unlink(missing_ok=True)
    sentinel = device.root / "sentinel"
    sentinel.write_bytes(b"untouched")
    if kind == "symlink":
        target.symlink_to(sentinel)
    else:
        target.mkdir()
    result = device.run("core-restore")
    assert result.returncode != 0
    assert "Unsupported display activation file" in result.stderr
    assert sentinel.read_bytes() == b"untouched"
    assert target.is_symlink() if kind == "symlink" else target.is_dir()
