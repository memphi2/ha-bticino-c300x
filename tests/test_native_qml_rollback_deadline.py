"""The real QML rollback must survive the former ten-second job deadline."""

import shlex
import time

from test_native_agent_maintenance_jobs import GUI, QML, response, wait_until
from test_native_agent_maintenance_jobs import binary as binary
from test_native_agent_maintenance_jobs import lab as lab
from test_native_agent_maintenance_jobs import (
    maintenance_options as maintenance_options,
)
from test_qml_patch_script import SCRIPT, SOURCE_DIR, _write_original_gui
from test_qml_patch_startup_rollback import startup_env
from test_qml_patch_transactions import snapshot

from native_agent.test.smoke import api_get


def test_rollback_restart_survives_ten_seconds_and_keeps_single_writer(lab):
    gui, backup = lab.root / "gui", lab.root / "backup"
    gui.mkdir()
    _write_original_gui(gui)
    before = snapshot(gui)
    env, observations = startup_env(lab.root)
    pidof = lab.root / "startup-commands/pidof"
    probe = pidof.read_text().removeprefix("#!/bin/sh\n")
    pidof.write_text('#!/bin/sh\n'
                     'if [ "$(cat "$C300X_TEST_OBSERVATIONS/count")" = "2" ] && '
                     '[ ! -e "$C300X_TEST_OBSERVATIONS/probed" ]; then\n'
                     '  touch "$C300X_TEST_OBSERVATIONS/probed"\n'
                     '  while [ ! -e "$C300X_TEST_OBSERVATIONS/release-probe" ]; do sleep 0.02; done\n'
                     'fi\n' + probe)
    env.update({"C300X_QML_GUI_DIR": str(gui), "C300X_QML_BACKUP_DIR": str(backup),
                "C300X_QML_SOURCE_DIR": str(SOURCE_DIR), "C300X_QML_NO_REMOUNT": "1"})
    lab.script("\n".join(f"export {key}={shlex.quote(value)}" for key, value in env.items())
               + f"\nexec {shlex.quote(str(SCRIPT))} apply\n")
    pending = lab.request(QML + "/actions/apply", {"confirm": "apply_qml_patch"})
    pending.sock.settimeout(25)
    lab.started()
    wait_until(lambda: observations.joinpath("probed").exists())
    time.sleep(10.2)
    assert api_get(lab.port, "/api/v1/health")["ok"]
    assert snapshot(gui) == before
    assert response(lab.request(QML + "/actions/apply", {"confirm": "apply_qml_patch"}), 409)["error"] == "maintenance_busy"
    assert response(lab.request(GUI, {"confirm": "reload_gui"}), 409)["error"] == "maintenance_busy"
    observations.joinpath("release-probe").touch()
    result = response(pending)
    assert result["ok"] is False and result["state"] == "reload_failed"
    assert result["gui_running"] is True
    assert snapshot(gui) == snapshot(observations / "2") == before
    assert observations.joinpath("count").read_text() == "2"
