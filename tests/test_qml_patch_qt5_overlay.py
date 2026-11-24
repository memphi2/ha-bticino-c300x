"""The Display patch on firmware 3.0.x: from the files inside BtClass to the preloaded resource file."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

from tests.test_display_qt5 import (
    FLAGS,
    NATIVE,
    SOURCES,
    _program,
    _qt_find,
    overlay_blob,
)
from tests.test_qml_patch_qt5 import VENDOR_FILES, _qt5_form
from tests.test_qml_patch_script import SCRIPT, SOURCE_DIR, _write_original_gui

WRAPPER = (
    "#!/bin/sh\n"
    'trap "killall BtClass; exit 0" SIGTERM\n'
    "export QT_QPA_PLATFORM=eglfs\n"
    "\n"
    "./bin/gui/BtClass &\n"
    "wait\n"
)


def _vendor_files(tmp_path: Path, *, main_app_extra: str = "") -> dict[str, bytes]:
    plain = tmp_path / "plain-vendor"
    plain.mkdir(parents=True, exist_ok=True)
    _write_original_gui(plain)
    files = {rel: _qt5_form((plain / rel).read_text()).encode() for rel in VENDOR_FILES}
    # After the import line: a stock file still ends with its closing brace.
    head, rest = files["MainApp.qml"].split(b"\n", 1)
    files["MainApp.qml"] = head + b"\n" + main_app_extra.encode() + rest
    return files


@pytest.fixture(scope="module")
def programs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Two known BtClass programs (two firmware builds) and the agent that reads them."""

    out = tmp_path_factory.mktemp("qt5-programs")
    layouts = []
    paths = {}
    for name, extra in (("first", ""), ("second", "// another build\n")):
        body, (tree, names, data) = _program(_vendor_files(out / name, main_app_extra=extra))
        paths[name] = out / name / "BtClass"
        paths[name].write_bytes(body)
        layouts.append(f'{{"{hashlib.sha256(body).hexdigest()}", {tree}u, {names}u, {data}u}}')
    cli = out / "display-qt5"
    subprocess.run(
        ["gcc", *FLAGS, f"-DC300X_DISPLAY_QT5_TEST_LAYOUT={','.join(layouts)}",
         f'-DC300X_DISPLAY_QT5_TEST_WRAPPER={{"{hashlib.sha256(WRAPPER.encode()).hexdigest()}", {len(WRAPPER.encode())}}}',
         *(str(NATIVE / s) for s in SOURCES), str(overlay_blob(out)), "-o", str(cli), "-ldl"],
        check=True, capture_output=True, text=True,
    )
    agent = out / "c300x-agent-native"
    agent.write_text(
        "#!/bin/sh\n"
        '[ "$1" = --display-qt5 ] || exit 2\n'
        "shift\n"
        'if [ "$1" = pack ] && [ -n "${QT5_TEST_PACK_FAILS:-}" ]; then echo \'{"ok":false}\'; exit 1; fi\n'
        f'exec "{cli}" "$@"\n'
    )
    agent.chmod(0o755)
    paths["agent"] = agent
    return paths


class Device:
    def __init__(self, tmp_path: Path, programs: dict[str, Path]) -> None:
        self.root = tmp_path
        self.programs = programs
        self.program = programs["first"]
        (tmp_path / "libQt5Core.so.5").write_text("")
        self.qt5_root = tmp_path / "agent/display-qt5"
        self.gui = self.qt5_root / "skins/default"
        self.backup = tmp_path / "backups/qt5/skins/default"
        self.rcc = tmp_path / "agent/display-qt5.rcc"
        self.lib = tmp_path / "agent/c300x-qrc-overlay.so"
        self.wrapper = tmp_path / "bin/BtClass_qws"
        self.wrapper_backup = tmp_path / "backups/bin/BtClass_qws"
        self.wrapper.parent.mkdir(parents=True)
        self.wrapper.write_text(WRAPPER)
        self.wrapper.chmod(0o755)
        self.rcc.parent.mkdir(parents=True)
        self.boot_id = tmp_path / "boot_id"
        self.boot_id.write_text("boot-1\n")

    def run(self, action: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([str(SCRIPT), action], capture_output=True, text=True,
                              env=self.environment(**env), check=False)

    def environment(self, **env: str) -> dict[str, str]:
        return {
            **os.environ,
            "C300X_QML_QT5_MARKER": str(self.root / "libQt5Core.so.5"),
            "C300X_QML_QT5_ROOT": str(self.qt5_root),
            "C300X_QML_GUI_DIR": str(self.gui),
            "C300X_QML_BACKUP_DIR": str(self.backup),
            "C300X_QML_SOURCE_DIR": str(SOURCE_DIR),
            "C300X_QML_QT5_RCC": str(self.rcc),
            "C300X_QML_QT5_OVERLAY_LIB": str(self.lib),
            "C300X_QML_QT5_WRAPPER_BACKUP": str(self.wrapper_backup),
            "C300X_QML_QT5_LOG": str(self.root / "display-qt5.log"),
            "C300X_QML_GUI_WRAPPER": str(self.wrapper),
            "C300X_QML_GUI_ROOT": str(self.root),
            "C300X_QML_AGENT_BIN": str(self.programs["agent"]),
            "C300X_QT5_GUI_BINARY": str(self.program),
            "C300X_QML_NO_REMOUNT": "1",
            "C300X_QML_RELOAD_GUI": "0",
            "C300X_QML_BOOT_ID": str(self.boot_id),
            # The restart run directory of this test, never the host's /tmp one.
            "C300X_QML_GUI_RUN_DIR": str(self.root / "gui-restart"),
            **env,
        }

    def ok(self, action: str, **env: str) -> dict[str, object]:
        result = self.run(action, **env)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout.strip().splitlines()[-1])

    def packed(self, rel: str) -> bytes | None:
        return _qt_find(self.rcc.read_bytes(), f"skins/default/{rel}")


@pytest.fixture
def device(tmp_path: Path, programs: dict[str, Path]) -> Device:
    return Device(tmp_path, programs)


def test_apply_packs_the_changed_files_in_qt5_form_and_preloads_them(device: Device) -> None:
    status = device.ok("apply")
    assert (status["state"], status["core_state"], status["qt5_overlay"]) == ("patched", "patched", "active")
    for rel in ("MainApp.qml", "HomePage.qml", "EventManager.qml", "Alarm.qml", "js/c300x_ha.js",
                "Settings.qml", "C300XSettings.qml", "js/c300x_maintenance.js"):
        expected = (device.gui / rel).read_text().replace("import QtQuick 1.1\n", "import QtQuick 2.7\n")
        assert device.packed(rel) == expected.encode(), rel
    assert b"import QtQuick 1.1" not in device.rcc.read_bytes()
    # Not changed by this action: the program's own files stay in use.
    assert device.packed("Components/Settings/CallBlockPopup.qml") is None
    assert device.packed("Components/Settings/GeneralsChoice.qml") is None
    assert device.lib.read_bytes() == (device.programs["agent"].parent / "c300x-qrc-overlay.so").read_bytes()
    wrapper = device.wrapper.read_text()
    assert f"LD_PRELOAD='{device.lib}' C300X_QRC_OVERLAY='{device.rcc}' QML_DISABLE_DISK_CACHE=1" in wrapper
    assert wrapper.endswith("fi\n./bin/gui/BtClass &\nwait\n")
    assert device.wrapper_backup.read_text() == WRAPPER
    assert os.access(device.wrapper, os.X_OK)


def test_both_home_page_layouts_are_packed_and_reported(device: Device) -> None:
    stock_count = b"+ (page.alarmButtonVisible ? 1 : 0) + (page.haButtonVisible ? 1 : 0) + 2"
    for request, layout, marker, absent in (
        ("0", "side_by_side", b"id: displayBridgeButtonRow", stock_count),
        ("1", "stock", stock_count, b"id: displayBridgeButtonRow"),
    ):
        status = device.ok("apply", C300X_QML_DYNAMIC_HOME_PAGE=request)
        assert (status["state"], status["home_buttons"], status["qt5_overlay"]) == ("patched", layout, "active")
        assert device.ok("status")["home_buttons"] == layout
        packed = device.packed("HomePage.qml") or b""
        assert marker in packed and absent not in packed
        assert packed.startswith(b"import QtQuick 2.7\n")
    assert device.ok("restore-all")["home_buttons"] is None


@pytest.mark.parametrize("state", ["failed", "incomplete"])
def test_the_home_page_layout_is_reported_only_while_the_overlay_is_active(device: Device, state: str) -> None:
    """The working copy keeps the page, but the display shows the vendor home page."""

    device.ok("apply", C300X_QML_DYNAMIC_HOME_PAGE="0")
    if state == "failed":
        Path(f"{device.rcc}.failed").write_text("boot-1\n")
    else:
        device.lib.unlink()
    status = device.ok("status")
    assert (status["qt5_overlay"], status["home_buttons"]) == (state, None)
    assert (device.gui / "HomePage.qml").exists()


def test_the_media_user_label_joins_the_packed_files(device: Device) -> None:
    device.ok("apply")
    device.ok("media-user-label-apply")
    assert b"Forward calls to Home Assistant" in (device.packed("Components/Settings/CallBlockPopup.qml") or b"")
    assert device.packed("MainApp.qml") is not None


def test_restore_all_gives_the_display_back_as_shipped(device: Device) -> None:
    device.ok("apply")
    device.ok("media-user-label-apply")
    status = device.ok("restore-all")
    assert (status["state"], status["core_state"], status["media_user_label_state"]) == ("original",) * 3
    assert status["qt5_overlay"] == "off"
    assert not device.rcc.exists()
    assert not device.lib.exists()
    assert device.wrapper.read_text() == WRAPPER


def test_a_partial_restore_keeps_the_rest_preloaded(device: Device) -> None:
    device.ok("apply")
    status = device.ok("restore")
    assert (status["state"], status["core_state"], status["qt5_overlay"]) == ("original", "patched", "active")
    assert device.packed("EventManager.qml") is not None
    assert device.packed("MainApp.qml") is None
    assert "c300x-qrc-overlay" in device.wrapper.read_text()


def test_a_left_over_overlay_reads_as_partial_and_restore_all_removes_it(device: Device) -> None:
    device.ok("apply")
    installed = device.wrapper.read_text()
    device.ok("restore-all")
    device.wrapper.write_text(installed)
    device.wrapper_backup.write_text(WRAPPER)
    status = device.ok("status")
    assert (status["state"], status["qt5_overlay"]) == ("partial", "incomplete")
    assert device.ok("restore-all")["qt5_overlay"] == "off"
    assert device.wrapper.read_text() == WRAPPER


def test_another_firmware_build_starts_from_its_own_files(device: Device) -> None:
    device.ok("apply")
    device.program = device.programs["second"]
    assert device.ok("apply")["state"] == "patched"
    assert "\n// another build\n" in (device.backup / "MainApp.qml").read_text()
    assert "\n// another build\n" in (device.qt5_root / "vendor/MainApp.qml").read_text()


@pytest.mark.parametrize("action", ["apply", "core-apply", "media-user-label-apply"])
def test_an_unknown_program_changes_nothing_and_is_reported(device: Device, tmp_path: Path, action: str) -> None:
    """The display pages stay off; the step answers instead of failing the install or update."""

    device.program = tmp_path / "BtClass-unknown"
    device.program.write_bytes(b"\x7fELF other")
    result = device.run(action)
    assert result.returncode == 0, result.stderr
    reply = json.loads(result.stdout)
    assert reply["ok"] is False and reply["error"] == "display_unsupported"
    assert reply["qt5_unsupported"] == "display_program_unknown"
    assert reply["qt5_overlay"] == "off" and reply["core_patched"] is False
    assert not device.rcc.exists()
    assert device.wrapper.read_text() == WRAPPER
    assert not device.gui.exists()
    assert device.ok("status")["qt5_unsupported"] == "display_program_unknown"
    device.program = device.programs["first"]
    assert device.ok(action)["qt5_overlay"] == "active"
    assert "qt5_unsupported" not in device.ok("status")


def test_a_transient_read_error_still_fails_the_step(device: Device, tmp_path: Path) -> None:
    device.program = tmp_path / "missing-BtClass"
    result = device.run("apply")
    assert result.returncode != 0
    assert "display_program_unreadable" in result.stderr
    assert "qt5_unsupported" not in device.ok("status")


def test_a_failed_pack_rolls_the_change_back(device: Device) -> None:
    device.ok("apply")
    device.ok("core-restore")
    before_rcc = device.rcc.read_bytes()
    before_event_manager = (device.gui / "EventManager.qml").read_text()
    result = device.run("core-apply", QT5_TEST_PACK_FAILS="1")
    assert result.returncode != 0
    assert "Cannot write the display resource file" in result.stderr
    assert device.rcc.read_bytes() == before_rcc
    assert (device.gui / "EventManager.qml").read_text() == before_event_manager
    assert not list(device.gui.glob(".c300x-qml-transaction.*"))


def test_an_unknown_start_script_is_left_alone(device: Device) -> None:
    other = WRAPPER.replace("./bin/gui/BtClass &", "exec ./bin/gui/BtClass")
    device.wrapper.write_text(other)
    result = device.run("apply")
    assert result.returncode == 0, result.stderr
    assert "Unsupported display start script" in result.stderr
    reply = json.loads(result.stdout)
    assert reply["error"] == "display_unsupported" and reply["qt5_unsupported"] == "display_wrapper_unknown"
    assert device.wrapper.read_text() == other
    assert not device.rcc.exists()
    assert not (device.gui / "Alarm.qml").exists()


def test_the_swipe_threshold_patch_is_not_run_on_qt5(device: Device, tmp_path: Path) -> None:
    calls = tmp_path / "calls"
    agent = tmp_path / "agent-logging"
    agent.write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\nexec "{device.programs["agent"]}" "$@"\n')
    agent.chmod(0o755)
    device.ok("apply", C300X_QML_AGENT_BIN=str(agent))
    device.ok("restore-all", C300X_QML_AGENT_BIN=str(agent))
    assert "--display-touch" not in calls.read_text()


def _start_display(device: Device, tmp_path: Path, exit_code: int, stderr: str = "") -> list[str]:
    """Run the start script with a display program that ends at once with exit_code."""

    log = tmp_path / "starts"
    program = tmp_path / "bin/gui/BtClass"
    program.parent.mkdir(parents=True, exist_ok=True)
    program.write_text(
        f'#!/bin/sh\necho "${{LD_PRELOAD:-plain}}" >> "{log}"\necho shown\n{stderr}\nexit {exit_code}\n'
    )
    program.chmod(0o755)
    result = subprocess.run(["sh", str(device.wrapper)], cwd=tmp_path, check=False, timeout=30,
                            capture_output=True, text=True)
    assert result.stdout.startswith("shown\n")
    return log.read_text().splitlines()


def test_a_display_that_fails_with_the_overlay_starts_as_shipped(device: Device, tmp_path: Path) -> None:
    device.ok("apply")
    assert _start_display(device, tmp_path, 139) == [str(device.lib), "plain"]
    assert device.ok("status")["qt5_overlay"] == "failed"
    assert _start_display(device, tmp_path, 0)[2:] == ["plain"]


def test_a_display_that_ends_normally_is_not_restarted(device: Device, tmp_path: Path) -> None:
    device.ok("apply")
    assert _start_display(device, tmp_path, 143) == [str(device.lib)]
    assert device.ok("status")["qt5_overlay"] == "active"


def test_a_quarantine_holds_for_the_boot_that_wrote_it(device: Device, tmp_path: Path) -> None:
    device.ok("apply")
    assert _start_display(device, tmp_path, 134) == [str(device.lib), "plain"]
    assert Path(f"{device.rcc}.failed").read_text() == "boot-1\n"
    assert device.ok("status")["qt5_overlay"] == "failed"
    assert device.ok("restore")["qt5_overlay"] == "failed"
    assert _start_display(device, tmp_path, 0)[2:] == ["plain"]
    device.boot_id.write_text("boot-2\n")
    assert device.ok("status")["qt5_overlay"] == "active"
    assert _start_display(device, tmp_path, 0)[3:] == [str(device.lib)]


@pytest.mark.parametrize("action", ["apply", "core-apply", "media-user-label-apply"])
def test_an_apply_retries_a_quarantined_overlay_once(device: Device, action: str) -> None:
    device.ok("apply")
    device.ok("media-user-label-apply")
    Path(f"{device.rcc}.failed").write_text("boot-1\n")
    assert device.ok("reload")["qt5_overlay"] == "failed"
    assert device.ok(action)["qt5_overlay"] == "active"
    assert not Path(f"{device.rcc}.failed").exists()


def test_full_removal_also_takes_away_a_mark_of_an_earlier_boot(device: Device) -> None:
    device.ok("apply")
    device.ok("restore-all")
    Path(f"{device.rcc}.failed").write_text("boot-0\n")
    assert device.ok("status")["qt5_overlay"] == "off"
    device.ok("restore-all")
    assert not Path(f"{device.rcc}.failed").exists()


def test_the_start_script_tries_the_overlay_once_per_start_without_a_pause(device: Device, tmp_path: Path) -> None:
    """The restart worker retries; the start script never sleeps, so its trap always runs at once."""

    device.ok("apply")
    assert "sleep" not in device.wrapper.read_text()
    attempts = tmp_path / "attempts"
    program = tmp_path / "bin/gui/BtClass"
    program.parent.mkdir(parents=True, exist_ok=True)
    program.write_text(f'#!/bin/sh\necho "${{LD_PRELOAD:-plain}}" >> "{attempts}"\n[ -n "${{LD_PRELOAD:-}}" ] && exit 134\nexit 0\n')
    program.chmod(0o755)
    environment = {**os.environ, "C300X_GUI_RELOAD": "1"}
    started = time.monotonic()
    subprocess.run(["sh", str(device.wrapper)], cwd=tmp_path, env=environment, check=False, timeout=30)
    assert time.monotonic() - started < 2
    assert attempts.read_text().splitlines() == [str(device.lib), "plain"]
    assert device.ok("status")["qt5_overlay"] == "failed"


def test_the_display_errors_are_kept_in_a_bounded_log(device: Device, tmp_path: Path) -> None:
    device.ok("apply")
    error = "qrc:/skins/default/MainApp.qml:12: ReferenceError: trsl is not defined"
    _start_display(device, tmp_path, 143, f'echo "{error}" >&2\nhead -c 200000 /dev/zero >&2')
    log = (tmp_path / "display-qt5.log").read_bytes()
    assert log.startswith(error.encode() + b"\n")
    assert len(log) == 65536


def test_the_daemons_signals_still_reach_the_display_started_with_the_overlay(device: Device, tmp_path: Path) -> None:
    device.ok("apply")
    starts = tmp_path / "starts"
    pid_file = tmp_path / "display.pid"
    program = tmp_path / "bin/gui/BtClass"
    program.parent.mkdir(parents=True, exist_ok=True)
    # Goes on under a name of its own (same PID): no host killall BtClass reaches it.
    program.write_text(
        '#!/bin/sh\n[ "${0##*/}" = BtClass ] && exec "${0%/*}/c300x-tdisp" "$@"\n'
        f'echo $$ > "{pid_file}"\necho "${{LD_PRELOAD:-plain}}" >> "{starts}"\n'
        f"trap 'echo usr1 >> \"{starts}\"; exit 0' USR1\n"
        "i=0\nwhile [ $i -lt 100 ]; do sleep 0.1; i=$((i + 1)); done\nexit 0\n"
    )
    program.chmod(0o755)
    shutil.copy(program, program.with_name("c300x-tdisp"))
    # The vendor's killall stand-in signals this test's display only.
    tools = tmp_path / "display-tools"
    tools.mkdir()
    (tools / "killall").write_text(
        f'#!/bin/sh\nsig=TERM\ncase "$1" in -*) sig="${{1#-}}" ;; esac\nkill -"$sig" "$(cat "{pid_file}")"\n'
    )
    (tools / "killall").chmod(0o755)
    text = device.wrapper.read_text()
    device.wrapper.write_text(text.replace(
        'trap "killall BtClass; exit 0" SIGTERM\n',
        'trap "killall BtClass; exit 0" SIGTERM\ntrap "killall -USR1 BtClass; wait" USR1\n', 1))
    wrapper = subprocess.Popen(["sh", str(device.wrapper)], cwd=tmp_path,
                               env={**os.environ, "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}"})
    deadline = time.monotonic() + 10
    while not starts.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    time.sleep(0.3)
    outside = tmp_path / "outside/BtClass"
    outside.parent.mkdir()
    outside.write_text("#!/bin/sh\nwhile :; do sleep 0.2; done\n")
    outside.chmod(0o755)
    other = subprocess.Popen([str(outside)], start_new_session=True)
    try:
        time.sleep(0.3)
        wrapper.send_signal(signal.SIGUSR1)
        assert wrapper.wait(timeout=10) == 0
        # A display program of another test or worktree is left alone.
        assert other.poll() is None
    finally:
        other.kill()
        other.wait()
    assert starts.read_text().splitlines() == [str(device.lib), "usr1"]
    assert device.ok("status")["qt5_overlay"] == "active"
