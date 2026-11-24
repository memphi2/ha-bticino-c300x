"""A cut SSH upload must never be moved over a live station file.

The remote side reads the payload with cat. When the SSH stream is cut, cat
still sees EOF and exits 0, so the staging file can be partial. These tests
run the generated commands in a local shell and cut the payload in half.
"""

import hashlib
import re
import subprocess
from pathlib import Path

import pytest

from custom_components.bticino_c300x import device_installer as installer

ROOT = Path(__file__).resolve().parents[1]


class LocalClient:
    def __init__(self, *, cut: bool) -> None:
        self.cut = cut
        self.commands: list[str] = []

    def run(self, command: str, input_data: bytes | None = None) -> str:
        self.commands.append(command)
        if self.cut and input_data:
            input_data = input_data[: len(input_data) // 2]
        prefix = 'mount() { :; }; '
        result = subprocess.run(["sh", "-c", prefix + command], input=input_data,
                                capture_output=True, check=False, timeout=10)
        if result.returncode:
            raise installer.C300XDeviceInstallError("device_install_failed")
        return result.stdout.decode()


def _put_file(client: LocalClient, source: Path, target: Path) -> bool:
    ssh = object.__new__(installer._AsyncSshDeviceSshClient)
    ssh.run = client.run  # type: ignore[method-assign]
    return ssh.put_file(source, str(target), "700")


def _write_file(client: LocalClient, source: Path, target: Path) -> bool:
    return installer._write_remote_file_sync(client, str(target), source.read_bytes(), mode="700")


@pytest.mark.parametrize("upload", [_put_file, _write_file])
def test_a_cut_upload_keeps_the_live_file_and_leaves_no_staging(tmp_path: Path, upload) -> None:
    source = tmp_path / "new-agent"
    source.write_bytes(b"\x7fELF new agent " * 512)
    target = tmp_path / "station" / "c300x-agent-native"
    target.parent.mkdir()
    target.write_bytes(b"\x7fELF working agent " * 512)
    target.chmod(0o700)

    with pytest.raises(installer.C300XDeviceInstallError):
        upload(LocalClient(cut=True), source, target)

    assert target.read_bytes() == b"\x7fELF working agent " * 512
    assert sorted(path.name for path in target.parent.iterdir()) == [target.name]

    assert upload(LocalClient(cut=False), source, target) is True
    assert target.read_bytes() == source.read_bytes()
    assert target.stat().st_mode & 0o777 == 0o700
    assert sorted(path.name for path in target.parent.iterdir()) == [target.name]


def test_staging_names_differ_between_install_runs(tmp_path: Path) -> None:
    source = tmp_path / "config.json"
    source.write_bytes(b"{}")
    names = set()
    for _ in range(2):
        client = LocalClient(cut=False)
        target = tmp_path / f"target-{len(names)}"
        _write_file(client, source, target)
        names |= set(re.findall(r"target-\d\.\S+\.new", client.commands[-1]))
    assert len(names) == 2


def test_a_cut_startup_script_upload_keeps_the_boot_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent, root = tmp_path / "agent", tmp_path / "root"
    agent.mkdir()
    root.mkdir()
    init, link = root / "init", root / "startup-link"
    original = b"#!/bin/sh\n# working original startup script\nexit 0\n"
    init.write_bytes(original)
    init.chmod(0o700)
    link.symlink_to(init)
    monkeypatch.setattr(installer, "REMOTE_INIT_SCRIPT", str(init))
    monkeypatch.setattr(installer, "REMOTE_INIT_LINK", str(link))
    source = ROOT / "custom_components/bticino_c300x/device_agent/init/c300x-native-agent"

    with pytest.raises(installer.C300XDeviceInstallError):
        installer._install_startup_script_sync(LocalClient(cut=True), source, str(agent))

    assert init.read_bytes() == original
    assert hashlib.sha256(init.read_bytes()).hexdigest() == hashlib.sha256(original).hexdigest()
    assert not list(agent.glob(".c300x-native-agent-init*"))
    assert sorted(path.name for path in root.iterdir()) == ["init", "startup-link"]
