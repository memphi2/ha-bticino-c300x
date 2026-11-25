"""Exercise the real HTTP quality transaction against local, unshipped firmware."""

from __future__ import annotations

import fcntl
import hashlib
import json
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_native_camera_quality import (
    CONFIRM,
    SETTINGS,
    STACK,
    WHOLE_PICTURE,
    Lab,
    binary,
    lab,
    media_image,
    qt5,
    reboot,
)

__all__ = ["binary", "lab", "media_image", "qt5", "reboot"]

STOCK = "97b61ad80e67c1b3ea494956568645b93c7fe3ef359f77af9c7e2ad6dff1bf9e"
PATCHED = "baac8d478db5c4ae1baa46da963b379941d2952cfe047f3030b6a3182579821c"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_unknown_firmware_never_offers_or_applies_geometry(lab: Lab) -> None:
    assert "960x576" not in lab.call()["sizes"]
    assert lab.call({**CONFIRM, "size": "960x576"}, status=400)["error"] == "camera_quality_invalid_size"
    assert lab.stack.read_text() == STACK
    assert not lab.backup.parent.exists()


def test_parallel_maintenance_returns_conflict_without_mutation(lab: Lab) -> None:
    with Path(lab.env["C300X_CAMERA_UPDATE_LOCK"]).open("w") as lock:
        Path(lock.name).chmod(0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = lab.call({**CONFIRM, "fps": 24}, status=409)
        assert result["error"] == "camera_quality_update_busy"
    assert lab.settings.read_text() == SETTINGS
    assert not lab.backup.parent.exists()


@pytest.mark.parametrize("media_image", ["stock"], indirect=True)
def test_geometry_selection_is_coupled_and_survives_agent_restart(lab: Lab) -> None:
    target = Path(lab.env["C300X_MEDIA_GEOMETRY_TARGET"])
    running = Path(lab.env["C300X_MEDIA_GEOMETRY_RUNNING_TARGET"])
    backup = Path(lab.env["C300X_MEDIA_GEOMETRY_BACKUP"])
    assert "960x576" in lab.call()["sizes"]
    body = lab.call({**CONFIRM, "size": "960x576", "fps": 24, "bitrate_kbps": 3000})
    assert (body["size"], body["running_size"], body["restart_required"]) == ("960x576", "688x480", True)
    assert digest(target) == PATCHED and digest(backup) == STOCK and digest(running) == STOCK
    assert lab.stack.read_text() == WHOLE_PICTURE
    assert "Width=800\nHeight=480" in lab.settings.read_text()
    lab.restart_agent()
    assert lab.call()["running_size"] == "688x480"
    assert lab.call()["restart_required"] is True
    inode = target.stat().st_ino
    assert lab.call({**CONFIRM, "size": "960x576"})["changed"] is False
    assert target.stat().st_ino == inode
    # Simulate the device booting the replaced executable, not just restarting the agent.
    running.write_bytes(target.read_bytes())
    (target.parent / "boot_id").write_text("boot-2\n")
    lab.restart_agent()
    assert (lab.call()["running_size"], lab.call()["restart_required"]) == ("960x576", False)
    body = lab.call({**CONFIRM, "size": "704x576"})
    assert (body["size"], body["running_size"], body["restart_required"]) == ("704x576", "960x576", True)
    assert digest(target) == STOCK
    assert digest(backup) == STOCK


@pytest.mark.parametrize("media_image", ["stock"], indirect=True)
def test_uninstall_restores_geometry_and_original_camera_settings(lab: Lab) -> None:
    lab.call({**CONFIRM, "size": "960x576", "fps": 24})
    for _ in range(2):
        result = subprocess.run([str(lab.binary), "--restore-media-patches"], env=lab.env,
                                capture_output=True, text=True, timeout=10, check=False)
        assert result.returncode == 0, result.stderr
        assert digest(Path(lab.env["C300X_MEDIA_GEOMETRY_TARGET"])) == STOCK
        assert lab.stack.read_text() == STACK
        assert lab.settings.read_text() == SETTINGS


@pytest.mark.parametrize("media_image", ["stock"], indirect=True)
def test_invalid_geometry_backup_prevents_any_config_change(lab: Lab) -> None:
    backup = Path(lab.env["C300X_MEDIA_GEOMETRY_BACKUP"])
    backup.parent.mkdir(parents=True)
    backup.write_bytes(b"broken backup")
    body = lab.call({**CONFIRM, "size": "960x576", "fps": 24}, status=500)
    assert body["error"] == "camera_quality_geometry_backup_invalid"
    assert lab.stack.read_text() == STACK
    assert lab.settings.read_text() == SETTINGS
    assert digest(Path(lab.env["C300X_MEDIA_GEOMETRY_TARGET"])) == STOCK


@pytest.mark.parametrize("media_image", ["stock"], indirect=True)
@pytest.mark.parametrize("qt5", [True])
def test_low_stream_cannot_apply_high_geometry(lab: Lab) -> None:
    assert "960x576" not in lab.call()["sizes"]
    lab.call({**CONFIRM, "size": "960x576"}, status=400)
    assert digest(Path(lab.env["C300X_MEDIA_GEOMETRY_TARGET"])) == STOCK
    assert not lab.backup.parent.exists()


@pytest.mark.parametrize("media_image", ["stock"], indirect=True)
@pytest.mark.parametrize("broken", ["settings", "crop"])
def test_unreadable_managed_config_blocks_removal_and_keeps_all_backups(lab: Lab, broken: str) -> None:
    lab.call({**CONFIRM, "size": "960x576", "fps": 24})
    target = Path(lab.env["C300X_MEDIA_GEOMETRY_TARGET"])
    backup = Path(lab.env["C300X_MEDIA_GEOMETRY_BACKUP"])
    (lab.settings if broken == "settings" else lab.stack).write_text("damaged config")
    result = subprocess.run([str(lab.binary), "--restore-media-patches"], env=lab.env,
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 1
    assert "managed_camera_config_unreadable" in result.stderr
    assert digest(target) == PATCHED
    assert digest(backup) == STOCK
    assert lab.backup.read_text() == SETTINGS
    assert (lab.backup.parent / "stack_open.xml.camera").read_text() == STACK


@pytest.mark.parametrize("media_image", ["stock"], indirect=True)
@pytest.mark.parametrize("reboot", [True])
def test_running_review_unknown_image_does_not_reboot_an_unchanged_request(lab: Lab) -> None:
    Path(lab.env["C300X_MEDIA_GEOMETRY_RUNNING_TARGET"]).write_bytes(b"unknown running image")
    lab.restart_agent()
    body = lab.call({**CONFIRM, "fps": 15})
    assert (body["changed"], body["restart_required"], body["rebooting"]) == (False, False, False)
    assert (body["running_fps"], body["running_size"]) == (0, "")
    time.sleep(0.1)
    assert not (lab.settings.parent / "reboot-done").exists()
    body = lab.call({**CONFIRM, "fps": 20, "reboot": False})
    assert body["restart_required"] is True
    lab.restart_agent()
    body = lab.call()
    assert (body["running_fps"], body["running_size"], body["restart_required"]) == (0, "", True)
    assert lab.call({**CONFIRM, "fps": 15, "reboot": False})["restart_required"] is False


@pytest.mark.parametrize("media_image", ["stock"], indirect=True)
def test_running_review_unknown_image_keeps_geometry_only_change_pending(lab: Lab) -> None:
    lab.call({**CONFIRM, "size": "704x576"})
    (lab.settings.parent / "boot_id").write_text("boot-2\n")
    lab.restart_agent()
    Path(lab.env["C300X_MEDIA_GEOMETRY_RUNNING_TARGET"]).write_bytes(b"unknown running image")
    lab.restart_agent()
    before = lab.settings.read_bytes(), lab.stack.read_bytes()
    body = lab.call({**CONFIRM, "size": "960x576"})
    assert (lab.settings.read_bytes(), lab.stack.read_bytes()) == before
    assert body["restart_required"] is True
    lab.restart_agent()
    body = lab.call()
    assert (body["size"], body["running_size"], body["restart_required"]) == ("960x576", "", True)
    assert lab.call({**CONFIRM, "size": "704x576"})["restart_required"] is False


@pytest.mark.parametrize("media_image", ["stock"], indirect=True)
@pytest.mark.parametrize("observe_before_agent_restart", [False, True])
@pytest.mark.parametrize("replacement_mode", ["same_inode", "new_inode"])
def test_running_review_new_generation_never_mixes_old_config_with_new_geometry(
    lab: Lab, observe_before_agent_restart: bool, replacement_mode: str,
) -> None:
    lab.call({**CONFIRM, "size": "960x576", "fps": 24})
    running = Path(lab.env["C300X_MEDIA_GEOMETRY_RUNNING_TARGET"])
    replacement = running.with_suffix(".new") if replacement_mode == "new_inode" else running
    replacement.write_bytes(Path(lab.env["C300X_MEDIA_GEOMETRY_TARGET"]).read_bytes())
    if replacement_mode == "new_inode":
        replacement.replace(running)
    if observe_before_agent_restart:
        body = lab.call()
        assert (body["running_bitrate_kbps"], body["running_fps"], body["running_size"]) == (0, 0, "")
    lab.restart_agent()
    body = lab.call()
    assert (body["running_bitrate_kbps"], body["running_fps"], body["running_size"]) == (0, 0, "")
    assert body["restart_required"] is True
    (lab.settings.parent / "boot_id").write_text("boot-2\n")
    lab.restart_agent()
    body = lab.call()
    assert (body["running_fps"], body["running_size"], body["restart_required"]) == (24, "960x576", False)


@pytest.mark.parametrize("media_image", ["stock"], indirect=True)
def test_running_review_same_image_new_generation_is_not_a_new_baseline(lab: Lab) -> None:
    running = Path(lab.env["C300X_MEDIA_GEOMETRY_RUNNING_TARGET"])
    old = running.with_suffix(".old")
    running.rename(old)
    running.write_bytes(old.read_bytes())
    body = lab.call()
    assert (body["running_fps"], body["running_size"], body["restart_required"]) == (0, "", False)
    # Even restoring the fixture identity cannot clear an observed generation loss.
    old.replace(running)
    lab.restart_agent()
    body = lab.call()
    assert (body["running_fps"], body["running_size"], body["restart_required"]) == (0, "", False)


@pytest.mark.parametrize("media_image", ["stock"], indirect=True)
@pytest.mark.parametrize("pending", ["none", "config", "geometry", "reverted"])
def test_running_review_late_first_process_binds_only_an_unchanged_baseline(lab: Lab, pending: str) -> None:
    running = Path(lab.env["C300X_MEDIA_GEOMETRY_RUNNING_TARGET"])
    running.unlink()
    lab.stack.write_text(WHOLE_PICTURE)
    (lab.settings.parent / "boot_id").write_text("boot-2\n")
    lab.restart_agent()
    body = lab.call()
    assert (body["running_fps"], body["running_size"], body["restart_required"]) == (0, "", False)
    if pending in ("config", "reverted"):
        assert lab.call({**CONFIRM, "fps": 20})["restart_required"] is True
    elif pending == "geometry":
        assert lab.call({**CONFIRM, "size": "960x576"})["restart_required"] is True
    running.write_bytes(Path(lab.env["C300X_MEDIA_GEOMETRY_TARGET"]).read_bytes())
    if pending == "reverted":
        assert lab.call({**CONFIRM, "fps": 15})["restart_required"] is False
    expected = (15, "704x576", False) if pending == "none" else (0, "", pending != "reverted")
    body = lab.call()
    assert (body["running_fps"], body["running_size"], body["restart_required"]) == expected
    lab.restart_agent()
    body = lab.call()
    assert (body["running_fps"], body["running_size"], body["restart_required"]) == expected


def test_running_review_real_process_start_time_prevents_pid_only_binding(lab: Lab) -> None:
    # A local sleeping process exercises /proc identity; it never runs vendor code.
    child = subprocess.Popen([sys.executable, "-c",
        'import ctypes,sys; assert ctypes.CDLL(None).prctl(15,b"bt_"+b"av_media",0,0,0)==0; '
        'print("ready",flush=True); sys.stdin.read()'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert select.select([child.stdout], [], [], 5)[0]
        assert child.stdout.readline().strip() == "ready"
        lab.env.pop("C300X_MEDIA_GEOMETRY_RUNNING_TARGET")
        note = Path(lab.env["C300X_CAMERA_RUNNING_NOTE"])
        note.unlink()
        lab.restart_agent()
        assert lab.call()["running_fps"] == 15  # unknown firmware keeps legacy config reporting
        fields = note.read_text().split()
        ticks = Path(f"/proc/{child.pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
        assert fields[9:12] == ["g1", str(child.pid), ticks]
        fields[11] = str(int(ticks) + 1)  # stale generation for the same PID
        note.write_text(" ".join(fields) + "\n")
        lab.restart_agent()
        body = lab.call()
        assert (body["running_fps"], body["running_size"], body["restart_required"]) == (0, "", False)
    finally:
        child.terminate()
        child.communicate(timeout=5)


@pytest.mark.parametrize("media_image", ["stock"], indirect=True)
def test_running_review_current_geometry_observation_does_not_change_boot_note(lab: Lab) -> None:
    lab.call({**CONFIRM, "size": "960x576"})
    running = Path(lab.env["C300X_MEDIA_GEOMETRY_RUNNING_TARGET"])
    target = Path(lab.env["C300X_MEDIA_GEOMETRY_TARGET"])
    note = Path(lab.env["C300X_CAMERA_RUNNING_NOTE"])
    running.write_bytes(target.read_bytes())
    before = note.read_bytes()
    for current, expected in ((running.read_bytes(), True), (b"unknown executable", False)):
        running.write_bytes(current)
        result = subprocess.run([str(lab.binary), "--restore-media-patches"], env=lab.env,
                                capture_output=True, text=True, timeout=10, check=True)
        assert json.loads(result.stdout)["media_reboot_required"] is expected
        assert digest(target) == STOCK
        assert note.read_bytes() == before


@pytest.mark.parametrize("symlink_at", ["note", "old_temp"])
def test_running_review_note_write_never_follows_a_precreated_symlink(lab: Lab, symlink_at: str) -> None:
    note = Path(lab.env["C300X_CAMERA_RUNNING_NOTE"])
    victim = note.with_name("unrelated-private-file")
    victim.write_text("must remain untouched\n")
    link = note if symlink_at == "note" else Path(str(note) + ".tmp")
    link.unlink(missing_ok=True)
    link.symlink_to(victim)
    lab.restart_agent()
    assert victim.read_text() == "must remain untouched\n"
    assert not note.is_symlink() and note.stat().st_mode & 0o777 == 0o600
    assert lab.call()["running_fps"] == 15


@pytest.mark.parametrize("mode,expected_fps", [(0o644, 10), (0o666, 15)])
def test_running_review_legacy_note_requires_owner_only_write_access(
    lab: Lab, mode: int, expected_fps: int,
) -> None:
    note = Path(lab.env["C300X_CAMERA_RUNNING_NOTE"])
    note.write_text("boot-1 800 10 800 480 16 48 688 480\n")
    note.chmod(mode)
    lab.restart_agent()
    assert lab.call()["running_fps"] == expected_fps
    assert note.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("media_image", ["stock"], indirect=True)
@pytest.mark.parametrize("reboot", [True])
@pytest.mark.parametrize("failure", ["create", "rename", "boot_id"])
@pytest.mark.parametrize("change", [{"fps": 20}, {"size": "960x576"}])
def test_running_note_persistence_failure_blocks_updates_without_false_reboot(
    lab: Lab, failure: str, change: dict,
) -> None:
    note = Path(lab.env["C300X_CAMERA_RUNNING_NOTE"])
    note.unlink()
    if failure == "create":
        note = note.parent / "missing-parent" / "note"
        lab.env["C300X_CAMERA_RUNNING_NOTE"] = str(note)
    elif failure == "rename":
        note.mkdir()
    else:
        Path(lab.env["C300X_BOOT_ID_FILE"]).write_text("")
    target = Path(lab.env["C300X_MEDIA_GEOMETRY_TARGET"])
    before = lab.settings.read_bytes(), lab.stack.read_bytes(), target.read_bytes()
    lab.restart_agent()
    body = lab.call({**CONFIRM, "fps": 15})
    assert (body["running_fps"], body["running_size"], body["restart_required"], body["rebooting"]) == (0, "", False, False)
    body = lab.call({**CONFIRM, **change}, status=500)
    assert body["error"] == "camera_quality_running_note_write_failed"
    assert (lab.settings.read_bytes(), lab.stack.read_bytes(), target.read_bytes()) == before
    assert not lab.backup.exists()
    time.sleep(0.1)
    assert not (lab.settings.parent / "reboot-done").exists()
    lab.restart_agent()
    body = lab.call()
    assert (body["fps"], body["running_fps"], body["running_size"], body["restart_required"]) == (15, 0, "", False)
    if failure == "create":
        note.parent.mkdir()
    elif failure == "rename":
        note.rmdir()
    else:
        Path(lab.env["C300X_BOOT_ID_FILE"]).write_text("boot-1\n")
        lab.restart_agent()
    # A retry may persist the original in-memory baseline, never the requested values.
    body = lab.call({**CONFIRM, **change, "reboot": False})
    assert body["changed"] is True and body["restart_required"] is True
    lab.restart_agent()
    body = lab.call()
    assert body["running_fps"] == 15 and body["running_size"] == "688x480"
    assert body["restart_required"] is True


@pytest.fixture(scope="module")
def running_note_fsync_fault(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("running-note-fsync-fault")
    source = folder / "fault.c"
    source.write_text(r'''
#define _GNU_SOURCE
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>
int fsync(int fd) {
    char link[64], path[4096];
    const char *note = getenv("C300X_CAMERA_RUNNING_NOTE");
    snprintf(link,sizeof(link),"/proc/self/fd/%d",fd);
    ssize_t n = readlink(link,path,sizeof(path)-1);
    if (note && n >= 0) {
        path[n] = '\0';
        size_t len = strlen(note);
        if (!strncmp(path,note,len) && path[len] == '.') { errno = ENOSPC; return -1; }
    }
    return (int)syscall(SYS_fsync,fd);
}
''')
    library = folder / "fault.so"
    subprocess.run(["gcc", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror", str(source),
                    "-o", str(library)], check=True, capture_output=True, text=True)
    return library


@pytest.mark.parametrize("media_image", ["stock"], indirect=True)
def test_running_note_fsync_failure_preserves_existing_pending_baseline(
    lab: Lab, running_note_fsync_fault: Path,
) -> None:
    lab.call({**CONFIRM, "fps": 20})
    note = Path(lab.env["C300X_CAMERA_RUNNING_NOTE"])
    before = note.read_bytes()
    lab.env["LD_PRELOAD"] = str(running_note_fsync_fault)
    lab.restart_agent()
    body = lab.call()
    assert (body["fps"], body["running_fps"], body["restart_required"]) == (20, 15, True)
    assert lab.call({**CONFIRM, "fps": 24}, status=500)["error"] == "camera_quality_running_note_write_failed"
    assert note.read_bytes() == before
    assert not list(note.parent.glob(note.name + ".*"))
    assert lab.call()["restart_required"] is True
    lab.restart_agent()
    body = lab.call()
    assert (body["fps"], body["running_fps"], body["restart_required"]) == (20, 15, True)
    lab.env.pop("LD_PRELOAD")
    lab.restart_agent()
    assert lab.call({**CONFIRM, "fps": 24})["restart_required"] is True
    lab.restart_agent()
    assert lab.call()["running_fps"] == 15 and lab.call()["restart_required"] is True
