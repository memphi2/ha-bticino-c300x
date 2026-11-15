"""Exercise init replacement with real local copies and cross-filesystem moves."""

import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from custom_components.bticino_c300x import device_installer as installer

ROOT = Path(__file__).resolve().parents[1]


class LocalClient:
    """Run generated commands only against temporary paths, never mount anything."""

    def __init__(self, *, fail_writes: bool) -> None:
        self.fail_writes = fail_writes
        self.mounts: list[str] = []

    def run(self, command: str, input_data: bytes | None = None) -> str:
        if command.startswith("python - "):
            command = shlex.quote(sys.executable) + command[len("python"):]
        prefix = 'mount() { printf "MOCK_MOUNT %s\\n" "$*" >&2; }; '
        if self.fail_writes:
            # EXDEV makes mv copy too. Limit real cp/mv writes, not the upload,
            # so both the old implementation and sibling staging face the fault.
            limited_copy = (
                "import os,resource,signal,sys; "
                "resource.setrlimit(resource.RLIMIT_FSIZE,(512,512)); "
                "signal.signal(signal.SIGXFSZ,signal.SIG_IGN); "
                "os.execv('/usr/bin/'+sys.argv[1],sys.argv[1:])"
            )
            for tool in ("cp", "mv"):
                prefix += (
                    f"{tool}() {{ {shlex.quote(sys.executable)} -c "
                    f"{shlex.quote(limited_copy)} {tool} \"$@\"; }}; "
                )
        result = subprocess.run(
            ["sh", "-c", prefix + command], input=input_data,
            capture_output=True, check=False, timeout=10,
        )
        self.mounts.extend(
            line for line in result.stderr.decode().splitlines()
            if line.startswith("MOCK_MOUNT")
        )
        if result.returncode:
            raise installer.C300XDeviceInstallError("device_install_failed")
        return result.stdout.decode()


@pytest.mark.parametrize("different_filesystems", [False, True])
@pytest.mark.parametrize("fail_writes", [False, True])
def test_startup_copy_failure_preserves_init_and_retry_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    different_filesystems: bool, fail_writes: bool,
) -> None:
    root_parent = Path("/dev/shm") if different_filesystems else tmp_path
    if not root_parent.is_dir():
        pytest.skip("separate temporary filesystem unavailable")
    with tempfile.TemporaryDirectory(dir=root_parent) as root_dir:
        root = Path(root_dir)
        if different_filesystems and root.stat().st_dev == tmp_path.stat().st_dev:
            pytest.skip("temporary directories are on the same filesystem")
        agent = tmp_path / "custom-agent"
        agent.mkdir()
        init = root / "init"
        link = root / "startup-link"
        original = b"#!/bin/sh\n# working original startup script\nexit 0\n"
        init.write_bytes(original)
        init.chmod(0o700)
        link.symlink_to(init)
        monkeypatch.setattr(installer, "REMOTE_INIT_SCRIPT", str(init))
        monkeypatch.setattr(installer, "REMOTE_INIT_LINK", str(link))
        source = ROOT / "custom_components/bticino_c300x/device_agent/init/c300x-native-agent"
        client = LocalClient(fail_writes=fail_writes)

        if fail_writes:
            with pytest.raises(installer.C300XDeviceInstallError):
                installer._install_startup_script_sync(client, source, str(agent))
            assert init.read_bytes() == original
            assert link.readlink() == init
            assert not Path(f"{init}.new").exists()
            assert client.mounts[-2:] == [
                "MOCK_MOUNT -o remount,rw /", "MOCK_MOUNT -o remount,ro /",
            ]
            client.fail_writes = False

        changed = installer._install_startup_script_sync(client, source, str(agent))
        assert str(init) in changed
        assert init.read_bytes() == installer._render_startup_script(source, str(agent))
        assert init.stat().st_mode & 0o777 == 0o700
        assert link.readlink() == init
        assert not Path(f"{init}.new").exists()
        assert not (agent / ".c300x-native-agent-init.new").exists()
        stamp = init.stat().st_mtime_ns
        mount_count = len(client.mounts)
        assert installer._install_startup_script_sync(client, source, str(agent)) == ()
        assert init.stat().st_mtime_ns == stamp
        assert len(client.mounts) == mount_count
