"""Cross-process camera transaction ownership, using only isolated host files."""

from __future__ import annotations

import fcntl
import json
import os
import select
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "native_agent/src"
SETTINGS = "[Answering Machine]\nWidth=800\nHeight=480\nBitrateRtpH=800\nFpsRtpH=15\n"
CROP = (
    "<crop><left>16</left><top>48</top><width>688</width><height>480</height></crop>\n"
)
HARNESS = r"""
#define _POSIX_C_SOURCE 200809L
#include "camera_update_lock.h"
#include "camera_quality.h"
#include "camera_update.h"
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int c300x_device_camera_resolution_fixed(void) { return 0; }
int __real_c300x_camera_update(int low, const struct c300x_camera_values *before,
    const struct c300x_camera_values *after, int g0, int g1,
    const char *settings, const char *crop, int *ro, const char **error);
int __wrap_c300x_camera_update(int low, const struct c300x_camera_values *before,
    const struct c300x_camera_values *after, int g0, int g1,
    const char *settings, const char *crop, int *ro, const char **error) {
    if (getenv("PAUSE_UPDATE")) { puts("entered"); fflush(stdout); (void)getchar(); }
    return __real_c300x_camera_update(low,before,after,g0,g1,settings,crop,ro,error);
}
static int operation(const char *action, const char **error) {
    struct c300x_camera_quality quality;
    if (!strcmp(action,"restore")) return c300x_camera_quality_remove_patches(error);
    return c300x_camera_quality_apply(&quality,
        !strcmp(action,"invalid") ? 1 : !strcmp(action,"noop") ? 800 : 1200,15,NULL,error);
}
int main(int argc, char **argv) {
    const char *error = "";
    if (argc != 2) return 2;
    if (!strcmp(argv[1],"exec")) {
        int fd = c300x_camera_update_lock_acquire(&error);
        if (fd < 0) return 3;
        execl(argv[0],argv[0],"lock",(char *)NULL);
        close(fd); return 4;
    }
    if (!strcmp(argv[1],"hold")) {
        int fd = c300x_camera_update_lock_acquire(&error);
        if (fd < 0) return 3;
        printf("held %d\n", !!(fcntl(fd,F_GETFD) & FD_CLOEXEC)); fflush(stdout);
        (void)getchar(); close(fd); return 0;
    }
    int ok;
    if (!strcmp(argv[1],"lock")) {
        int fd = c300x_camera_update_lock_acquire(&error);
        ok = fd >= 0;
        if (fd >= 0) close(fd);
    } else if (!strcmp(argv[1],"repeat")) {
        const char *actions[] = {"noop","invalid","restore"};
        ok = 1;
        for (int i = 0; i < 60; i++) {
            int result = operation(actions[i % 3], &error);
            if (result != (i % 3 != 1)) { ok = 0; break; }
            int fd = c300x_camera_update_lock_acquire(&error);
            if (fd < 0) { ok = 0; break; }
            close(fd);
        }
    } else ok = operation(argv[1], &error);
    printf("{\"ok\":%d,\"error\":\"%s\"}\n",ok,error);
    return 0;
}
"""


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    folder = tmp_path_factory.mktemp("camera-lock-build")
    source = folder / "probe.c"
    source.write_text(HARNESS)
    binary = folder / "probe"
    modules = (
        "camera_update_lock",
        "camera_quality",
        "camera_restore",
        "camera_update",
        "camera_files",
        "camera_running",
        "camera_sizes",
        "camera_settings",
        "camera_crop",
        "device_file",
        "device_file_sync",
        "device_patch_io",
        "root_mount",
        "media_geometry_patch",
        "sha256",
        "string_util",
    )
    result = subprocess.run(
        [
            "gcc",
            "-std=c11",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            "-D_DEFAULT_SOURCE",
            "-I",
            str(SRC),
            str(source),
            *[str(SRC / f"{name}.c") for name in modules],
            "-Wl,--wrap=c300x_camera_update",
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return binary


@pytest.fixture
def lab(tmp_path, probe):
    settings, crop, lock = tmp_path / "settings", tmp_path / "crop", tmp_path / "lock"
    settings.write_text(SETTINGS)
    crop.write_text(CROP)
    media = tmp_path / "media"
    media.write_bytes(b"unmanaged generated test image")
    env = {
        **os.environ,
        "C300X_CAMERA_UPDATE_LOCK": str(lock),
        "C300X_CAMERA_QUALITY_FILE": str(settings),
        "C300X_CAMERA_CROP_FILE": str(crop),
        "C300X_MEDIA_GEOMETRY_TARGET": str(media),
        "C300X_MEDIA_GEOMETRY_RUNNING_TARGET": str(media),
        "C300X_MEDIA_GEOMETRY_BACKUP": str(tmp_path / "binary-backup"),
        "C300X_AUDIO_BACKUP_DIR": str(tmp_path / "backups"),
        "C300X_CAMERA_RUNNING_NOTE": str(tmp_path / "running"),
        "C300X_AUDIO_NO_REMOUNT": "1",
        "C300X_DEVICE_PATCH_NO_REMOUNT": "1",
    }

    def run(action):
        result = subprocess.run(
            [str(probe), action],
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=3,
        )
        return json.loads(result.stdout)

    return settings, crop, lock, env, run


def ready_line(process):
    assert select.select([process.stdout], [], [], 5)[0], (
        "probe did not reach transaction barrier"
    )
    return process.stdout.readline().strip()


@pytest.mark.parametrize("action", ["apply", "restore", "noop", "invalid"])
def test_external_owner_refuses_entire_public_operation(lab, action):
    settings, crop, lock, _, run = lab
    lock.touch(mode=0o600)
    with lock.open("r+") as fd:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert run(action) == {"ok": 0, "error": "update_busy"}
        assert settings.read_text() == SETTINGS and crop.read_text() == CROP
    assert run("lock")["ok"] == 1


def test_noop_and_validation_failures_release_lock_in_same_process(lab):
    settings, crop, lock, _, run = lab
    assert run("repeat")["ok"] == 1
    assert lock.exists() and lock.stat().st_mode & 0o777 == 0o600
    assert settings.read_text() == SETTINGS and crop.read_text() == CROP


def test_exec_does_not_inherit_lock(lab):
    _, _, _, _, run = lab
    assert run("exec")["ok"] == 1


@pytest.mark.parametrize("failure", ["read", "backup", "restore"])
def test_io_failure_paths_release_transaction_lock(lab, failure):
    settings, _, _, env, run = lab
    action = "apply"
    if failure == "read":
        settings.write_text("invalid settings")
    elif failure == "backup":
        Path(env["C300X_AUDIO_BACKUP_DIR"]).write_text("not a directory")
    else:
        assert run("apply")["ok"] == 1
        (Path(env["C300X_AUDIO_BACKUP_DIR"]) / "bt_answering_machine").write_text(
            "invalid backup"
        )
        action = "restore"
    assert run(action)["ok"] == 0
    assert run("lock")["ok"] == 1


@pytest.mark.parametrize(
    "owner,competitor", [("apply", "restore"), ("restore", "apply")]
)
def test_apply_and_uninstall_cannot_overlap(lab, probe, owner, competitor):
    settings, crop, _, env, run = lab
    if owner == "restore":
        assert run("apply")["ok"] == 1
    before = settings.read_bytes(), crop.read_bytes()
    process = subprocess.Popen(
        [str(probe), owner],
        env={**env, "PAUSE_UPDATE": "1"},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert ready_line(process) == "entered"
        assert run(competitor) == {"ok": 0, "error": "update_busy"}
        assert (settings.read_bytes(), crop.read_bytes()) == before
        stdout, stderr = process.communicate("\n", timeout=5)
        assert process.returncode == 0, stderr
        assert json.loads(stdout)["ok"] == 1
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
    assert run("restore")["ok"] == 1
    assert settings.read_text() == SETTINGS and crop.read_text() == CROP


def test_cloexec_and_process_exit_release_without_unlink(lab, probe):
    _, _, lock, env, run = lab
    process = subprocess.Popen(
        [str(probe), "hold"],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert ready_line(process) == "held 1"
        inode = lock.stat().st_ino
        assert run("lock")["error"] == "update_busy"
        process.kill()
        process.communicate(timeout=5)
        assert run("lock")["ok"] == 1
        assert lock.stat().st_ino == inode
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "directory", "public"])
def test_unsafe_lock_paths_fail_closed(lab, kind):
    settings, crop, lock, _, run = lab
    if kind == "symlink":
        lock.symlink_to(settings)
    elif kind == "hardlink":
        os.link(settings, lock)
    elif kind == "fifo":
        os.mkfifo(lock, 0o600)
    elif kind == "directory":
        lock.mkdir()
    else:
        lock.touch()
        lock.chmod(0o666)
    assert run("apply") == {"ok": 0, "error": "update_lock_invalid"}
    assert settings.read_text() == SETTINGS and crop.read_text() == CROP


def test_original_glibc_arm_lock_contention(tmp_path):
    sysroot = ROOT.parent / "c300x-fwpatch/work/rootfs-1.7.19"
    if (
        not (sysroot / "lib/libc.so.6").exists()
        or not shutil.which("qemu-arm")
        or not shutil.which("arm-linux-gnueabihf-gcc")
    ):
        pytest.skip("optional original libc and ARM/QEMU toolchain unavailable")
    source = tmp_path / "lock-probe.c"
    source.write_text("""
#include "camera_update_lock.h"
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>
int main(void) {
    const char *error = "";
    int fd = c300x_camera_update_lock_acquire(&error);
    if (fd < 0) puts(error);
    else { puts((fcntl(fd,F_GETFD) & FD_CLOEXEC) ? "ok" : "not_cloexec"); close(fd); }
    return 0;
}
""")
    binary = tmp_path / "lock-probe"
    result = subprocess.run(
        [
            "arm-linux-gnueabihf-gcc",
            "-std=c11",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            "-D_DEFAULT_SOURCE",
            "-D_TIME_BITS=32",
            "-I",
            str(SRC),
            str(source),
            str(SRC / "camera_update_lock.c"),
            str(SRC / "arm_start.S"),
            "-nostartfiles",
            f"-Wl,-rpath-link,{sysroot}/lib",
            f"-L{sysroot}/lib",
            "-l:libc.so.6",
            "-l:ld-linux-armhf.so.3",
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    lock = tmp_path / "lock"
    lock.touch(mode=0o600)

    def call():
        return subprocess.run(
            ["qemu-arm", "-L", str(sysroot), str(binary)],
            env={**os.environ, "C300X_CAMERA_UPDATE_LOCK": str(lock)},
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()

    with lock.open("r+") as fd:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert call() == "update_busy"
    assert call() == "ok"
