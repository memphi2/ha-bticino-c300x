"""Full-build apply admission using read-only originals and isolated temp copies."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE_ROOT = Path(os.environ.get("C300X_FIRMWARE_WORK", ROOT.parent / "c300x-fwpatch/work"))
FIRMWARES = ("c100x-1.5.8", "1.7.19", "2.0.2", "3.0.6")


@pytest.fixture(scope="module")
def apply_identity_binary(tmp_path_factory):
    binary = tmp_path_factory.mktemp("routing-apply-identity") / "probe"
    result = subprocess.run([
        "cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
        "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
        str(ROOT / "native_agent/test/device_routing_apply_identity_test.c"),
        *(str(ROOT / "native_agent/src" / name) for name in
          ("device_patch_io.c", "sha256.c", "string_util.c")), "-o", str(binary),
    ], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return binary


def run(binary, target, backup, action):
    return subprocess.run([str(binary), str(target.parent), str(backup.parent), action],
                          env={**os.environ, "C300X_DEVICE_PATCH_NO_REMOUNT": "1"},
                          capture_output=True, text=True, timeout=10)


@pytest.mark.parametrize("firmware", FIRMWARES)
@pytest.mark.parametrize("case", [
    "roundtrip", "stock_trailer", "stock_outside", "patched_trailer",
    "patched_outside", "missing_backup", "corrupt_backup", "stock_symlink",
    "stale_backup", "foreign_backup",
])
def test_apply_whole_identity(apply_identity_binary, tmp_path, firmware, case):
    original = FIRMWARE_ROOT / f"rootfs-{firmware}/home/bticino/bin/bt_answering_machine"
    if not original.is_file():
        pytest.skip(f"Extracted firmware unavailable: {original}")
    target = tmp_path / "bin/bt_answering_machine"
    backup = tmp_path / "backup/bt_answering_machine"
    target.parent.mkdir()
    backup.parent.mkdir()
    shutil.copy2(original, target)
    stock = target.read_bytes()
    binary = apply_identity_binary
    if case in {"stale_backup", "foreign_backup"}:
        if case == "foreign_backup":
            other = FIRMWARES[(FIRMWARES.index(firmware) + 1) % len(FIRMWARES)]
            shutil.copy2(FIRMWARE_ROOT / f"rootfs-{other}/home/bticino/bin/bt_answering_machine", backup)
        else:
            backup.write_bytes(b"stale recovery material")
        result = run(binary, target, backup, "apply")
        assert result.returncode == 0, result.stdout + result.stderr
        assert backup.read_bytes() == stock
        assert run(binary, target, backup, "restore").returncode == 0
        assert target.read_bytes() == stock
        return
    if case.startswith("patched") or case in {"roundtrip", "missing_backup", "corrupt_backup"}:
        result = run(binary, target, backup, "apply")
        assert result.returncode == 0, result.stdout + result.stderr
        assert backup.read_bytes() == stock
    else:
        backup.write_bytes(stock)
    if case.endswith("trailer"):
        target.write_bytes(target.read_bytes() + b"foreign-build-trailer")
    elif case.endswith("outside"):
        data = bytearray(target.read_bytes())
        data[0] ^= 1
        target.write_bytes(data)
    elif case == "missing_backup":
        backup.unlink()
    elif case == "corrupt_backup":
        backup.write_bytes(b"invalid recovery material")
    elif case == "stock_symlink":
        referent = tmp_path / "referent"
        target.rename(referent)
        target.symlink_to(referent)
    before = target.read_bytes()
    saved = backup.read_bytes() if backup.exists() else None
    result = run(binary, target, backup, "apply")
    assert target.read_bytes() == before
    assert (backup.read_bytes() if backup.exists() else None) == saved
    if case == "roundtrip":
        assert result.returncode == 0, result.stdout
        assert run(binary, target, backup, "restore").returncode == 0
        assert target.read_bytes() == stock
    else:
        assert result.returncode != 0, result.stdout
        assert "unsupported_routing_target_hash" in result.stdout
        if case != "stock_symlink":
            assert "state=unsupported" in run(binary, target, backup, "status").stdout
    assert not list(target.parent.glob("*.tmp"))
