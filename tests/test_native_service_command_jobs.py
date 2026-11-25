"""SSH/reboot/remove scheduling with real jobs and only temporary fake programs."""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from http.client import RemoteDisconnected
from pathlib import Path

import pytest
from test_native_agent_maintenance_jobs import QML, ROOT, response, wait_until
from test_native_agent_maintenance_jobs import lab as lab

from native_agent.test.smoke import TOKEN, api_get

SSH = "/api/v1/maintenance/ssh"
REBOOT = "/api/v1/maintenance/reboot"
REMOVE = "/api/v1/maintenance/agent/actions/remove"


@pytest.fixture(scope="module", params=[False, True], ids=["host", "asan-ubsan"])
def binary(request, tmp_path_factory):
    build = tmp_path_factory.mktemp("service-command-build")
    (build / "bin/gui").mkdir(parents=True)
    for path in ("bin/bt_daemon", "bin/gui/BtClass"):
        (build / path).symlink_to(Path(sys.executable).resolve())
    # The station's /bin/sh is bash; its argv[0] stays the shell path, as there.
    shell = build / "sh"
    shell.symlink_to(Path(shutil.which("bash")).resolve())
    wrapper = build / "bin/BtClass_qws"
    wrapper.write_text(f'#!{shell}\n./bin/gui/BtClass -c "$GUI_CLIENT" &\nwait\n')
    wrapper.chmod(0o755)
    flags = ("-std=c11 -O2 -Wall -Wextra -Werror -pedantic "
             "-D_DEFAULT_SOURCE -D_POSIX_C_SOURCE=200809L "
             '-DC300X_NATIVE_AGENT_VERSION=\\\"test\\\" '
             '-DC300X_SSH_INIT_SCRIPT=\\\"./service-test.sh\\\" '
             '-DC300X_SSH_STATUS_COMMAND=\\\"./status-test.sh\\\" '
             '-DC300X_REBOOT_PROGRAM=\\\"./reboot-test.sh\\\" '
             '-DC300X_SSH_COMMAND_TIMEOUT_MS=2000 -DC300X_SSH_STATUS_TIMEOUT_MS=2000')
    # The lab is a Qt 4 station unless a test creates "qt5-mark" in its root.
    flags += ' -DC300X_QT5_DISPLAY_MARKER=\\"./qt5-mark\\"'
    flags += (f' -DC300X_GUI_HOME=\\"{build}\\" -DC300X_GUI_SHELL=\\"{shell}\\" -DC300X_GUI_INIT_PID={os.getpid()}'
              f' -DC300X_GUI_UID={os.getuid()} -DC300X_GUI_GID={os.getgid()}')
    if request.param:
        flags += " -fsanitize=address,undefined -fno-omit-frame-pointer"
    link = "-pthread -ldl " + str(ROOT / "native_agent/test/http_audio_codec_stub.c")
    link += " -Wl,--wrap=statvfs " + str(ROOT / "native_agent/test/gui_firmware_mount_stub.c")
    for function in ("apply", "restore", "read_status"):
        link += " -Wl,--wrap=c300x_audio_codec_" + function
    result = subprocess.run(
        ["make", "-C", str(ROOT / "native_agent"), f"BUILD_DIR={build}",
         f"CFLAGS={flags}", f"LDFLAGS={link}", "-j2", "all"], capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return build / "host/c300x-agent-native"


@pytest.fixture
def maintenance_options(request):
    return {"sshStart": {"enabled": True},
            "reboot": {"enabled": True, "delayMs": getattr(request, "param", 10)},
            "agentRemove": {"enabled": True, "script": "./remove-test.sh"}}


def script(lab, name, body):
    path = lab.root / (name + "-test.sh")
    path.write_text('#!/bin/sh\nprintf "%s" "$$" > ' + name + "-pid\n" + body)
    path.chmod(0o700)


def scripts(lab, service="exit 0\n", status="exit 0\n"):
    script(lab, "service", service)
    script(lab, "status", status)
    script(lab, "reboot", "touch reboot-done\n")
    script(lab, "remove", "touch remove-done\n")


SUPERVISOR = ["bin/bt_daemon", "-c", 'import subprocess; subprocess.run(["bin/BtClass_qws"], check=True)']
GUI_CLIENT = """
import json, os
from http.client import HTTPConnection
port, action, payload, headers = json.loads(os.environ["GUI_REQUEST"])
conn = HTTPConnection("127.0.0.1", port, timeout=5)
conn.request("GET" if payload is None else "POST", "/ui/maintenance" + action,
             body=None if payload is None else json.dumps(payload), headers=headers)
reply = conn.getresponse()
print(json.dumps([reply.status, json.loads(reply.read())]))
"""


def display(lab, action="", payload=None, *, status=200, launcher=SUPERVISOR, **headers):
    home = Path(lab.process.args[0]).parents[1]
    result = subprocess.run(launcher, cwd=home, check=True, timeout=8, capture_output=True,
                            env={**os.environ, "GUI_CLIENT": GUI_CLIENT, "GUI_REQUEST":
                                 json.dumps([lab.ui_port, action, payload, headers])})
    code, body = json.loads(result.stdout)
    assert code == status, body
    return body


def test_display_maintenance_offline(lab):
    scripts(lab)
    ui = {"X-C300X-UI": "settings-v1"}
    for headers in ({}, {**ui, "Origin": "http://localhost"}):
        assert display(lab, status=403, **headers)["ok"] is False
    assert display(lab, **ui) == {
        "ok": True, "ssh": True, "remove": True, "reboot": True,
    }
    for action in ("/remove", "/reboot"):
        display(lab, action, {}, status=400, **ui)
    assert not list(lab.root.glob("*-pid"))
    display(lab, "/reboot", {"confirm": "reboot"}, status=202, **ui)
    wait_until(lambda: (lab.root / "reboot-done").exists())
    assert not (lab.root / "service-pid").exists()
    assert display(lab, "/ssh", **ui)["running"]
    assert display(lab, "/ssh", {"enabled": True}, **ui)["running"]
    display(lab, "/remove", {"confirm": "remove_agent"}, status=202, **ui)
    wait_until(lambda: (lab.root / "remove-done").exists())


def test_same_gui_binary_requires_unique_station_launch(lab):
    ui = {"X-C300X-UI": "settings-v1"}
    # Same uid, gid, socket, executable and header, but no station launcher.
    for launcher in (["bin/gui/BtClass", "-c", GUI_CLIENT], ["bin/BtClass_qws"]):
        assert display(lab, "/reboot", {"confirm": "reboot"}, status=403,
                       launcher=launcher, **ui)["error"] == "display_maintenance_denied"
    home = Path(lab.process.args[0]).parents[1]
    ready, done = lab.root / "ready-gui", lab.root / "stop-gui"
    hold = ("import pathlib,time\n" + f"pathlib.Path({str(ready)!r}).touch()\n"
            + f"while not pathlib.Path({str(done)!r}).exists(): time.sleep(.02)")
    with subprocess.Popen(SUPERVISOR, cwd=home, env={**os.environ, "GUI_CLIENT": hold}):
        try:
            wait_until(ready.exists)
            assert display(lab, status=403, **ui)["error"] == "display_maintenance_denied"
        finally:
            done.touch()
    assert display(lab, **ui)["ok"]


def test_stock_gui_accepts_only_one_or_two_pinned_daemons(lab):
    ui = {"X-C300X-UI": "settings-v1"}
    lookalike = lab.root / "bt_daemon"
    shutil.copy2(Path(sys.executable).resolve(), lookalike)
    daemon = "bin/bt_daemon"
    for chain, expected in [
        ([daemon], 200), ([daemon, daemon], 200),
        ([str(lookalike), daemon], 403), ([daemon, str(lookalike)], 403),
        ([daemon, daemon, daemon], 403),
    ]:
        launcher = ["bin/BtClass_qws"]
        for executable in reversed(chain):
            launcher = [executable, "-c", f"import subprocess; subprocess.run({launcher!r}, check=True)"]
        result = display(lab, status=expected, launcher=launcher, **ui)
        assert result["ok"] is (expected == 200)


def test_reload_requires_exact_immutable_wrapper(lab):
    ui = {"X-C300X-UI": "settings-v1"}
    home = Path(lab.process.args[0]).parents[1]
    wrapper, shell = str(home / "bin/BtClass_qws"), str(home / "sh")
    # The fixture's init anchor is this test process. Direct child, no daemon.
    assert display(lab, launcher=[shell, wrapper], **ui)["ok"]
    for launcher in ([shell, wrapper, "extra"],
                     [shell, "-c", './bin/gui/BtClass -c "$GUI_CLIENT" & wait']):
        assert display(lab, launcher=launcher, status=403, **ui)["ok"] is False
    (lab.root / "firmware-writable").touch()
    assert display(lab, launcher=[shell, wrapper], status=403, **ui)["ok"] is False


def qt5_start_script(lab):
    """The Qt 5 start script exactly as qml_patch.sh generates it from a stock one."""
    home = Path(lab.process.args[0]).parents[1]
    source = (ROOT / "native_agent/scripts/qml_patch.sh").read_text()
    generator = re.search(r"^qt5_wrapper_text\(\) \{\n.*?^\}\n", source, re.S | re.M).group(0)
    stock = lab.root / "stock-wrapper"
    stock.write_text(f"#!{home / 'sh'}\n./bin/gui/BtClass &\nwait\n")
    for name in ("overlay.so", "overlay.rcc"):
        (lab.root / name).write_bytes(b"")
    env = {**os.environ, "QT5_OVERLAY_LIB": str(lab.root / "overlay.so"),
           "QT5_RCC": str(lab.root / "overlay.rcc"), "QT5_LOG": str(lab.root / "display-qt5.log"),
           "QT5_BOOT_ID": str(lab.root / "boot_id")}
    text = subprocess.run(["sh", "-c", generator + 'qt5_wrapper_text "$1"', "sh", str(stock)],
                          env=env, check=True, capture_output=True, text=True).stdout
    assert '    { LD_PRELOAD=' in text and '2> "$c300x_err"; echo $?' in text
    return text.replace("./bin/gui/BtClass", './bin/gui/BtClass -c "$GUI_CLIENT"')


@contextmanager
def start_script(lab, text):
    wrapper = Path(lab.process.args[0]).parents[1] / "bin/BtClass_qws"
    stock = wrapper.read_text()
    wrapper.write_text(text)
    try:
        yield
    finally:
        wrapper.write_text(stock)


def test_qt5_start_script_runs_the_display_in_a_station_launch(lab):
    ui = {"X-C300X-UI": "settings-v1"}
    home = Path(lab.process.args[0]).parents[1]
    rc = lab.root / "display-qt5.log.rc"
    (lab.root / "qt5-mark").touch()
    with start_script(lab, qt5_start_script(lab)):
        # At boot bt_daemon runs bin/BtClass_qws; reload_gui runs the absolute path under init.
        for launcher in (SUPERVISOR, [str(home / "sh"), str(home / "bin/BtClass_qws")]):
            rc.unlink(missing_ok=True)
            assert display(lab, launcher=launcher, **ui)["ok"]
            assert rc.read_text() == "0\n"


def test_qt5_start_script_with_more_forks_is_not_a_station_launch(lab):
    ui = {"X-C300X-UI": "settings-v1"}
    home = Path(lab.process.args[0]).parents[1]
    (lab.root / "qt5-mark").touch()
    # The display runs one fork below the start script; three are more than allowed.
    text = qt5_start_script(lab).replace("    { LD_PRELOAD=", "    { ( ( LD_PRELOAD=")
    text = text.replace('2> "$c300x_err"; echo $?', '2> "$c300x_err"; true; ); true; ); echo $?')
    with start_script(lab, text):
        for launcher in (SUPERVISOR, [str(home / "sh"), str(home / "bin/BtClass_qws")]):
            assert display(lab, launcher=launcher, status=403, **ui)["error"] == "display_maintenance_denied"
    assert (lab.root / "display-qt5.log.rc").read_text() == "0\n"


def test_a_forked_start_script_is_no_station_launch_on_qt4(lab):
    """1.7.x/2.0.2 as in 2.9.2: the wrapper itself must start the display."""
    ui = {"X-C300X-UI": "settings-v1"}
    home = Path(lab.process.args[0]).parents[1]
    assert not (lab.root / "qt5-mark").exists()
    for text in (qt5_start_script(lab),
                 f'#!{home / "sh"}\n( ./bin/gui/BtClass -c "$GUI_CLIENT"; true ) &\nwait\n'):
        with start_script(lab, text):
            for launcher in (SUPERVISOR, [str(home / "sh"), str(home / "bin/BtClass_qws")]):
                assert display(lab, launcher=launcher, status=403, **ui)["error"] == "display_maintenance_denied"
    # The stock start script still is one.
    assert display(lab, **ui)["ok"]


def test_gui_peer_checks_all_production_credential_fields(tmp_path):
    # Compile with production IDs (not the unprivileged integration fixture).
    probe = tmp_path / "credentials"
    subprocess.run(["cc", "-std=c11", "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
                    "-I", str(ROOT / "native_agent/src"), "-x", "c", "-", "-o", str(probe)],
                   input='#include "gui_peer.c"\nint c300x_device_display_is_qt5(void) { return 0; }\n'
                         'int main(void) { return trusted_parent(AT_FDCWD) != 42; }',
                   text=True, check=True)
    for changed in range(-1, 8):
        fields = [0] * 8
        if changed >= 0:
            fields[changed] = 1000
        uids, gids = (" ".join(map(str, ids)) for ids in (fields[:4], fields[4:]))
        (tmp_path / "status").write_text(f"PPid:\t42\nUid:\t{uids}\nGid:\t{gids}\n")
        assert subprocess.run([str(probe)], cwd=tmp_path).returncode == (changed >= 0)


def test_header_without_trusted_gui_process_is_not_enough(lab):
    result = subprocess.run([
        "curl", "--silent", "--show-error", "--max-time", "4", "--noproxy", "*",
        "-H", "X-C300X-UI: settings-v1",
        f"http://127.0.0.1:{lab.ui_port}/ui/maintenance",
    ], check=True, capture_output=True)
    assert json.loads(result.stdout)["error"] == "display_maintenance_denied"


def test_display_ssh_only_confirms_observed_state(lab):
    ui = {"X-C300X-UI": "settings-v1"}
    scripts(lab, status="exit 1\n")  # pidof: daemon absent.
    assert display(lab, "/ssh", {"enabled": False}, **ui)["running"] is False
    display(lab, "/ssh", {"enabled": True}, status=502, **ui)
    scripts(lab, status="exit 127\n")  # Broken probe: do not report SSH as off.
    display(lab, "/ssh", status=502, **ui)


@pytest.mark.parametrize("path,payload,expected", [
    (SSH, None, {"ok": True, "enabled": True, "running": True}),
    (SSH, {"enabled": True}, {"ok": True, "enabled": True, "running": True}),
    (SSH + "/actions/start", {"confirm": "start_ssh"},
     {"ok": True, "action": "ssh_start", "enabled": True, "running": True}),
    (SSH + "/actions/stop", {"confirm": "stop_ssh"},
     {"ok": True, "action": "ssh_stop", "enabled": False, "running": False}),
])
def test_slow_commands_leave_health_and_ui_responsive(lab, path, payload, expected):
    slow = "while [ ! -e release ]; do sleep 0.02; done\n"
    scripts(lab, service=slow, status=slow)
    pending = lab.request(path, payload)
    wait_until(lambda: (lab.root / ("status-pid" if payload is None else "service-pid")).exists())
    started = time.monotonic()
    for _ in range(5):
        assert api_get(lab.port, "/api/v1/health")["ok"]
        api_get(lab.ui_port, "/ui/events/status", authorized=False)
    assert time.monotonic() - started < 1
    assert response(lab.request(SSH, {"enabled": False}), 409)["error"] == "maintenance_busy"
    assert response(lab.request(SSH, headers={}), 401)["error"] == "unauthorized"
    assert response(lab.request(SSH, headers={"Authorization": "Bearer " + TOKEN}),
                    403)["error"] == "maintenance_unauthorized"
    lab.release()
    assert response(pending) == expected


@pytest.mark.parametrize("path,payload,expected", [
    (SSH, None, (200, {"ok": True, "enabled": False, "running": False})),
    (SSH + "/actions/start", {"confirm": "start_ssh"},
     (502, {"ok": False, "error": "maintenance_command_failed"})),
])
def test_a_hanging_ssh_command_ends_at_its_deadline_and_frees_maintenance(lab, path, payload, expected):
    hang = "while [ ! -e release ]; do sleep 0.02; done\n"
    scripts(lab, service=hang, status=hang)
    started = time.monotonic()
    assert response(lab.request(path, payload), expected[0]) == expected[1]
    assert 1.5 < time.monotonic() - started < 6
    # The slot is free again: the next request runs its own command.
    scripts(lab)
    assert response(lab.request(SSH))["running"] is True


def test_ssh_get_waits_in_input_pool_without_new_busy_status_or_deadline(lab):
    scripts(lab)
    lab.script('while [ ! -e release ]; do sleep 0.02; done\nprintf "{}"\n')
    pending = lab.request(QML)
    lab.started()
    waiting = [lab.request(SSH) for _ in range(3)]
    time.sleep(0.65)  # Complete requests must not inherit the 500ms input deadline.
    assert api_get(lab.port, "/api/v1/health")["ok"]
    assert not (lab.root / "status-pid").exists()
    lab.release()
    response(pending)
    for connection in waiting:
        assert response(connection) == {"ok": True, "enabled": True, "running": True}


def test_deferred_status_keeps_input_capacity_and_ui_reservation(lab):
    scripts(lab)
    lab.script('while [ ! -e release ]; do sleep 0.02; done\nprintf "{}"\n')
    pending = lab.request(QML)
    lab.started()
    waiting = [lab.request(SSH) for _ in range(6)]
    time.sleep(0.1)
    # The existing admission contract closes excess API connections, without
    # consuming the two slots reserved for loopback UI requests.
    with pytest.raises((RemoteDisconnected, ConnectionResetError, BrokenPipeError)):
        response(lab.request(SSH))
    api_get(lab.ui_port, "/ui/events/status", authorized=False)
    assert not (lab.root / "status-pid").exists()
    lab.release()
    response(pending)
    for connection in waiting:
        assert response(connection)["running"]
    assert api_get(lab.port, "/api/v1/health")["ok"]


@pytest.mark.parametrize("path,payload", [
    (SSH, {"enabled": False}), (SSH + "/actions/start", {"confirm": "start_ssh"}),
    (SSH + "/actions/stop", {"confirm": "stop_ssh"}),
])
def test_failed_service_keeps_502_and_does_not_probe(lab, path, payload):
    scripts(lab, service="exit 7\n")
    assert response(lab.request(path, payload), 502)["error"] == "maintenance_command_failed"
    assert not (lab.root / "status-pid").exists()


def test_missing_commands_and_failed_probe_keep_existing_statuses(lab):
    assert response(lab.request(SSH)) == {"ok": True, "enabled": False, "running": False}
    assert response(lab.request(SSH, {"enabled": True}), 502)["error"] == "maintenance_command_failed"
    scripts(lab, status="exit 1\n")
    assert response(lab.request(SSH, {"enabled": True}))["running"] is False
    assert response(lab.request(SSH + "/actions/start", {"confirm": "start_ssh"}))["running"] is True


@pytest.mark.parametrize("path,payload,status,error", [
    (SSH, {}, 400, "maintenance_ssh_enabled_required"),
    (SSH + "/actions/start", {}, 400, "maintenance_confirmation_required"),
    (SSH + "/actions/stop", {}, 400, "maintenance_confirmation_required"),
    (REBOOT, {}, 400, "maintenance_confirmation_required"),
    (REMOVE, {}, 400, "maintenance_confirmation_required"),
    (SSH + "/", None, 501, "not_implemented"),
])
def test_validation_starts_no_commands(lab, path, payload, status, error):
    scripts(lab)
    assert response(lab.request(path, payload), status)["error"] == error
    assert not list(lab.root.glob("*-pid"))


@pytest.mark.parametrize("path,confirm,name", [(REBOOT, "reboot", "reboot"), (REMOVE, "remove_agent", "remove")])
@pytest.mark.parametrize("ssh_exit", [0, 9])
def test_shutdown_actions_wait_for_ssh_but_ignore_its_failure(lab, path, confirm, name, ssh_exit):
    scripts(lab, service=f"while [ ! -e release ]; do sleep 0.02; done\nexit {ssh_exit}\n")
    pending = lab.request(path, {"confirm": confirm})
    wait_until(lambda: (lab.root / "service-pid").exists())
    assert not (lab.root / (name + "-done")).exists()
    assert api_get(lab.port, "/api/v1/health")["ok"]
    lab.release()
    result = response(pending, 202)
    assert result["action"] == confirm and result["scheduled"] is True
    wait_until(lambda: (lab.root / (name + "-done")).exists())


@pytest.mark.parametrize("path,confirm,name", [(REBOOT, "reboot", "reboot"), (REMOVE, "remove_agent", "remove")])
def test_shutdown_actions_go_ahead_when_the_ssh_start_hangs_past_its_deadline(lab, path, confirm, name):
    scripts(lab, service="while [ ! -e release ]; do sleep 0.02; done\n")
    started = time.monotonic()
    result = response(lab.request(path, {"confirm": confirm}), 202)
    assert 1.5 < time.monotonic() - started < 6
    assert result["action"] == confirm and result["scheduled"] is True
    wait_until(lambda: (lab.root / (name + "-done")).exists())


@pytest.mark.parametrize("delay", [0, -1])
def test_nonpositive_reboot_delay_remains_rejected(lab, binary, delay):
    config = json.loads((lab.root / "config.json").read_text())
    config["maintenance"]["reboot"]["delayMs"] = delay
    path = lab.root / "invalid-config.json"
    path.write_text(json.dumps(config))
    result = subprocess.run([str(binary), "--config", str(path), "--check-config"],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 2
    assert "maintenance.reboot.delayMs must be positive" in result.stderr


def test_no_output_limit_or_write_fd_timer_churn(lab):
    scripts(lab, service="head -c 100000 /dev/zero\n")
    before = api_get(lab.port, "/api/v1/diagnostics")
    for _ in range(6):
        assert response(lab.request(SSH, {"enabled": True}))["ok"]
    after = api_get(lab.port, "/api/v1/diagnostics")
    assert after["open_fd_count"] == before["open_fd_count"]
    assert after["agent_write_count"] == before["agent_write_count"]
    time.sleep(0.3)
    assert api_get(lab.port, "/api/v1/diagnostics")["loop_iterations"] - after["loop_iterations"] <= 3


def test_disconnect_and_shutdown_do_not_advance_pending_action(lab):
    scripts(lab, service="exec 1>&-\nexec sleep 30\n")
    pending = lab.request(REBOOT, {"confirm": "reboot"})
    wait_until(lambda: (lab.root / "service-pid").exists())
    pid = int((lab.root / "service-pid").read_text())
    pending.close()
    waiting = lab.request(SSH)
    assert api_get(lab.port, "/api/v1/health")["ok"]
    assert response(lab.request(SSH, {"enabled": True}), 409)["error"] == "maintenance_busy"
    lab.process.terminate()
    assert lab.process.wait(timeout=2) == 0
    waiting.close()
    assert not (lab.root / "reboot-done").exists()

    def exited():
        try:
            return Path(f"/proc/{pid}/stat").read_text().split()[2] == "Z"
        except (FileNotFoundError, ProcessLookupError):
            return True

    wait_until(exited)


CODEC = "/api/v1/maintenance/audio-codec"


def test_codec_reboot_tail_is_async_and_keeps_response_and_write_accounting(lab):
    scripts(lab, service="while [ ! -e release ]; do sleep 0.02; done\n")
    before = api_get(lab.port, "/api/v1/diagnostics")
    pending = lab.request(CODEC + "/actions/apply", {"confirm": "apply_audio_codec_patch"})
    wait_until(lambda: (lab.root / "service-pid").exists())
    assert api_get(lab.port, "/api/v1/health")["ok"]
    during = api_get(lab.port, "/api/v1/diagnostics")
    assert during["agent_write_count"] == before["agent_write_count"] + 1
    assert not (lab.root / "reboot-done").exists()
    lab.release()
    body = response(pending)
    assert body == {"ok": True, "supported": True, "state": "speex", "configured_state": "pcmu",
                    "running_state": "speex", "backup_present": True, "changed": True,
                    "reboot_required": True, "root_writable": False, "rebooting": True}
    wait_until(lambda: (lab.root / "reboot-done").exists())


@pytest.mark.parametrize("action", ["apply", "restore"])
def test_codec_failure_and_opt_out_start_no_service_jobs(lab, action):
    scripts(lab)
    path = CODEC + "/actions/" + action
    payload = {"confirm": action + "_audio_codec_patch", "reboot": False}
    assert response(lab.request(path, {}), 400)["error"] == "maintenance_confirmation_required"
    assert response(lab.request(path, payload, headers={"Authorization": "Bearer " + TOKEN}),
                    403)["error"] == "maintenance_unauthorized"
    (lab.root / "codec-fail").touch()
    assert response(lab.request(path, payload), 500) == {
        "ok": False, "error": f"audio_codec_{action}_failed", "detail": "simulated codec failure"}
    (lab.root / "codec-fail").unlink()
    assert response(lab.request(path, payload))["rebooting"] is False
    assert not (lab.root / "service-pid").exists()
    assert not (lab.root / "reboot-done").exists()


def test_codec_shutdown_frees_continuation_without_reboot(lab):
    scripts(lab, service="exec sleep 30\n")
    lab.request(CODEC + "/actions/apply", {"confirm": "apply_audio_codec_patch"})
    wait_until(lambda: (lab.root / "service-pid").exists())
    lab.process.terminate()
    assert lab.process.wait(timeout=2) == 0
    assert not (lab.root / "reboot-done").exists()
