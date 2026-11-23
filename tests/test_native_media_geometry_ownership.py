"""Optional fakeroot regressions for vendor-owned shared backup directories.

All ownership changes affect private fixtures through fakeroot, never the host
or a device. Both the native probe and HTTP lab come from existing tests.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from test_native_camera_quality import binary as camera_binary
from test_native_media_geometry_patch import (
    FIRMWARE,
    ROOT,
    patched,
    probe,
    variant_image,
)

__all__ = ["camera_binary", "probe"]
FAKEROOT = shutil.which("fakeroot")
pytestmark = pytest.mark.skipif(FAKEROOT is None, reason="optional local fakeroot required")


def _run_worker(case: str, binary: Path, folder: Path) -> None:
    result = subprocess.run(
        [FAKEROOT, sys.executable, str(Path(__file__).resolve()), case, str(binary), str(folder)],
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
             "PYTHONPATH": os.pathsep.join((str(ROOT), str(ROOT / "tests")))},
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("case", ["vendor-parent", "agent-parent"])
def test_shared_backup_full_original_and_idempotent_restore(probe, tmp_path, case):
    _run_worker(case, probe, tmp_path)


@pytest.mark.parametrize("case", [
    "other-owner", "group-write", "world-write", "foreign-lock", "public-lock",
    "lock-symlink", "lock-hardlink", "parent-symlink", "backup-symlink",
    "backup-hardlink", "unknown-target", "foreign-backup",
])
def test_shared_backup_rejects_unsafe_metadata_and_identity(probe, tmp_path, case):
    _run_worker(case, probe, tmp_path)


def test_http_save_and_uninstall_preserve_vendor_owned_shared_backups(camera_binary, tmp_path):
    if not FIRMWARE.exists():
        pytest.skip("optional local original firmware required")
    _run_worker("http", camera_binary, tmp_path)


def _metadata(path: Path) -> tuple:
    st = path.stat()
    return st.st_uid, st.st_gid, st.st_mode & 0o7777, st.st_ino


def _shared_backup(folder: Path) -> tuple[Path, Path, Path]:
    root = folder / "home/bticino/cfg/extra/c300x-device-file-backups/original"
    parent = root / "home/bticino/bin"
    parent.mkdir(parents=True)
    parent.chmod(0o755)
    os.chown(parent, 1000, 1000)
    neighbor = parent / "bt_answering_machine"
    neighbor.write_bytes(b"existing routing recovery material\n")
    neighbor.chmod(0o751)
    os.chown(neighbor, 1000, 1000)
    return root, parent / "bt_av_media", neighbor


def _probe_worker(case: str, binary: Path, folder: Path) -> None:
    assert os.geteuid() == os.getegid() == 0
    original = variant_image(binary)
    target = folder / "home/bticino/bin/bt_av_media"
    target.parent.mkdir(parents=True)
    target.write_bytes(original)
    target.chmod(0o755)
    os.chown(target, 1000, 1000)
    root, backup, neighbor = _shared_backup(folder)
    env = {**os.environ, "C300X_MEDIA_GEOMETRY_TARGET": str(target),
           "C300X_AUDIO_BACKUP_DIR": str(root)}
    env.pop("C300X_MEDIA_GEOMETRY_BACKUP", None)
    env.pop("FAIL", None)
    neighbor_before = neighbor.read_bytes(), _metadata(neighbor)

    def run(action: str) -> dict:
        result = subprocess.run([str(binary), action, "1"], env=env,
                                capture_output=True, text=True, timeout=10, check=True)
        return json.loads(result.stdout)

    if case == "agent-parent":
        os.chown(backup.parent, 0, 0)
    elif case == "other-owner":
        os.chown(backup.parent, 1001, 1001)
    elif case in ("group-write", "world-write"):
        backup.parent.chmod(0o775 if case == "group-write" else 0o757)
    elif case in ("foreign-lock", "public-lock", "lock-hardlink"):
        lock = backup.parent / ".geometry.lock"
        lock.touch(mode=0o600)
        if case == "foreign-lock":
            os.chown(lock, 1000, 1000)
        elif case == "public-lock":
            lock.chmod(0o644)
        else:
            os.link(lock, folder / "lock-alias")
    elif case == "lock-symlink":
        (backup.parent / ".geometry.lock").symlink_to(neighbor)
    elif case == "parent-symlink":
        parent = backup.parent
        moved = parent.with_name("bin-real")
        parent.rename(moved)
        parent.symlink_to(moved, target_is_directory=True)
    elif case == "backup-symlink":
        backup.symlink_to(target)
    elif case == "backup-hardlink":
        backup.write_bytes(original)
        os.chown(backup, 1000, 1000)
        os.link(backup, folder / "backup-alias")
    elif case == "unknown-target":
        target.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    elif case == "foreign-backup":
        backup.write_bytes(variant_image(binary, other=True))
        backup.chmod(0o755)
        os.chown(backup, 1000, 1000)

    directory_before = _metadata(backup.parent)
    target_before = target.read_bytes(), _metadata(target)
    backup_before = backup.read_bytes() if backup.exists() else None
    if case not in ("vendor-parent", "agent-parent"):
        result = run("prepare")
        expected = "geometry_target_invalid" if case == "unknown-target" else "geometry_backup_invalid"
        assert result["ok"] == 0 and result["error"] == expected, result
        assert (target.read_bytes(), _metadata(target)) == target_before
        assert (backup.read_bytes() if backup.exists() else None) == backup_before
        if case == "legacy-rejection":
            assert not (backup.parent / ".geometry.lock").exists()
            sys.stdout.write(json.dumps(result) + "\n")
    else:
        assert run("prepare")["ok"] == 1
        assert target.read_bytes() == backup.read_bytes() == original
        assert _metadata(target) == target_before[1]
        assert _metadata(backup)[:3] == (1000, 1000, 0o755)
        assert _metadata(backup.parent / ".geometry.lock")[:3] == (0, 0, 0o600)
        saved = _metadata(backup)
        assert run("prepare")["ok"] == 1
        for _ in range(2):
            assert run("apply")["ok"] == 1
            assert target.read_bytes() == patched(original)
            inode = target.stat().st_ino
            assert run("apply")["ok"] == 1
            assert target.stat().st_ino == inode
            assert run("restore")["ok"] == 1
            assert target.read_bytes() == original
            inode = target.stat().st_ino
            assert run("restore")["ok"] == 1
            assert target.stat().st_ino == inode
            assert backup.read_bytes() == original and _metadata(backup) == saved
            assert _metadata(target)[:3] == (1000, 1000, 0o755)
    assert _metadata(backup.parent) == directory_before
    assert (neighbor.read_bytes(), _metadata(neighbor)) == neighbor_before
    assert not list(backup.parent.glob(".geometry.*.tmp"))


def _http_worker(binary: Path, folder: Path) -> None:
    from test_native_camera_quality import CONFIRM, SETTINGS, STACK, lab

    assert os.geteuid() == os.getegid() == 0
    original = FIRMWARE.read_bytes()
    context = lab.__wrapped__(binary, folder, False, False, original)
    instance = next(context)
    try:
        root, backup, neighbor = _shared_backup(folder)
        target = Path(instance.env["C300X_MEDIA_GEOMETRY_TARGET"])
        os.chown(target, 1000, 1000)
        instance.env.pop("C300X_MEDIA_GEOMETRY_BACKUP")
        instance.env["C300X_AUDIO_BACKUP_DIR"] = str(root)
        instance.restart_agent()
        before = _metadata(backup.parent), neighbor.read_bytes(), _metadata(neighbor)
        assert "960x576" in instance.call()["sizes"]
        payload = {**CONFIRM, "size": "960x576", "fps": 24, "bitrate_kbps": 3000}
        assert instance.call(payload)["size"] == "960x576"
        assert backup.read_bytes() == original and target.read_bytes() == patched(original)
        saved = _metadata(backup)
        inode = target.stat().st_ino
        assert instance.call(payload)["changed"] is False
        assert target.stat().st_ino == inode
        for _ in range(2):
            result = subprocess.run([str(binary), "--restore-media-patches"], env=instance.env,
                                    capture_output=True, text=True, timeout=10)
            assert result.returncode == 0, result.stdout + result.stderr
            assert target.read_bytes() == backup.read_bytes() == original
            assert _metadata(backup) == saved
            assert _metadata(target)[:3] == (1000, 1000, 0o755)
            assert instance.settings.read_text() == SETTINGS
            assert instance.stack.read_text() == STACK
        assert (_metadata(backup.parent), neighbor.read_bytes(), _metadata(neighbor)) == before
    finally:
        context.close()


if __name__ == "__main__":
    mode, executable, directory = sys.argv[1:]
    if mode == "http":
        _http_worker(Path(executable), Path(directory))
    else:
        _probe_worker(mode, Path(executable), Path(directory))
