"""Offline originals are read-only inputs; native operations use temp copies."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE_ROOT = Path(os.environ.get(
    "C300X_FIRMWARE_WORK", ROOT.parent / "c300x-fwpatch/work"
))
FIRMWARES = ("1.7.19", "2.0.2", "3.0.6")
PATCH_OFFSETS = dict(zip(FIRMWARES, (0x282F8, 0x28300, 0x27014), strict=True))


def original(firmware):
    path = FIRMWARE_ROOT / f"rootfs-{firmware}/home/bticino/bin/bt_answering_machine"
    if not path.is_file():
        pytest.skip(f"Extracted firmware unavailable: {path}")
    return path


@pytest.fixture(scope="module")
def routing_binary(tmp_path_factory):
    binary = tmp_path_factory.mktemp("routing-host") / "routing"
    subprocess.run([
        "gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
        "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
        str(ROOT / "native_agent/test/device_routing_firmware_test.c"),
        *[str(ROOT / "native_agent/src" / name) for name in
          ("device_patch_io.c", "root_mount.c", "sha256.c", "string_util.c")],
        "-o", str(binary),
    ], check=True, capture_output=True, text=True)
    return binary


def routing_run(binary, target, backup, action, **env):
    return subprocess.run([str(binary), str(target.parent), str(backup.parent), action],
                          env={**os.environ, "C300X_DEVICE_PATCH_NO_REMOUNT": "1", **env},
                          capture_output=True, text=True, timeout=10)


def prepare(tmp_path, firmware):
    target = tmp_path / "bin/bt_answering_machine"
    backup = tmp_path / "backup/bt_answering_machine"
    target.parent.mkdir()
    backup.parent.mkdir()
    shutil.copy2(original(firmware), target)
    target.chmod(0o751)
    return target, backup


@pytest.mark.parametrize("firmware", FIRMWARES)
@pytest.mark.parametrize("recovery", ["patched", "stock", "partial"])
def test_verified_roundtrip(routing_binary, tmp_path, firmware, recovery):
    target, backup = prepare(tmp_path, firmware)
    stock = target.read_bytes()
    result = routing_run(routing_binary, target, backup, "apply")
    assert result.returncode == 0, result.stdout + result.stderr
    assert target.read_bytes() != stock and backup.read_bytes() == stock
    if recovery == "stock":
        target.write_bytes(stock)
    elif recovery == "partial":
        data = bytearray(target.read_bytes())
        data[PATCH_OFFSETS[firmware]] ^= 1
        target.write_bytes(data)
    result = routing_run(routing_binary, target, backup, "restore")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "state=stock" in result.stdout
    assert target.read_bytes() == backup.read_bytes() == stock
    assert target.stat().st_mode & 0o7777 == 0o751
    assert not list(target.parent.glob("*.restore.*"))


def test_restore_ignores_predictable_temp_symlink(routing_binary, tmp_path):
    target, backup = prepare(tmp_path, "3.0.6")
    assert routing_run(routing_binary, target, backup, "apply").returncode == 0
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"untouched")
    target.with_suffix(".tmp").symlink_to(sentinel)
    result = routing_run(routing_binary, target, backup, "restore")
    assert result.returncode == 0, result.stdout + result.stderr
    assert sentinel.read_bytes() == b"untouched"
    assert target.read_bytes() == backup.read_bytes()


@pytest.mark.parametrize("firmware", FIRMWARES)
def test_foreign_model_backup_is_rejected(routing_binary, tmp_path, firmware):
    target, backup = prepare(tmp_path, firmware)
    assert routing_run(routing_binary, target, backup, "apply").returncode == 0
    # A negative identity fixture only; not a supported beta model/variant.
    shutil.copy2(original("c100x-1.5.8"), backup)
    before, saved = target.read_bytes(), backup.read_bytes()
    result = routing_run(routing_binary, target, backup, "restore")
    assert result.returncode != 0 and "routing_backup_invalid" in result.stdout
    assert target.read_bytes() == before and backup.read_bytes() == saved


@pytest.mark.parametrize("firmware", FIRMWARES)
@pytest.mark.parametrize("fault", [
    "corrupt_backup", "patched_backup", "truncated_backup", "foreign_backup",
    "corrupt_target", "unknown_target", "missing_target", "missing_backup",
    "target_symlink", "backup_symlink", "rename",
])
def test_invalid_restore_retains_recovery_material(routing_binary, tmp_path, firmware, fault):
    target, backup = prepare(tmp_path, firmware)
    assert routing_run(routing_binary, target, backup, "apply").returncode == 0
    env = {}
    if fault == "corrupt_backup":
        backup.write_bytes(b"\0" + backup.read_bytes()[1:])
    elif fault == "patched_backup":
        backup.write_bytes(target.read_bytes())
    elif fault == "truncated_backup":
        backup.write_bytes(backup.read_bytes()[:-1])
    elif fault == "foreign_backup":
        other = FIRMWARES[(FIRMWARES.index(firmware) + 1) % len(FIRMWARES)]
        shutil.copy2(original(other), backup)
        data = bytearray(target.read_bytes())
        data[PATCH_OFFSETS[firmware]] ^= 1
        target.write_bytes(data)
    elif fault == "corrupt_target":
        target.write_bytes(b"\0" + target.read_bytes()[1:])
    elif fault == "unknown_target":
        target.write_bytes(b"x" * target.stat().st_size)
    elif fault == "missing_target":
        target.unlink()
    elif fault == "missing_backup":
        backup.unlink()
    elif fault.endswith("symlink"):
        path = target if fault == "target_symlink" else backup
        sentinel = tmp_path / "sentinel"
        path.rename(sentinel)
        path.symlink_to(sentinel)
    elif fault == "rename":
        env["TEST_RENAME_FAIL"] = "1"
    before = target.read_bytes() if target.exists() else None
    saved = backup.read_bytes() if backup.exists() else None
    result = routing_run(routing_binary, target, backup, "restore", **env)
    assert result.returncode != 0, result.stdout
    assert (backup.read_bytes() if backup.exists() else None) == saved
    assert (target.read_bytes() if target.exists() else None) == before
    if fault.endswith("symlink"):
        assert path.is_symlink() and sentinel.read_bytes() == (before if path == target else saved)
    assert not list(target.parent.glob("*.restore.*"))


@pytest.mark.parametrize("firmware", FIRMWARES)
def test_restore_on_a_busy_root_is_done(routing_binary, tmp_path, firmware):
    """The replaced binary stays open in the daemon and blocks remount,ro.

    The restore is on disk then; it must answer success and say that /
    stays writable until the next boot, not fail after the fact.
    """
    target, backup = prepare(tmp_path, firmware)
    assert routing_run(routing_binary, target, backup, "apply").returncode == 0
    result = routing_run(routing_binary, target, backup, "restore",
                         C300X_DEVICE_PATCH_NO_REMOUNT="ro_busy")
    assert result.returncode == 0, result.stdout
    assert "state=stock" in result.stdout and "root_writable=1" in result.stdout
    assert target.read_bytes() == backup.read_bytes()
    assert not list(target.parent.glob("*.restore.*"))
