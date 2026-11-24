"""Exercise uninstall rollback with the real agent and isolated device files."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_qml_patch_script import _write_original_gui

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "native_agent/scripts/remove_agent.sh"
STACK = "<config><enable_speex>1</enable_speex></config>\n"
LINPHONE = (
    "[sound]\nrtp_ptnum=110\nrtp_map=speex/8000/1\n"
    "[audio_codec_0]\nmime=PCMU\nrate=8000\nenabled=0\n"
    "[audio_codec_1]\nmime=speex\nrate=8000\nenabled=1\n"
)
# Stand-in stock routing binary, built in as the 1.7.19 stock identity. It is
# larger than the last 1.7.19 patch range.
ROUTING_STOCK = bytes(index * 7 % 251 for index in range(0x40000))


def _routing_patches() -> tuple:
    spec = importlib.util.spec_from_file_location(
        "device_routing_builder", ROOT / "scripts/device_routing_builder.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.PATCHES


def _patched_stand_in() -> bytes:
    """The stand-in with the 1.7.19 writes; the build takes its range hashes."""
    data = bytearray(ROUTING_STOCK)
    for patch in ROUTING_PATCHES:
        for write in patch.writes:
            start = patch.offset + write.offset
            data[start:start + len(write.data)] = write.data
    return bytes(data)


ROUTING_PATCHES = _routing_patches()
ROUTING_PATCHED = _patched_stand_in()


@pytest.fixture(scope="module")
def removal_binary(tmp_path_factory: pytest.TempPathFactory) -> Path:
    build = tmp_path_factory.mktemp("removal-build")
    patched_ranges = "".join(
        f" -DC300X_DEVICE_PATCH_PATCHED_RANGE_SHA256_{index}="
        f'\\"{hashlib.sha256(ROUTING_PATCHED[patch.offset:patch.offset + patch.range_len]).hexdigest()}\\"'
        for index, patch in enumerate(ROUTING_PATCHES)
    )
    result = subprocess.run(
        ["make", "-C", str(ROOT / "native_agent"), f"BUILD_DIR={build}", "-j2", "all",
         "CFLAGS=-std=c11 -O2 -Wall -Wextra -Werror -pedantic -D_DEFAULT_SOURCE "
         "-D_POSIX_C_SOURCE=200809L -DC300X_DEVICE_PATCH_STOCK_SHA256="
         f'\\"{hashlib.sha256(ROUTING_STOCK).hexdigest()}\\"' + patched_ranges],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return build / "host/c300x-agent-native"


@pytest.fixture
def device(tmp_path: Path, removal_binary: Path) -> dict[str, str]:
    agent = tmp_path / "agent"
    backups = tmp_path / "backups"
    original = backups / "original"
    agent.mkdir()
    original.mkdir(parents=True)
    routing = tmp_path / "vendor-bin"
    routing.mkdir()
    (routing / "bt_answering_machine").write_bytes(ROUTING_STOCK)
    shutil.copy2(removal_binary, agent / "c300x-agent-native")
    (agent / "c300x-agent-native.pid").write_text("123\n")
    env = dict(os.environ)
    env.update({
        "C300X_AGENT_DIR": str(agent),
        "C300X_BACKUP_ROOT": str(backups),
        "C300X_AUDIO_BACKUP_DIR": str(original),
        "C300X_AUDIO_NO_REMOUNT": "1",
        "C300X_DEVICE_PATCH_NO_REMOUNT": "1",
        "C300X_ROUTING_TARGET_DIR": str(routing),
        "C300X_ROUTING_BACKUP_DIR": str(original / "home/bticino/bin"),
        "TEST_COMMAND_LOG": str(tmp_path / "commands.log"),
    })
    files = {
        "C300X_AUDIO_STACK_OPEN": ("stack.xml", STACK),
        "C300X_AUDIO_LINPHONE_CONF": ("linphone.conf", LINPHONE),
        "C300X_INIT_SCRIPT": ("init", "agent startup"),
        "C300X_INIT_LINK": ("init-link", "agent startup link"),
        "C300X_IPTABLES": ("iptables", "original firewall\n"),
        "C300X_IPTABLES6": ("iptables6", "original firewall\n"),
    }
    for key, (name, content) in files.items():
        path = tmp_path / name
        path.write_text(content)
        env[key] = str(path)
    gui = tmp_path / "gui"
    gui.mkdir()
    _write_original_gui(gui)
    env.update({
        "C300X_QML_PATCH_SCRIPT": str(ROOT / "native_agent/scripts/qml_patch.sh"),
        "C300X_QML_GUI_DIR": str(gui),
        "C300X_QML_BACKUP_DIR": str(original / "gui/skins/default"),
        "C300X_QML_NO_REMOUNT": "1",
        "C300X_QML_RELOAD_GUI": "0",
    })
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


def _set_pcmu_config(env: dict[str, str]) -> None:
    """Switch the codec config to PCMU. The drain patch is gone, so this only
    rewrites stack_open.xml and linphone.conf; the daemon is never touched."""

    result = _cli(env, "--audio-codec", "apply")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["state"] == "pcmu"


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


def test_uninstall_leaves_an_unconfigured_device_untouched(device: dict[str, str]) -> None:
    result = _remove(device)
    _assert_removed(device, result)
    assert Path(device["C300X_AUDIO_STACK_OPEN"]).read_text() == STACK


def test_uninstall_keeps_agent_and_backups_after_gui_start_rollback(device: dict[str, str]) -> None:
    source = Path(device["C300X_AGENT_DIR"]) / "qml"
    shutil.copytree(ROOT / "device_qml", source)
    env = {**device, "C300X_QML_SOURCE_DIR": str(source)}
    subprocess.run([device["C300X_QML_PATCH_SCRIPT"], "apply"],
                   env=env, check=True, capture_output=True, timeout=10)
    gui = Path(device["C300X_QML_GUI_DIR"])
    before = {p.relative_to(gui): p.read_bytes() for p in gui.rglob("*") if p.is_file()}
    device.update({"C300X_QML_RELOAD_GUI": "1", "C300X_QML_GUI_RELOAD_DELAY_SECONDS": "0",
                   "C300X_QML_GUI_WRAPPER": str(source / "missing-wrapper")})
    result = _remove(device)
    _assert_kept(device, result)
    assert "Failed to restore Display patch" in result.stderr
    assert {p.relative_to(gui): p.read_bytes() for p in gui.rglob("*") if p.is_file()} == before


def test_restore_cli_restores_the_codec_config_idempotently(device: dict[str, str]) -> None:
    _set_pcmu_config(device)
    for _ in range(2):
        result = _cli(device, "--restore-media-patches")
        assert result.returncode == 0, result.stderr
        assert Path(device["C300X_AUDIO_STACK_OPEN"]).read_text() == STACK
        assert Path(device["C300X_AUDIO_LINPHONE_CONF"]).read_text() == LINPHONE
    assert Path(device["C300X_BACKUP_ROOT"]).exists()


def test_uninstall_restores_the_codec_config_before_cleanup(device: dict[str, str]) -> None:
    _set_pcmu_config(device)
    _assert_removed(device, _remove(device))
    assert Path(device["C300X_AUDIO_STACK_OPEN"]).read_text() == STACK
    assert Path(device["C300X_AUDIO_LINPHONE_CONF"]).read_text() == LINPHONE


def test_uninstall_keeps_files_if_codec_restore_fails(device: dict[str, str]) -> None:
    _set_pcmu_config(device)
    # A file the agent cannot read the codec lines of is never rewritten.
    linphone = Path(device["C300X_AUDIO_LINPHONE_CONF"])
    linphone.write_bytes(linphone.read_bytes().replace(b"\n", b"\r\n"))
    _assert_kept(device, _remove(device))
    assert "<enable_speex>0</enable_speex>" in Path(device["C300X_AUDIO_STACK_OPEN"]).read_text()


PCMU_STACK = "<config><enable_speex>0</enable_speex></config>\n"
PCMU_LINPHONE = (
    "[sound]\nrtp_ptnum=0\nrtp_map=PCMU/8000/1\n"
    "[audio_codec_0]\nmime=PCMU\nrate=8000\nenabled=1\n"
    "[audio_codec_1]\nmime=speex\nrate=8000\nenabled=0\n"
    "[audio_codec_2]\nmime=speex\nrate=16000\nenabled=0\n"
)


def test_firmware_3_switches_to_speex_and_back_and_removal_keeps_its_pcmu(device: dict[str, str]) -> None:
    # Firmware 3.0.6 comes with PCMU and has no backup before the first switch.
    stack, linphone = Path(device["C300X_AUDIO_STACK_OPEN"]), Path(device["C300X_AUDIO_LINPHONE_CONF"])
    stack.write_text(PCMU_STACK)
    linphone.write_text(PCMU_LINPHONE)
    result = _cli(device, "--audio-codec", "restore")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["state"] == "speex"
    assert stack.read_text() == PCMU_STACK.replace("<enable_speex>0", "<enable_speex>1")
    assert linphone.read_text() == (
        "[sound]\nrtp_ptnum=110\nrtp_map=speex/8000/1\n"
        "[audio_codec_0]\nmime=PCMU\nrate=8000\nenabled=0\n"
        "[audio_codec_1]\nmime=speex\nrate=8000\nenabled=1\n"
        "[audio_codec_2]\nmime=speex\nrate=16000\nenabled=0\n"
    )
    _set_pcmu_config(device)
    assert (stack.read_text(), linphone.read_text()) == (PCMU_STACK, PCMU_LINPHONE)
    assert _cli(device, "--audio-codec", "restore").returncode == 0
    result = _cli(device, "--restore-media-patches")
    assert result.returncode == 0, result.stderr
    assert (stack.read_text(), linphone.read_text()) == (PCMU_STACK, PCMU_LINPHONE)


@pytest.mark.skipif(os.geteuid() == 0, reason="root may write a read-only directory")
@pytest.mark.parametrize("first,then", [("apply", "restore"), ("restore", "apply")])
def test_a_failed_second_write_leaves_both_files_as_they_were(
    device: dict[str, str], tmp_path: Path, first: str, then: str,
) -> None:
    # Firmware 1.7.19/2.0.2 (Speex) and 3.0.6 (PCMU): switch once, then back
    # towards the original codec with linphone.conf that cannot be written.
    stack = Path(device["C300X_AUDIO_STACK_OPEN"])
    folder = tmp_path / "linphone-folder"
    folder.mkdir()
    linphone = folder / "linphone.conf"
    if first == "restore":
        stack.write_text(PCMU_STACK)
        linphone.write_text(PCMU_LINPHONE)
    else:
        linphone.write_text(LINPHONE)
    device["C300X_AUDIO_LINPHONE_CONF"] = str(linphone)
    assert _cli(device, "--audio-codec", first).returncode == 0
    before = (stack.read_text(), linphone.read_text())
    folder.chmod(0o555)
    try:
        result = _cli(device, "--audio-codec", then)
    finally:
        folder.chmod(0o755)

    assert result.returncode != 0
    assert (stack.read_text(), linphone.read_text()) == before


def test_removal_after_a_firmware_update_changes_only_the_codec_lines(device: dict[str, str]) -> None:
    stack, linphone = Path(device["C300X_AUDIO_STACK_OPEN"]), Path(device["C300X_AUDIO_LINPHONE_CONF"])
    _set_pcmu_config(device)
    assert _cli(device, "--audio-codec", "restore").returncode == 0
    # A firmware update of the same family replaces both files; the backups
    # of the earlier firmware stay on their own partition.
    updated_stack = STACK.replace("</config>", "<new_setting>1</new_setting></config>")
    updated_linphone = LINPHONE + "[video]\nsize=vga\n"
    stack.write_text(updated_stack)
    linphone.write_text(updated_linphone)
    for switch_first in (False, True):
        if switch_first:
            _set_pcmu_config(device)
        result = _cli(device, "--restore-media-patches")
        assert result.returncode == 0, result.stdout + result.stderr
        assert (stack.read_text(), linphone.read_text()) == (updated_stack, updated_linphone)


def test_removal_of_an_unchanged_device_with_a_single_backup_succeeds(device: dict[str, str]) -> None:
    # The first switch saved stack_open.xml, then failed to save linphone.conf.
    (Path(device["C300X_AUDIO_BACKUP_DIR"]) / "stack_open.xml").write_text(STACK)
    result = _cli(device, "--restore-media-patches")
    assert result.returncode == 0, result.stdout + result.stderr
    assert Path(device["C300X_AUDIO_STACK_OPEN"]).read_text() == STACK
    assert Path(device["C300X_AUDIO_LINPHONE_CONF"]).read_text() == LINPHONE


def _patched_routing(env: dict[str, str]) -> tuple[Path, Path]:
    """The HA media user patched the routing binary and kept its stock backup."""
    target = Path(env["C300X_ROUTING_TARGET_DIR"], "bt_answering_machine")
    backup = Path(env["C300X_ROUTING_BACKUP_DIR"], "bt_answering_machine")
    backup.parent.mkdir(parents=True)
    backup.write_bytes(ROUTING_STOCK)
    target.write_bytes(ROUTING_PATCHED)
    target.chmod(0o751)
    return target, backup


def test_uninstall_restores_the_routing_binary_before_deleting_its_backup(device: dict[str, str]) -> None:
    target, _ = _patched_routing(device)
    _assert_removed(device, _remove(device))
    assert target.read_bytes() == ROUTING_STOCK
    assert not list(target.parent.glob("*.restore.*"))


@pytest.mark.parametrize("fault", ["corrupt_backup", "unknown_target", "missing_target", "remount"])
def test_uninstall_keeps_files_if_routing_restore_fails(device: dict[str, str], fault: str) -> None:
    target, backup = _patched_routing(device)
    if fault == "corrupt_backup":
        backup.write_bytes(b"x" + backup.read_bytes()[1:])
    elif fault == "unknown_target":
        target.write_bytes(b"x" * len(ROUTING_STOCK))
    elif fault == "missing_target":
        target.unlink()
    else:
        device["C300X_DEVICE_PATCH_NO_REMOUNT"] = "ro_busy"
    before = target.read_bytes() if target.exists() else None
    saved = backup.read_bytes()
    result = _remove(device)
    _assert_kept(device, result)
    assert "Failed to restore device routing" in result.stderr
    # Only a failed RO remount may leave / writable; then a reboot comes first.
    hint = "/ may still be writable, perform a full device reboot before retrying removal"
    assert (hint in result.stderr) == (fault == "remount")
    assert backup.read_bytes() == saved
    # The verified stock file is already in place when only the RO remount fails.
    assert (target.read_bytes() if target.exists() else None) == (saved if fault == "remount" else before)
    if fault == "remount":
        device["C300X_DEVICE_PATCH_NO_REMOUNT"] = "1"
        _assert_removed(device, _remove(device))


@pytest.mark.parametrize("target", [b"unknown routing build", None])
def test_uninstall_leaves_a_routing_binary_alone_the_agent_never_patched(
    device: dict[str, str], target: bytes | None,
) -> None:
    path = Path(device["C300X_ROUTING_TARGET_DIR"], "bt_answering_machine")
    if target is None:
        path.unlink()
    else:
        path.write_bytes(target)
    _assert_removed(device, _remove(device))
    assert (path.read_bytes() if path.exists() else None) == target


def test_uninstall_refuses_a_patched_routing_binary_without_its_backup(device: dict[str, str]) -> None:
    target, backup = _patched_routing(device)
    backup.unlink()
    result = _remove(device)
    _assert_kept(device, result)
    assert "Failed to restore device routing: routing_backup_missing" in result.stderr
    assert target.read_bytes() == ROUTING_PATCHED
    assert not backup.exists()


def test_uninstall_leaves_a_stock_routing_binary_with_a_stale_backup_alone(device: dict[str, str]) -> None:
    target, backup = _patched_routing(device)
    target.write_bytes(ROUTING_STOCK)
    backup.write_bytes(b"old unusable backup")
    _assert_removed(device, _remove(device))
    assert target.read_bytes() == ROUTING_STOCK
    assert target.stat().st_mode & 0o7777 == 0o751
    assert not list(target.parent.glob("*.restore.*"))
