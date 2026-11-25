"""Qt 5 activation fault injection; no real GUI, mount, or device operations."""

import os
import shutil
import signal
import stat
import subprocess
import time
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


def test_a_sigterm_during_the_activation_rollback_repeats_it_and_exits_130(device):
    """The write's GUI restart fails and the agent's deadline SIGTERM hits the
    process group while the start script is put back: the cut step runs once
    more in the same process and the activation is the previous one again."""

    device.ok("apply")
    before = snapshot(device)
    source = overlay.SCRIPT.read_text()
    start, end = source.index("reload_gui() {"), source.index("\nremount_rw() {")
    script = device.root / "reload-failure.sh"
    script.write_text(source[:start] + "reload_gui() { return 1; }\n" + source[end:])
    script.chmod(0o700)
    held = device.root / "held"
    env = command_failure(
        device, "cp",
        f'case "$*" in *"/.qt5/wrapper {device.wrapper}.c300x-recovery."*) [ ! -e "{held}" ];; *) false;; esac',
        effect=f': > "{held}"; while :; do sleep 0.02; done',
    )
    process = subprocess.Popen([str(script), "media-user-label-apply"], env=device.environment(**env),
                               text=True, start_new_session=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.monotonic() + 20
    while not held.exists():
        assert process.poll() is None and time.monotonic() < deadline, process.communicate()
        time.sleep(0.01)
    os.killpg(process.pid, signal.SIGTERM)
    _, stderr = process.communicate(timeout=20)
    assert process.returncode == 130, stderr
    assert snapshot(device) == before
    assert not list(device.gui.glob(".c300x-qml-transaction.*"))
    assert not list(device.root.rglob("*.c300x-recovery.*"))


def test_a_sigkill_during_the_activation_rollback_leaves_no_recovery_copy_after_recover(device):
    """The agent's SIGKILL after the grace period cuts the copy of the start
    script; the next run rolls back again and drops the orphaned copy."""

    device.ok("apply")
    before = snapshot(device)
    source = overlay.SCRIPT.read_text()
    start, end = source.index("reload_gui() {"), source.index("\nremount_rw() {")
    script = device.root / "reload-failure.sh"
    script.write_text(source[:start] + "reload_gui() { return 1; }\n" + source[end:])
    script.chmod(0o700)
    held = device.root / "held"
    env = command_failure(
        device, "cp",
        f'case "$*" in *"/.qt5/wrapper {device.wrapper}.c300x-recovery."*) [ ! -e "{held}" ];; *) false;; esac',
        effect=f': > "{held}"; while :; do sleep 0.02; done',
    )
    process = subprocess.Popen([str(script), "media-user-label-apply"], env=device.environment(**env),
                               text=True, start_new_session=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.monotonic() + 20
    while not held.exists():
        assert process.poll() is None and time.monotonic() < deadline, process.communicate()
        time.sleep(0.01)
    os.killpg(process.pid, signal.SIGKILL)
    process.communicate(timeout=20)
    assert list(device.root.rglob("*.c300x-recovery.*"))
    status = device.ok("recover")
    assert status.get("transaction") == "recovered"
    assert snapshot(device) == before
    assert not list(device.gui.glob(".c300x-qml-transaction.*"))
    assert not list(device.root.rglob("*.c300x-recovery.*"))


def held_agent(device, command):
    """The agent binary, held in its `--display-qt5 <command>` until signalled."""
    held = device.root / "held"
    agent = device.root / "held-agent"
    agent.write_text(
        f'#!/bin/sh\nif [ "$2" = "{command}" ] && [ ! -e "{held}" ]; then\n'
        f'    : > "{held}"; while :; do sleep 0.02; done\nfi\n'
        f'exec "{device.programs["agent"]}" "$@"\n'
    )
    agent.chmod(0o700)
    return held, {"C300X_QML_AGENT_BIN": str(agent)}


def signal_when(process, mark, signo):
    deadline = time.monotonic() + 20
    while not mark():
        assert process.poll() is None and time.monotonic() < deadline, process.communicate()
        time.sleep(0.01)
    os.killpg(process.pid, signo)
    return process.communicate(timeout=20)


@pytest.mark.parametrize("signo", [signal.SIGTERM, signal.SIGKILL])
def test_a_write_ended_during_the_resource_pack_leaves_no_stage_on_storage(device, signo):
    """The resource stage lies on the station's storage, not in RAM like the
    base's staging directory: the signal clean-up removes it with that, and a
    stage of a script killed past its grace goes with the next pack."""

    device.ok("core-apply")
    before = snapshot(device)
    held, env = held_agent(device, "pack")
    process = subprocess.Popen([str(overlay.SCRIPT), "apply"], env=device.environment(**env),
                               text=True, start_new_session=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _, stderr = signal_when(process, held.exists, signo)
    stages = list(device.qt5_root.glob("rcc-stage.*"))
    if signo == signal.SIGTERM:
        assert process.returncode == 130, stderr
        assert stages == []
        assert snapshot(device) == before
    else:
        assert stages == [device.qt5_root / f"rcc-stage.{process.pid}"]
    device.ok("apply")
    assert list(device.qt5_root.glob("rcc-stage.*")) == []


def test_a_sigterm_during_the_recovery_restart_waits_for_its_request_on_qt5(device):
    """The base repeats a recovery pass cut by the deadline signal. On the Qt 5
    display its display restart is a request to the restart worker: the repeat
    waits for the request the first pass filed and files no second restart."""

    device.ok("apply")
    source = overlay.SCRIPT.read_text()
    start, end = source.index("reload_gui() {"), source.index("\nremount_rw() {")
    failing = device.root / "reload-failure.sh"
    failing.write_text(source[:start] + "reload_gui() { return 1; }\n" + source[end:])
    failing.chmod(0o700)
    # A write killed after its files changed leaves a transaction that needs a restart.
    held = device.root / "held"
    env = command_failure(
        device, "cp",
        f'case "$*" in *"/.qt5/wrapper {device.wrapper}.c300x-recovery."*) [ ! -e "{held}" ];; *) false;; esac',
        effect=f': > "{held}"; while :; do sleep 0.02; done',
    )
    process = subprocess.Popen([str(failing), "media-user-label-apply"], env=device.environment(**env),
                               text=True, start_new_session=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    signal_when(process, held.exists, signal.SIGKILL)
    assert list(device.gui.glob(".c300x-qml-transaction.*/.c300x-reload"))
    # No worker may take the request (flock refuses), so the filed requests stay countable.
    noflock = device.root / "noflock"
    noflock.write_text("#!/bin/sh\nexit 1\n")
    noflock.chmod(0o700)
    requests = device.root / "gui-restart/requests"
    process = subprocess.Popen([str(overlay.SCRIPT), "recover"], env=device.environment(
        C300X_QML_RELOAD_GUI="1", C300X_QML_GUI_FLOCK=str(noflock), C300X_QML_GUI_BUDGET_SECONDS="60"),
        text=True, start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    started = time.monotonic()

    def filed():
        # A request is filed once renamed from its .tmp; the worker skips a .tmp.
        return [p for p in requests.iterdir() if not p.name.endswith(".tmp")] if requests.is_dir() else []

    _, stderr = signal_when(process, lambda: bool(filed()), signal.SIGTERM)
    assert process.returncode == 131, stderr
    assert time.monotonic() - started < 15
    assert len(filed()) == 1
    assert not list(device.gui.glob(".c300x-qml-transaction.*"))
