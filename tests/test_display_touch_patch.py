"""The swipe threshold patch of the display library: once, checked, reversible."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native_agent"
NAME = "libQtGuiE.so.4.8.7"
OFFSET = 0x180094
OURS = bytes.fromhex("1000a0e31eff2fe1")
STOCK_SHA256 = "bdbff744eebe0f8acbf13d9aebb7868e2f60c9cfc9ffd1a7014abbee86701fe4"
PATCHED_SHA256 = "8088d9cdc83aaecb875357becb1579be273e9c34fa28c2dadb470db6d4080b5e"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build(folder: Path, defines: dict[str, str]) -> Path:
    binary = folder / "probe"
    sources = [NATIVE / "src" / name for name in ("display_touch.c", "device_patch_io.c", "sha256.c", "string_util.c")]
    subprocess.run(
        ["gcc", "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror", "-D_DEFAULT_SOURCE",
         *[f"-D{key}={json.dumps(value)}" for key, value in defines.items()],
         str(NATIVE / "test/display_touch_test.c"), *map(str, sources), "-o", str(binary)],
        check=True, capture_output=True, text=True,
    )
    return binary


class _Device:
    """A stand-in library of zeros: no byte of the real file is needed."""

    def __init__(self, folder: Path, patched_sha256: str | None = None) -> None:
        self.stock = bytes(OFFSET + 64)
        self.patched = self.stock[:OFFSET] + OURS + self.stock[OFFSET + len(OURS):]
        self.target = folder / "lib" / NAME
        self.backup = folder / "backup" / NAME
        self.target.parent.mkdir()
        self.target.write_bytes(self.stock)
        self.binary = _build(folder, {
            "C300X_DISPLAY_TOUCH_TARGET_DIR": str(self.target.parent),
            "C300X_DISPLAY_TOUCH_BACKUP_DIR": str(self.backup.parent),
            "C300X_DISPLAY_TOUCH_STOCK_SHA256": _sha(self.stock),
            "C300X_DISPLAY_TOUCH_PATCHED_SHA256": patched_sha256 or _sha(self.patched),
            "C300X_DISPLAY_TOUCH_STOCK_RANGE_SHA256": _sha(self.stock[OFFSET:OFFSET + 8]),
        })

    def run(self, action: str) -> dict:
        result = subprocess.run(
            [str(self.binary), action], capture_output=True, text=True,
            env={**os.environ, "C300X_DEVICE_PATCH_NO_REMOUNT": "1"},
        )
        return json.loads(result.stdout)


@pytest.fixture
def device(tmp_path: Path) -> _Device:
    return _Device(tmp_path)


def test_the_patch_is_applied_once_and_restored_from_the_stock_backup(device: _Device) -> None:
    assert device.run("status")["state"] == "stock"
    applied = device.run("apply")
    assert (applied["ok"], applied["state"], applied["changed"]) == (True, "patched", True)
    assert device.target.read_bytes() == device.patched
    assert device.backup.read_bytes() == device.stock
    assert not list(device.target.parent.glob("*.tmp"))
    # A second apply finds the patched file and writes nothing.
    stamp = device.target.stat().st_mtime_ns
    again = device.run("apply")
    assert (again["ok"], again["state"], again["changed"]) == (True, "patched", False)
    assert device.target.stat().st_mtime_ns == stamp
    restored = device.run("restore")
    assert (restored["ok"], restored["state"], restored["changed"]) == (True, "stock", True)
    assert device.target.read_bytes() == device.stock
    assert device.run("restore")["changed"] is False


def test_a_file_of_another_build_is_left_alone(device: _Device) -> None:
    other = device.stock[:10] + b"\x01" + device.stock[11:]
    device.target.write_bytes(other)
    result = device.run("apply")
    assert (result["ok"], result["state"], result["error"]) == (False, "unsupported", "unsupported_touch_target_hash")
    assert device.target.read_bytes() == other
    assert not device.backup.exists()
    # Nor does a restore replace a file this patch did not write.
    device.backup.parent.mkdir()
    device.backup.write_bytes(device.stock)
    assert device.run("restore")["changed"] is False
    assert device.target.read_bytes() == other


def test_only_a_stock_backup_is_restored_and_a_bad_one_is_replaced_on_apply(device: _Device) -> None:
    device.backup.parent.mkdir()
    device.backup.write_bytes(b"truncated")
    assert device.run("apply")["state"] == "patched"
    assert device.backup.read_bytes() == device.stock
    device.backup.write_bytes(device.patched)
    refused = device.run("restore")
    assert (refused["ok"], refused["error"]) == (False, "touch_backup_invalid")
    assert device.target.read_bytes() == device.patched


def test_a_missing_library_is_no_error_for_the_display_patch(device: _Device) -> None:
    device.target.unlink()
    assert device.run("status")["state"] == "missing"
    assert device.run("apply")["ok"] is False
    assert device.run("restore") == {
        "ok": True, "state": "missing", "patched": False, "backup_present": False, "changed": False,
        "root_writable": False, "error": "",
    }


def test_the_source_holds_only_our_bytes_and_hashes() -> None:
    source = (NATIVE / "src/display_touch.c").read_text(encoding="utf-8")
    # The two instructions "return 16" are the only bytes in the source.
    assert len(re.findall(r"\b0x[0-9a-f]{2}\b", source)) == len(OURS)
    assert "{0x10,0x00,0xa0,0xe3,0x1e,0xff,0x2f,0xe1}" in source
    assert f"0x{OFFSET:x}, 8," in source
    assert STOCK_SHA256 in source and PATCHED_SHA256 in source
    assert _sha(OURS) in source
    assert NAME not in source


def test_the_real_library_becomes_the_pinned_patched_file(tmp_path: Path) -> None:
    rootfs = os.environ.get("C300X_QT4_ROOTFS")
    if not rootfs or not (Path(rootfs) / "usr/lib" / NAME).is_file():
        pytest.skip("firmware root file system not available")
    target = tmp_path / "lib" / NAME
    target.parent.mkdir()
    shutil.copyfile(Path(rootfs) / "usr/lib" / NAME, target)
    binary = _build(tmp_path, {
        "C300X_DISPLAY_TOUCH_TARGET_DIR": str(target.parent),
        "C300X_DISPLAY_TOUCH_BACKUP_DIR": str(tmp_path / "backup"),
    })
    env = {**os.environ, "C300X_DEVICE_PATCH_NO_REMOUNT": "1"}
    assert _sha(target.read_bytes()) == STOCK_SHA256
    result = json.loads(subprocess.run([str(binary), "apply"], capture_output=True, text=True, env=env).stdout)
    assert (result["ok"], result["state"]) == (True, "patched")
    assert _sha(target.read_bytes()) == PATCHED_SHA256
    assert _sha((tmp_path / "backup" / NAME).read_bytes()) == STOCK_SHA256
    json.loads(subprocess.run([str(binary), "restore"], capture_output=True, text=True, env=env).stdout)
    assert _sha(target.read_bytes()) == STOCK_SHA256


def _fake_agent(
    tmp_path: Path, changed: bool, ok: bool = True, restore_reply: str | None = None
) -> tuple[Path, Path]:
    log = tmp_path / "agent-calls.log"
    agent = tmp_path / "fake-agent"
    reply = json.dumps({"ok": ok, "changed": changed}, separators=(",", ":"))
    restore = reply if restore_reply is None else restore_reply
    agent.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {log}\n"
        f"if [ \"$2\" = restore ]; then printf '%s\\n' '{restore}'; else printf '%s\\n' '{reply}'; fi\n"
    )
    agent.chmod(0o755)
    return agent, log


def _gui(tmp_path: Path) -> Path:
    from tests import test_qml_patch_script as qml

    gui_dir = tmp_path / "gui"
    gui_dir.mkdir(parents=True)
    qml._write_original_gui(gui_dir)
    return gui_dir


def _script(tmp_path: Path, gui_dir: Path, action: str, agent: Path, **env: str) -> subprocess.CompletedProcess[str]:
    from tests import test_qml_patch_script as qml

    return qml._run_qml_patch_raw(
        tmp_path, gui_dir, tmp_path / "backup", action, env_overrides={"C300X_QML_AGENT_BIN": str(agent), **env}
    )


def _calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


NO_DISPLAY = {
    "C300X_QML_RELOAD_GUI": "1",
    "C300X_QML_GUI_RELOAD_DELAY_SECONDS": "0",
    "C300X_QML_GUI_WRAPPER": "/nonexistent/wrapper",
}


@pytest.mark.parametrize(
    ("action", "expected"),
    [("apply", "apply"), ("restore", "restore"), ("restore-all", "restore"), ("status", None), ("core-apply", None)],
)
def test_the_display_patch_applies_and_restores_the_threshold_with_it(
    tmp_path: Path, action: str, expected: str | None
) -> None:
    agent, log = _fake_agent(tmp_path, changed=True)
    result = _script(tmp_path, _gui(tmp_path), action, agent)
    assert json.loads(result.stdout)["ok"] is True
    # A display that starts keeps the changed library: no restore follows.
    assert _calls(log) == ([f"--display-touch {expected}"] if expected else [])


def test_a_display_that_does_not_start_gets_the_stock_library_back(tmp_path: Path) -> None:
    gui_dir = _gui(tmp_path)
    agent, log = _fake_agent(tmp_path, changed=False)
    _script(tmp_path, gui_dir, "apply", agent)
    log.unlink()
    agent, log = _fake_agent(tmp_path, changed=True)
    # The display files are in place already, so only the library changes; the
    # restart finds no display process and no wrapper to start one.
    result = _script(tmp_path, gui_dir, "apply", agent, **NO_DISPLAY)
    assert json.loads(result.stdout)["state"] == "reload_failed"
    assert _calls(log) == ["--display-touch apply", "--display-touch restore"]


def test_the_library_is_left_alone_when_the_display_files_fail(tmp_path: Path) -> None:
    gui_dir = _gui(tmp_path)
    agent, log = _fake_agent(tmp_path, changed=True)
    # The new display files do not start: they are rolled back, and the
    # library is not changed on top of a failed patch.
    result = _script(tmp_path, gui_dir, "apply", agent, **NO_DISPLAY)
    assert json.loads(result.stdout)["state"] == "reload_failed"
    assert _calls(log) == []
    # Nor when the display files cannot be built at all.
    original = gui_dir / "MainApp.original"
    (gui_dir / "MainApp.qml").rename(original)
    (gui_dir / "MainApp.qml").symlink_to(original)
    result = _script(tmp_path, gui_dir, "apply", agent)
    assert result.returncode != 0
    assert _calls(log) == []


def test_a_failed_library_restore_fails_the_display_restore(tmp_path: Path) -> None:
    agent, _log = _fake_agent(tmp_path, changed=False, ok=False)
    status = json.loads(_script(tmp_path, _gui(tmp_path), "restore", agent).stdout)
    assert (status["ok"], status["error"]) == (False, "display_library_restore_failed")
    # An agent that dies without an answer has not restored anything either.
    silent, _log = _fake_agent(tmp_path, changed=False, restore_reply="")
    status = json.loads(_script(tmp_path, _gui(tmp_path / "third"), "restore", silent).stdout)
    assert status["ok"] is False
    # An apply on a library of another build is no failure of the Display patch.
    assert json.loads(_script(tmp_path, _gui(tmp_path / "second"), "apply", agent).stdout)["ok"] is True


def _fake_device(tmp_path: Path, maps: str, mounts: str) -> dict[str, str]:
    """A running display (pid 4242) and a mount table, with logged commands."""

    tools = tmp_path / "tools"
    tools.mkdir()
    log = tmp_path / "tool-calls.log"
    for name, body in {
        "pidof": "echo 4242",
        "killall": f"echo killall $* >> {log}",
        "mount": f"echo mount $* >> {log}",
    }.items():
        (tools / name).write_text(f"#!/bin/sh\n{body}\n")
        (tools / name).chmod(0o755)
    proc = tmp_path / "proc"
    (proc / "4242").mkdir(parents=True)
    (proc / "4242/maps").write_text(maps)
    (proc / "mounts").write_text(mounts)
    return {
        "PATH": f"{tools}:{os.environ['PATH']}",
        "C300X_QML_PROC_DIR": str(proc),
        "C300X_QML_RELOAD_GUI": "1",
        "C300X_QML_GUI_RELOAD_DELAY_SECONDS": "0",
        "C300X_QML_NO_REMOUNT": "0",
    }


def test_a_run_that_was_cut_off_is_completed_by_the_next_one(tmp_path: Path) -> None:
    gui_dir = _gui(tmp_path)
    agent, _log = _fake_agent(tmp_path, changed=False)
    _script(tmp_path, gui_dir, "apply", agent)
    # The library was replaced, then the job was killed: the display still
    # runs the old file and the root file system is still writable.
    env = _fake_device(
        tmp_path,
        "76a00000-77200000 r-xp 00000000 b3:06 1234 /usr/lib/libQtGuiE.so.4.8.7 (deleted)\n",
        "/dev/mmcblk2p6 / ext4 rw,relatime,data=journal 0 0\n",
    )
    status = json.loads(_script(tmp_path, gui_dir, "apply", agent, **env).stdout)
    assert status["ok"] is True
    calls = (tmp_path / "tool-calls.log").read_text().splitlines()
    # The start script is stopped with the display program: one restart.
    assert calls == ["killall BtClass_qws", "killall BtClass", "mount -o remount,ro /"]


def test_a_display_on_the_current_library_is_not_restarted(tmp_path: Path) -> None:
    gui_dir = _gui(tmp_path)
    agent, _log = _fake_agent(tmp_path, changed=False)
    _script(tmp_path, gui_dir, "apply", agent)
    env = _fake_device(
        tmp_path,
        "76a00000-77200000 r-xp 00000000 b3:06 1234 /usr/lib/libQtGuiE.so.4.8.7\n",
        "/dev/mmcblk2p6 / ext4 ro,relatime,data=journal 0 0\n",
    )
    assert json.loads(_script(tmp_path, gui_dir, "apply", agent, **env).stdout)["ok"] is True
    assert not (tmp_path / "tool-calls.log").exists()


def test_a_root_that_cannot_go_read_only_yet_still_reports_the_change(device: _Device) -> None:
    # The running display keeps the replaced file open until it is restarted.
    result = subprocess.run(
        [str(device.binary), "apply"], capture_output=True, text=True,
        env={**os.environ, "C300X_DEVICE_PATCH_NO_REMOUNT": "ro_busy"},
    )
    applied = json.loads(result.stdout)
    assert (applied["ok"], applied["changed"], applied["root_writable"]) == (True, True, True)
    assert device.target.read_bytes() == device.patched


def test_a_restore_that_cannot_write_keeps_the_patched_library(device: _Device) -> None:
    device.run("apply")
    # No room for the temporary file: the patched library stays in place.
    (device.target.parent / (NAME + ".tmp")).mkdir()
    failed = device.run("restore")
    assert (failed["ok"], failed["changed"], failed["error"]) == (False, False, "touch_restore_failed")
    assert device.target.read_bytes() == device.patched


def test_a_rollback_is_only_reported_when_the_stock_library_is_back(tmp_path: Path) -> None:
    # The display dies with the changed library and starts again afterwards.
    tools = tmp_path / "tools"
    tools.mkdir()
    state = tmp_path / "display-up"
    (tools / "pidof").write_text(f"#!/bin/sh\n[ -e {state} ] && echo 4242\n[ -e {state} ]\n")
    (tools / "killall").write_text("#!/bin/sh\nexit 0\n")
    wrapper = tmp_path / "wrapper"
    wrapper.write_text(f"#!/bin/sh\n[ -e {tmp_path}/restored ] && touch {state}\nexit 0\n")
    for tool in (tools / "pidof", tools / "killall"):
        tool.chmod(0o755)
    env = {
        "PATH": f"{tools}:{os.environ['PATH']}",
        "C300X_QML_RELOAD_GUI": "1",
        "C300X_QML_GUI_RELOAD_DELAY_SECONDS": "0.2",
        "C300X_QML_GUI_WRAPPER": str(wrapper),
    }
    gui_dir = _gui(tmp_path)
    quiet, _log = _fake_agent(tmp_path, changed=False)
    _script(tmp_path, gui_dir, "apply", quiet)

    def run(restore_ok: bool) -> dict:
        (tmp_path / "restored").unlink(missing_ok=True)
        state.unlink(missing_ok=True)
        reply = json.dumps({"ok": restore_ok, "changed": restore_ok}, separators=(",", ":"))
        agent = tmp_path / "fake-agent"
        agent.write_text(
            "#!/bin/sh\n"
            f"if [ \"$2\" = restore ]; then touch {tmp_path}/restored; printf '%s\\n' '{reply}'; "
            "else printf '%s\\n' '{\"ok\":true,\"changed\":true}'; fi\n"
        )
        agent.chmod(0o755)
        return json.loads(_script(tmp_path, gui_dir, "apply", agent, **env).stdout)

    rolled_back = run(restore_ok=True)
    assert (rolled_back["ok"], rolled_back["display_library"]) == (True, "rolled_back")
    failed = run(restore_ok=False)
    assert (failed["ok"], failed["error"]) == (False, "display_library_restore_failed")


def test_a_cut_off_write_leaves_no_temporary_file_behind(device: _Device) -> None:
    stale = device.target.parent / (NAME + ".tmp")
    stale.write_bytes(b"half a library")
    device.run("restore")
    assert not stale.exists()
    assert device.target.read_bytes() == device.stock


def test_the_removal_restores_the_library_before_anything_it_cannot_undo() -> None:
    # A failed restore keeps the agent, its start and the backup of the library.
    script = (NATIVE / "scripts/remove_agent.sh").read_text(encoding="utf-8")
    tail = script.split("\nstart_ssh\n", maxsplit=1)[1]
    assert tail.index("if ! stop_agent; then") < tail.index("\nrestore_qml\n")
    assert tail.index("restore_qml") < tail.index("restore_display_library") < tail.index("restore_media_patches")
    assert tail.index("restore_media_patches") < tail.index("remove_startup") < tail.index('rm -rf "$AGENT_DIR"')


def test_a_written_copy_is_checked_before_it_replaces_the_library(tmp_path: Path) -> None:
    # The copy does not have the expected hash: it must never become the library.
    device = _Device(tmp_path, patched_sha256="0" * 64)
    failed = device.run("apply")
    assert (failed["ok"], failed["changed"], failed["error"]) == (False, False, "touch_ranges_mismatch")
    assert device.target.read_bytes() == device.stock
    assert not list(device.target.parent.glob("*.tmp"))


def test_a_root_left_writable_is_reported_beside_the_library_state(tmp_path: Path) -> None:
    gui_dir = _gui(tmp_path)
    agent, _log = _fake_agent(tmp_path, changed=False)
    _script(tmp_path, gui_dir, "apply", agent)
    env = _fake_device(
        tmp_path,
        "76a00000-77200000 r-xp 00000000 b3:06 1234 /usr/lib/libQtGuiE.so.4.8.7\n",
        "/dev/mmcblk2p6 / ext4 rw,relatime,data=journal 0 0\n",
    )
    (tmp_path / "tools/mount").write_text("#!/bin/sh\nexit 1\n")
    (tmp_path / "tools/sleep").write_text("#!/bin/sh\nexit 0\n")
    (tmp_path / "tools/sleep").chmod(0o755)
    status = json.loads(_script(tmp_path, gui_dir, "apply", agent, **env).stdout)
    assert (status["ok"], status["root_writable"]) == (True, True)
