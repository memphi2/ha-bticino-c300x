"""Exercise uninstall rollback with the real agent and isolated device files."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "native_agent/scripts/remove_agent.sh"
STACK = "<config><enable_speex>1</enable_speex></config>\n"
LINPHONE = (
    "[sound]\nrtp_ptnum=97\nrtp_map=speex/8000/1\n"
    "[audio_codec_0]\nmime=PCMU\nrate=8000\nenabled=0\n"
    "[audio_codec_1]\nmime=speex\nrate=8000\nenabled=1\n"
)


@pytest.fixture(scope="module")
def removal_binary(tmp_path_factory: pytest.TempPathFactory) -> Path:
    build = tmp_path_factory.mktemp("removal-build")
    subprocess.run(
        ["make", "-C", str(ROOT / "native_agent"), f"BUILD_DIR={build}", "-j2", "all"],
        check=True, capture_output=True, text=True,
    )
    return build / "host/c300x-agent-native"


@pytest.fixture
def device(tmp_path: Path, removal_binary: Path) -> dict[str, str]:
    agent = tmp_path / "agent"
    backups = tmp_path / "backups"
    original = backups / "original"
    agent.mkdir()
    original.mkdir(parents=True)
    shutil.copy2(removal_binary, agent / "c300x-agent-native")
    (agent / "c300x-agent-native.pid").write_text("123\n")
    env = dict(os.environ)
    env.update({
        "C300X_AGENT_DIR": str(agent),
        "C300X_BACKUP_ROOT": str(backups),
        "C300X_AUDIO_BACKUP_DIR": str(original),
        "C300X_MEDIA_TEARDOWN_BACKUP_DIR": str(original / "home/bticino/bin"),
        "C300X_MEDIA_TEARDOWN_PROC_ROOT": str(tmp_path / "absent-proc"),
        "C300X_AUDIO_NO_REMOUNT": "1",
        "C300X_DEVICE_PATCH_NO_REMOUNT": "1",
        "TEST_COMMAND_LOG": str(tmp_path / "commands.log"),
    })
    files = {
        "C300X_AUDIO_STACK_OPEN": ("stack.xml", STACK),
        "C300X_AUDIO_LINPHONE_CONF": ("linphone.conf", LINPHONE),
        "C300X_MEDIA_TEARDOWN_TARGET": ("media-target", "unmanaged firmware"),
        "C300X_INIT_SCRIPT": ("init", "agent startup"),
        "C300X_INIT_LINK": ("init-link", "agent startup link"),
        "C300X_IPTABLES": ("iptables", "original firewall\n"),
        "C300X_IPTABLES6": ("iptables6", "original firewall\n"),
    }
    for key, (name, content) in files.items():
        path = tmp_path / name
        path.write_text(content)
        env[key] = str(path)
    env["C300X_QML_PATCH_SCRIPT"] = str(tmp_path / "absent-qml-script")
    mocks = tmp_path / "commands"
    mocks.mkdir()
    for command in ("mount", "start-stop-daemon", "pidof", "killall", "ssh-init", "reboot"):
        path = mocks / command
        path.write_text(
            "#!/bin/sh\n"
            f'printf "%s\\n" "{command}" >> "$TEST_COMMAND_LOG"\n'
            f"exit {1 if command == 'pidof' else 0}\n"
        )
        path.chmod(0o700)
    env["PATH"] = str(mocks) + os.pathsep + env["PATH"]
    env["C300X_SSH_INIT"] = str(mocks / "ssh-init")
    env["C300X_REBOOT"] = str(mocks / "reboot")
    return env


def _cli(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(Path(env["C300X_AGENT_DIR"]) / "c300x-agent-native"), *args],
        env=env, capture_output=True, text=True, timeout=10,
    )


def _remove(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(SCRIPT), "--run-from-tmp"],
        env=env, capture_output=True, text=True, timeout=10,
    )


def _teardown_target_name() -> str:
    name = list("??_??_?????")
    for offset, value in (
        (0, "b"), (1, "t"), (3, "a"), (4, "v"),
        (6, "m"), (7, "e"), (8, "d"), (9, "i"), (10, "a"),
    ):
        name[offset] = value
    return "".join(name)


def _load_builder():
    import importlib.util

    path = ROOT / "scripts" / "media_teardown_builder.py"
    spec = importlib.util.spec_from_file_location("media_teardown_builder", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    import sys as _sys

    _sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _apply_pcmu(env: dict[str, str]) -> bytes:
    stock = os.environ.get("C300X_TEARDOWN_TEST_STOCK")
    if not stock or not Path(stock).is_file():
        pytest.skip("C300X_TEARDOWN_TEST_STOCK is required for verified firmware rollback")
    original = Path(stock).read_bytes()
    target = Path(env["C300X_MEDIA_TEARDOWN_TARGET"])
    target.write_bytes(original)
    result = _cli(env, "--audio-codec", "apply")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["state"] == "pcmu"
    # PCMU no longer applies the drain patch, so model a device from the coupled
    # release that still carries it: a patched daemon with a stock backup. The
    # removal path (and the startup rollback) must still return it to stock.
    _load_builder().patch_media(Path(stock), target)
    backup_dir = Path(env["C300X_MEDIA_TEARDOWN_BACKUP_DIR"])
    backup_dir.mkdir(parents=True, exist_ok=True)
    (backup_dir / _teardown_target_name()).write_bytes(original)
    return original


def _assert_kept(env: dict[str, str], result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode != 0
    assert "keeping agent files and backups in place" in result.stderr
    for key in ("C300X_AGENT_DIR", "C300X_BACKUP_ROOT", "C300X_INIT_SCRIPT", "C300X_INIT_LINK"):
        assert Path(env[key]).exists()
    assert "reboot" not in Path(env["TEST_COMMAND_LOG"]).read_text().splitlines()


def _assert_removed(env: dict[str, str], result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stdout + result.stderr
    for key in ("C300X_AGENT_DIR", "C300X_BACKUP_ROOT", "C300X_INIT_SCRIPT", "C300X_INIT_LINK"):
        assert not Path(env[key]).exists()
    deadline = time.monotonic() + 2
    while "reboot" not in Path(env["TEST_COMMAND_LOG"]).read_text().splitlines():
        assert time.monotonic() < deadline, "uninstall did not schedule reboot"
        time.sleep(0.01)


def test_uninstall_leaves_unmanaged_firmware_untouched(device: dict[str, str]) -> None:
    result = _remove(device)
    _assert_removed(device, result)
    assert Path(device["C300X_MEDIA_TEARDOWN_TARGET"]).read_text() == "unmanaged firmware"
    assert Path(device["C300X_AUDIO_STACK_OPEN"]).read_text() == STACK


def test_uninstall_keeps_unknown_firmware_and_its_backup(device: dict[str, str]) -> None:
    backup = Path(device["C300X_MEDIA_TEARDOWN_BACKUP_DIR"])
    backup.mkdir(parents=True)
    saved = backup / "bt_av_media"
    saved.write_bytes(b"unknown original")
    _assert_kept(device, _remove(device))
    assert saved.read_bytes() == b"unknown original"
    assert Path(device["C300X_MEDIA_TEARDOWN_TARGET"]).read_text() == "unmanaged firmware"


def test_restore_cli_restores_coupled_patches_idempotently(device: dict[str, str]) -> None:
    stock = _apply_pcmu(device)
    for _ in range(2):
        result = _cli(device, "--restore-media-patches")
        assert result.returncode == 0, result.stderr
        assert Path(device["C300X_MEDIA_TEARDOWN_TARGET"]).read_bytes() == stock
        assert Path(device["C300X_AUDIO_STACK_OPEN"]).read_text() == STACK
        assert Path(device["C300X_AUDIO_LINPHONE_CONF"]).read_text() == LINPHONE
    assert Path(device["C300X_BACKUP_ROOT"]).exists()


def test_uninstall_restores_both_codec_and_firmware_before_cleanup(device: dict[str, str]) -> None:
    stock = _apply_pcmu(device)
    _assert_removed(device, _remove(device))
    assert Path(device["C300X_MEDIA_TEARDOWN_TARGET"]).read_bytes() == stock
    assert Path(device["C300X_AUDIO_STACK_OPEN"]).read_text() == STACK
    assert Path(device["C300X_AUDIO_LINPHONE_CONF"]).read_text() == LINPHONE


@pytest.mark.parametrize("failure", ["missing", "corrupt", "unknown_target", "write_failure"])
def test_uninstall_preserves_files_when_firmware_restore_fails(
    device: dict[str, str], failure: str,
) -> None:
    _apply_pcmu(device)
    backup = next(Path(device["C300X_MEDIA_TEARDOWN_BACKUP_DIR"]).iterdir())
    target = Path(device["C300X_MEDIA_TEARDOWN_TARGET"])
    if failure == "missing":
        backup.unlink()
    elif failure == "corrupt":
        backup.write_bytes(b"corrupt")
    elif failure == "unknown_target":
        target.write_bytes(b"different firmware")
    else:
        Path(str(target) + ".tmp").mkdir()
    before = target.read_bytes()
    _assert_kept(device, _remove(device))
    assert target.read_bytes() == before


def test_uninstall_keeps_drain_patch_if_codec_restore_fails(device: dict[str, str]) -> None:
    _apply_pcmu(device)
    target = Path(device["C300X_MEDIA_TEARDOWN_TARGET"])
    patched = target.read_bytes()
    (Path(device["C300X_AUDIO_BACKUP_DIR"]) / "linphone.conf").unlink()
    _assert_kept(device, _remove(device))
    assert target.read_bytes() == patched
    assert "<enable_speex>0</enable_speex>" in Path(device["C300X_AUDIO_STACK_OPEN"]).read_text()
