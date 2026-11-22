"""Own lifecycle tests, with generated portable fixtures and optional local firmware.

No proprietary fixture is distributed. The local original is read only; working
copies and compiled probes stay in pytest's temporary directory, outside releases.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "native_agent/src"
STOCK = "97b61ad80e67c1b3ea494956568645b93c7fe3ef359f77af9c7e2ad6dff1bf9e"
PATCHED = "baac8d478db5c4ae1baa46da963b379941d2952cfe047f3030b6a3182579821c"
STOCK_2_0_2 = "e08227abb4bbc8ec47cdb6a2cf875c1b32c70ad0a295482b5ee7d73672b7479b"
PATCHED_2_0_2 = "b8b278f801284f8e573700554054e886e5ab256c08f09a609c15bdff2bb73e1d"
MEDIA_NAME = list("b?_a?_m?d?a")
for _offset, _letter in ((1, "t"), (4, "v"), (7, "e"), (9, "i")):
    MEDIA_NAME[_offset] = _letter
MEDIA_NAME = "".join(MEDIA_NAME)
FIRMWARE = (
    ROOT.parent / "c300x-fwpatch/work/rootfs-1.7.19/home/bticino/bin" / MEDIA_NAME
)
FIRMWARE_2_0_2 = (
    ROOT.parent / "c300x-fwpatch/work/rootfs-2.0.2/home/bticino/bin" / MEDIA_NAME
)
GENERATED = bytes(186932)
GENERATED_2_0_2 = bytearray(GENERATED)
GENERATED_2_0_2[0x1A0:0x1B4] = bytes(range(1, 21))
GENERATED_2_0_2 = bytes(GENERATED_2_0_2)


def replace_words(original):
    data = bytearray(original)
    data[0x14A24:0x14A28] = bytes.fromhex("0f7da0e3")
    data[0x14DE4:0x14DE8] = bytes.fromhex("0f5da0e3")
    return bytes(data)


HARNESS = r"""
#define _GNU_SOURCE
#define _LARGEFILE64_SOURCE 1
#include "media_geometry_patch.h"
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>
static int fault(const char *name) {
    const char *p = getenv("FAIL");
    if (p && !strcmp(p, name)) { errno = EIO; return 1; }
    return 0;
}
int __real_fsync(int fd);
int __wrap_fsync(int fd) {
#ifdef __arm__
    struct stat64 st;
    if (syscall(SYS_fstat64,fd,&st)) return -1;
#else
    struct stat st;
    if (fstat(fd, &st)) return -1;
#endif
    if (fault(S_ISDIR(st.st_mode) ? "dirsync" : "filesync")) return -1;
    return __real_fsync(fd);
}
int __real_renameat(int a, const char *b, int c, const char *d);
int __wrap_renameat(int a, const char *b, int c, const char *d) {
    return fault("rename") ? -1 : __real_renameat(a,b,c,d);
}
int __real_linkat(int a, const char *b, int c, const char *d, int flags);
int __wrap_linkat(int a, const char *b, int c, const char *d, int flags) {
    return fault("link") ? -1 : __real_linkat(a,b,c,d,flags);
}
ssize_t __real_write(int fd, const void *p, size_t n);
ssize_t __wrap_write(int fd, const void *p, size_t n) {
    const char *replacement = getenv("REPLACE_WRITE_IMAGE");
    if (replacement && n == 186932) {
        unsigned char *bytes = malloc(n);
        FILE *in = fopen(replacement,"rb");
        if (!bytes || !in) { free(bytes); if (in) fclose(in); return -1; }
        size_t got = fread(bytes,1,n,in);
        fclose(in);
        ssize_t result = got == n ? __real_write(fd,bytes,n) : -1;
        free(bytes);
        return result;
    }
    return fault("write") ? -1 : __real_write(fd,p,n);
}
int __real_fchown(int fd, uid_t u, gid_t g);
int __wrap_fchown(int fd, uid_t u, gid_t g) {
    return fault("owner") ? -1 : __real_fchown(fd,u,g);
}
int c300x_patch_remount_root(const char *mode) {
    const char *swap = getenv("SWAP_IMAGE");
    if (swap && !strcmp(mode,"rw")) {
        FILE *in = fopen(swap,"rb"), *out = fopen(getenv("C300X_MEDIA_GEOMETRY_TARGET"),"r+b");
        if (!in || !out) { if (in) fclose(in); if (out) fclose(out); return 0; }
        unsigned char buffer[4096];
        size_t n;
        while ((n = fread(buffer,1,sizeof(buffer),in)) != 0) {
            if (fwrite(buffer,1,n,out) != n) { fclose(in); fclose(out); return 0; }
        }
        int ok = !ferror(in);
        fclose(in);
        return fclose(out) == 0 && ok;
    }
    return !fault(!strcmp(mode,"rw") ? "rw" : "ro");
}
static int proc_fd = -1;
int __real_open(const char *path, int flags, ...);
int __wrap_open(const char *path, int flags, ...) {
    mode_t mode = 0;
    if (flags & O_CREAT) { va_list ap; va_start(ap,flags); mode = va_arg(ap,int); va_end(ap); }
    if (!strcmp(path,"/proc/123/exe") && proc_fd >= 0) return dup(proc_fd);
#ifdef __arm__
    /* QEMU -L redirects / to the extracted firmware. Keep test file operations
     * on the host root, where pytest created the isolated temporary directory. */
    if (!strcmp(path,"/")) return __real_open("/proc/self/root",flags,mode);
#endif
    return __real_open(path,flags,mode);
}
int main(int argc, char **argv) {
    int ok = 1, ro = 0;
    const char *error = "";
    if (argc < 2) return 2;
    if (!strcmp(argv[1],"name")) {
        char name[32], short_name[2] = {'x','y'};
        int ok = c300x_media_geometry_process_name(name,sizeof(name));
        int short_ok = c300x_media_geometry_process_name(short_name,sizeof(short_name));
        printf("{\"name\":\"%s\",\"ok\":%d,\"short_ok\":%d,\"unchanged\":%d}\n",
            name,ok,short_ok,short_name[0]=='x' && short_name[1]=='y');
        return 0;
    }
    if (!strcmp(argv[1],"prepare")) ok = c300x_media_geometry_prepare(argv[2][0]-'0', &error);
    else if (!strcmp(argv[1],"apply")) ok = c300x_media_geometry_apply(argv[2][0]-'0', &ro, &error);
    else if (!strcmp(argv[1],"restore")) ok = c300x_media_geometry_restore(&ro, &error);
    else if (!strcmp(argv[1],"running")) {
        if (argc > 2) { proc_fd = open(argv[2],O_RDONLY); if (unlink(argv[2])) return 3; }
        printf("{\"state\":%d}\n",c300x_media_geometry_running_state(argc > 2 ? 123 : getpid()));
        return 0;
    }
    printf("{\"ok\":%d,\"ro_failed\":%d,\"state\":%d,\"error\":\"%s\"}\n",
        ok,ro,c300x_media_geometry_state(NULL),error);
    return 0;
}
"""


@pytest.fixture(
    scope="module",
    params=["generated", "generated-2.0.2", "original", "original-2.0.2"],
)
def probe(tmp_path_factory, request):
    firmware = FIRMWARE_2_0_2 if request.param.endswith("2.0.2") else FIRMWARE
    if request.param.startswith("original") and not firmware.exists():
        pytest.skip("optional local original firmware unavailable")
    folder = tmp_path_factory.mktemp("geometry-build")
    harness = folder / "probe.c"
    harness.write_text(HARNESS)
    binary = folder / f"probe-{request.param}"
    defines = []
    if request.param.startswith("generated"):
        defines = [
            f'-DC300X_MEDIA_GEOMETRY_STOCK_SHA256="{hashlib.sha256(GENERATED).hexdigest()}"',
            f'-DC300X_MEDIA_GEOMETRY_PATCHED_SHA256="{hashlib.sha256(replace_words(GENERATED)).hexdigest()}"',
            f'-DC300X_MEDIA_GEOMETRY_STOCK_SHA256_2_0_2="{hashlib.sha256(GENERATED_2_0_2).hexdigest()}"',
            f'-DC300X_MEDIA_GEOMETRY_PATCHED_SHA256_2_0_2="{hashlib.sha256(replace_words(GENERATED_2_0_2)).hexdigest()}"',
        ]
    subprocess.run(
        [
            "gcc",
            "-std=c11",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            *defines,
            "-I",
            str(SRC),
            str(harness),
            str(SRC / "media_geometry_patch.c"),
            str(SRC / "sha256.c"),
            *[
                f"-Wl,--wrap={name}"
                for name in ("fsync", "renameat", "linkat", "write", "fchown", "open")
            ],
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return binary


def variant_image(probe, *, other=False):
    second = probe.name.endswith("2.0.2") != other
    if probe.name.startswith("probe-generated"):
        return GENERATED_2_0_2 if second else GENERATED
    path = FIRMWARE_2_0_2 if second else FIRMWARE
    if not path.exists():
        pytest.skip("optional local original firmware unavailable")
    image = path.read_bytes()
    assert hashlib.sha256(image).hexdigest() == (STOCK_2_0_2 if second else STOCK)
    return image


@pytest.fixture
def lab(tmp_path, probe):
    original = variant_image(probe)
    target = tmp_path / "media-target"
    target.write_bytes(original)
    target.chmod(0o751)
    backup = tmp_path / "private/original/media-target"

    def run(action="state", enable=1, fail="", extra=None):
        result = subprocess.run(
            [str(probe), action, str(extra or enable)],
            check=True,
            timeout=5,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "C300X_MEDIA_GEOMETRY_TARGET": str(target),
                "C300X_MEDIA_GEOMETRY_BACKUP": str(backup),
                "FAIL": fail,
            },
        )
        return json.loads(result.stdout)

    return target, backup, original, run


def patched(original):
    data = replace_words(original)
    if original not in (GENERATED, GENERATED_2_0_2):
        expected = {STOCK: PATCHED, STOCK_2_0_2: PATCHED_2_0_2}[
            hashlib.sha256(original).hexdigest()
        ]
        assert hashlib.sha256(data).hexdigest() == expected
    return data


def test_round_trip_prepare_is_nonmutating_and_idempotent(lab):
    target, backup, original, run = lab
    before = target.stat()
    assert run("apply")["ok"] == 0
    assert run("prepare")["ok"] == 1
    assert target.stat().st_ino == before.st_ino
    assert target.read_bytes() == backup.read_bytes() == original
    saved = backup.stat()
    assert (saved.st_uid, saved.st_gid, saved.st_mode) == (
        before.st_uid,
        before.st_gid,
        before.st_mode,
    )
    assert backup.parent.stat().st_mode & 0o022 == 0
    assert run("apply")["state"] == 1
    assert target.read_bytes() == patched(original)
    after = target.stat()
    assert (after.st_uid, after.st_gid, after.st_mode) == (
        before.st_uid,
        before.st_gid,
        before.st_mode,
    )
    assert run("apply")["ok"] == 1
    assert target.stat().st_ino == after.st_ino
    assert run("restore")["state"] == 0
    assert target.read_bytes() == original
    assert run("restore")["ok"] == 1


def test_known_patch_without_backup_is_never_adopted_or_reconstructed(lab):
    target, backup, original, run = lab
    target.write_bytes(patched(original))
    before = target.stat()
    assert run("apply")["ok"] == 0
    assert run("prepare")["error"] == "geometry_backup_missing"
    assert target.stat().st_ino == before.st_ino
    assert target.read_bytes() == patched(original)
    assert not backup.exists()
    assert run("restore")["error"] == "geometry_backup_missing"
    assert target.read_bytes() == patched(original)


def test_unmanaged_stock_restore_is_a_read_only_noop(lab):
    target, backup, original, run = lab
    before = target.stat()
    assert run("restore", fail="rw")["ok"] == 1
    assert target.stat().st_ino == before.st_ino
    assert target.read_bytes() == original
    assert not backup.parent.parent.exists()


def test_missing_unmanaged_target_restore_is_noop_but_managed_is_error(lab):
    target, backup, original, run = lab
    target.unlink()
    assert run("restore")["ok"] == 1
    backup.parent.mkdir(parents=True, mode=0o700)
    backup.write_bytes(original)
    backup.chmod(0o600)
    assert run("restore")["ok"] == 0


def test_never_managed_missing_parent_directories_restore_without_writes(
    tmp_path, probe
):
    missing = tmp_path / "never-created"
    env = {
        **os.environ,
        "C300X_MEDIA_GEOMETRY_TARGET": str(missing / "vendor/media"),
        "C300X_MEDIA_GEOMETRY_BACKUP": str(missing / "backup/media"),
        "FAIL": "rw",
    }
    result = subprocess.run(
        [str(probe), "restore", "0"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert json.loads(result.stdout) == {
        "ok": 1,
        "state": -1,
        "ro_failed": 0,
        "error": "",
    }
    assert not missing.exists()


def test_direct_restore_uses_verified_existing_backup(lab):
    target, backup, original, run = lab
    target.write_bytes(patched(original))
    backup.parent.mkdir(parents=True, mode=0o755)
    backup.write_bytes(original)
    backup.chmod(0o751)
    assert run("restore")["state"] == 0
    assert target.read_bytes() == backup.read_bytes() == original


@pytest.mark.parametrize("which", ["target", "backup"])
def test_revalidate_after_prepare(lab, which):
    target, backup, original, run = lab
    assert run("prepare")["ok"] == 1
    path = target if which == "target" else backup
    altered = bytearray(path.read_bytes())
    altered[10] ^= 1
    path.write_bytes(altered)
    before = target.read_bytes(), backup.read_bytes()
    assert run("apply")["ok"] == 0
    assert (target.read_bytes(), backup.read_bytes()) == before


@pytest.mark.parametrize("target_patched", [False, True])
@pytest.mark.parametrize(
    "action,enable", [("prepare", 1), ("apply", 1), ("apply", 0), ("restore", 0)]
)
def test_backup_must_belong_to_exact_target_variant(
    lab, probe, target_patched, action, enable
):
    target, backup, original, run = lab
    if target_patched:
        target.write_bytes(patched(original))
    other = variant_image(probe, other=True)
    backup.parent.mkdir(parents=True, mode=0o755)
    backup.write_bytes(other)
    backup.chmod(0o751)
    before = target.read_bytes(), backup.read_bytes()
    result = run(action, enable=enable)
    assert result["ok"] == 0 and result["error"] == "geometry_backup_invalid"
    assert (target.read_bytes(), backup.read_bytes()) == before


def test_build_id_bytes_are_never_normalized(lab):
    target, backup, original, run = lab
    altered = bytearray(original)
    altered[0x1A0] ^= 0x80
    target.write_bytes(altered)
    assert run("prepare")["error"] == "geometry_target_invalid"
    assert target.read_bytes() == altered and not backup.exists()


@pytest.mark.parametrize("hook", ["SWAP_IMAGE", "REPLACE_WRITE_IMAGE"])
def test_variant_rechecked_before_write_and_before_publish(lab, probe, hook):
    target, backup, original, run = lab
    assert run("prepare")["ok"] == 1
    other = variant_image(probe, other=True)
    replacement = other if hook == "SWAP_IMAGE" else patched(other)
    swap = target.with_name("other-variant")
    swap.write_bytes(replacement)
    inode = target.stat().st_ino
    result = subprocess.run(
        [str(probe), "apply", "1"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
        env={
            **os.environ,
            "C300X_MEDIA_GEOMETRY_TARGET": str(target),
            "C300X_MEDIA_GEOMETRY_BACKUP": str(backup),
            hook: str(swap),
        },
    )
    body = json.loads(result.stdout)
    assert body["ok"] == 0
    assert body["error"] == (
        "geometry_target_changed" if hook == "SWAP_IMAGE" else "geometry_write_failed"
    )
    assert target.stat().st_ino == inode
    assert target.read_bytes() == (other if hook == "SWAP_IMAGE" else original)
    assert backup.read_bytes() == original


def test_writable_by_others_backup_rejected(lab):
    target, backup, original, run = lab
    backup.parent.mkdir(parents=True, mode=0o700)
    backup.write_bytes(original)
    backup.chmod(0o666)
    assert run("prepare")["ok"] == 0
    assert target.read_bytes() == original


@pytest.mark.parametrize("mutation", ["partial", "extra", "short", "unrelated"])
def test_unknown_targets_fail_closed(lab, mutation):
    target, backup, original, run = lab
    data = bytearray(original)
    if mutation == "partial":
        data[0x14A24:0x14A28] = bytes.fromhex("0f7da0e3")
    if mutation == "extra":
        data += b"x"
    if mutation == "short":
        data.pop()
    if mutation == "unrelated":
        data[123] ^= 1
    target.write_bytes(data)
    assert run("prepare")["ok"] == run("apply")["ok"] == 0
    assert not backup.exists()
    # Unmanaged unsupported firmware is not changed by uninstall.
    assert run("restore")["ok"] == 1
    backup.parent.mkdir(parents=True, mode=0o700)
    backup.write_bytes(original)
    backup.chmod(0o600)
    assert run("restore")["ok"] == 0
    assert target.read_bytes() == data


@pytest.mark.parametrize("bad", [b"corrupt", b""])
def test_corrupt_backup_never_replaced(lab, bad):
    target, backup, original, run = lab
    backup.parent.mkdir(parents=True, mode=0o700)
    backup.write_bytes(bad)
    for action in ("prepare", "apply", "restore"):
        assert run(action)["ok"] == 0
        assert backup.read_bytes() == bad and target.read_bytes() == original


@pytest.mark.parametrize(
    "where", ["target", "target_parent", "backup", "backup_parent"]
)
def test_symlinks_rejected(lab, where):
    target, backup, original, run = lab
    victim = target.parent / "victim"
    victim.write_bytes(original)
    if where == "target":
        target.unlink()
        target.symlink_to(victim)
    elif where == "backup":
        backup.parent.mkdir(parents=True, mode=0o700)
        backup.symlink_to(victim)
    elif where == "backup_parent":
        backup.parent.parent.symlink_to(target.parent)
    else:
        folder = target.parent
        moved = folder.with_name(folder.name + "-real")
        folder.rename(moved)
        folder.symlink_to(moved, target_is_directory=True)
    for action in ("prepare", "apply", "restore"):
        assert run(action)["ok"] == 0


@pytest.mark.parametrize("failure", ["write", "filesync", "link", "dirsync"])
def test_backup_failure_leaves_target_unchanged(lab, failure):
    target, backup, original, run = lab
    backup.parent.mkdir(parents=True, mode=0o700)
    assert run("prepare", fail=failure)["ok"] == 0
    assert target.read_bytes() == original
    if backup.exists():
        assert backup.read_bytes() == original


@pytest.mark.parametrize("failure", ["write", "filesync", "rename", "owner", "rw"])
def test_prepublication_failure_leaves_whole_old_state(lab, failure):
    target, backup, original, run = lab
    assert run("prepare")["ok"] == 1
    assert run("apply", fail=failure)["ok"] == 0
    assert target.read_bytes() == backup.read_bytes() == original
    assert not list(target.parent.glob(".geometry.*.tmp"))


def test_postrename_sync_failure_is_reported_with_whole_new_state(lab):
    target, backup, original, run = lab
    assert run("prepare")["ok"] == 1
    result = run("apply", fail="dirsync")
    assert result["ok"] == 0 and result["state"] == 1
    assert target.read_bytes() == patched(original)
    assert run("apply", enable=0)["state"] == 0


def test_ro_failure_exposes_successful_replacement(lab):
    _, _, _, run = lab
    assert run("prepare")["ok"] == 1
    result = run("apply", fail="ro")
    assert result["ok"] == 1 and result["ro_failed"] == 1 and result["state"] == 1


def test_invalid_enable_and_hardlinks_rejected(lab):
    target, _, _, run = lab
    assert run("prepare", enable=2)["ok"] == 0
    os.link(target, target.with_name("other"))
    assert run("prepare")["ok"] == 0


def test_running_helper_reads_deleted_inode_not_installed_target(lab):
    target, _, original, run = lab
    target.write_bytes(patched(original))
    old = target.with_name("running-stock")
    old.write_bytes(original)
    assert run("running", extra=old)["state"] == 0
    assert not old.exists()
    assert run()["state"] == 1


def test_nonprivate_backup_directory_rejected(lab):
    target, backup, original, run = lab
    backup.parent.mkdir(parents=True, mode=0o777)
    backup.parent.chmod(0o777)
    assert run("prepare")["ok"] == 0
    assert not backup.exists()
    assert target.read_bytes() == original


def test_concurrent_backup_creation_and_stale_temp_symlink(lab, probe):
    target, backup, original, _ = lab
    victim = target.with_name("untouched")
    victim.write_text("sentinel")
    backup.parent.mkdir(parents=True, mode=0o700)
    (backup.parent / ".geometry.stale.tmp").symlink_to(victim)
    env = {
        **os.environ,
        "C300X_MEDIA_GEOMETRY_TARGET": str(target),
        "C300X_MEDIA_GEOMETRY_BACKUP": str(backup),
    }
    processes = [
        subprocess.Popen(
            [str(probe), "prepare", "1"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(4)
    ]
    for process in processes:
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr
        result = json.loads(stdout)
        assert result["ok"] == 1 or result["error"] == "geometry_busy"
    assert backup.read_bytes() == original
    assert victim.read_text() == "sentinel"
    assert target.read_bytes() == original


def test_held_binary_lock_fails_busy_without_mutation(lab):
    target, backup, original, run = lab
    assert run("prepare")["ok"] == 1
    with (backup.parent / ".geometry.lock").open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run("apply")
        assert result["ok"] == 0 and result["error"] == "geometry_busy"
    assert target.read_bytes() == original


def test_exact_process_name_and_short_buffer(lab):
    _, _, _, run = lab
    assert run("name") == {"name": MEDIA_NAME, "ok": 1, "short_ok": 0, "unchanged": 1}


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses permission restrictions")
@pytest.mark.parametrize("where", ["target", "backup_parent"])
def test_permission_denied_is_not_absence(lab, where):
    target, backup, _, run = lab
    path = target if where == "target" else backup.parent
    if where != "target":
        path.mkdir(parents=True, mode=0o700)
    before = path.stat().st_mode & 0o777
    path.chmod(0)
    try:
        assert run("restore")["ok"] == 0
    finally:
        path.chmod(before)


def test_dangling_backup_symlink_is_not_absence(lab):
    target, backup, original, run = lab
    backup.parent.mkdir(parents=True, mode=0o700)
    backup.symlink_to(target.with_name("missing"))
    assert run("restore")["ok"] == 0
    assert backup.is_symlink() and target.read_bytes() == original


def test_existing_uninstall_backup_root_is_used(lab, probe):
    target, _, original, _ = lab
    root = target.parent / "custom-backups/original"
    env = {
        **os.environ,
        "C300X_MEDIA_GEOMETRY_TARGET": str(target),
        "C300X_MEDIA_GEOMETRY_BACKUP": "",
        "C300X_AUDIO_BACKUP_DIR": str(root),
    }
    for action, expected in (("prepare", 0), ("apply", 1), ("restore", 0)):
        result = subprocess.run(
            [str(probe), action, "1"],
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        body = json.loads(result.stdout)
        assert body["ok"] == 1 and body["state"] == expected
    assert (root / "home/bticino/bin" / MEDIA_NAME).read_bytes() == original
    assert not (root / "media_geometry").exists()


@pytest.mark.parametrize(
    "firmware,stock_hash", [(FIRMWARE, STOCK), (FIRMWARE_2_0_2, STOCK_2_0_2)]
)
def test_original_glibc_arm_qemu_lifecycle(tmp_path, firmware, stock_hash):
    if (
        not firmware.exists()
        or not shutil.which("qemu-arm")
        or not shutil.which("arm-linux-gnueabihf-gcc")
    ):
        pytest.skip("original firmware and ARM/QEMU toolchain required")
    sysroot = firmware.parents[3]
    harness = tmp_path / "probe.c"
    harness.write_text(HARNESS)
    binary = tmp_path / "probe-arm"
    subprocess.run(
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
            str(harness),
            str(SRC / "media_geometry_patch.c"),
            str(SRC / "sha256.c"),
            str(SRC / "arm_start.S"),
            *[
                f"-Wl,--wrap={name}"
                for name in ("fsync", "renameat", "linkat", "write", "fchown", "open")
            ],
            "-nostartfiles",
            f"-Wl,-rpath-link,{sysroot}/lib",
            f"-L{sysroot}/lib",
            "-l:libc.so.6",
            "-l:ld-linux-armhf.so.3",
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    target, backup = tmp_path / "media", tmp_path / "private/original"
    original = firmware.read_bytes()
    assert hashlib.sha256(original).hexdigest() == stock_hash
    target.write_bytes(original)
    target.chmod(0o755)
    env = {
        **os.environ,
        "C300X_MEDIA_GEOMETRY_TARGET": str(target),
        "C300X_MEDIA_GEOMETRY_BACKUP": str(backup),
    }
    for action, enable, state in [
        ("prepare", 1, 0),
        ("apply", 1, 1),
        ("restore", 0, 0),
        ("apply", 1, 1),
    ]:
        result = subprocess.run(
            ["qemu-arm", "-L", str(sysroot), str(binary), action, str(enable)],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        body = json.loads(result.stdout)
        assert body["ok"] == 1 and body["state"] == state, body
    assert backup.read_bytes() == original
    assert target.read_bytes() == patched(original)
