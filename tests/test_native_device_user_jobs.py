"""Device-user script latency must not stall API/UI service or weaken auth."""

import time
from pathlib import Path

import pytest
from test_native_agent_maintenance_jobs import GUI, QML, response, wait_until
from test_native_agent_maintenance_jobs import binary as binary
from test_native_agent_maintenance_jobs import lab as lab
from test_native_agent_maintenance_jobs import (
    maintenance_options as maintenance_options,
)

from native_agent.test.smoke import TOKEN, api_get

USER = "/api/v1/device-user"
ENSURE = "/api/v1/maintenance/device-user/actions/ensure-homeassistant"
RESTORE = "/api/v1/maintenance/device-user/actions/restore-homeassistant-setup"


def test_slow_status_preserves_service_single_writer_and_auth(lab):
    lab.script('while [ ! -e release ]; do sleep 0.02; done\n'
               'printf \'{"media_user_label_state":"patched","media_user_label_patched":true}\'\n')
    pending = lab.request(USER)
    lab.started()
    started = time.monotonic()
    for _ in range(5):
        assert api_get(lab.port, "/api/v1/health")["ok"]
        api_get(lab.ui_port, "/ui/events/status", authorized=False)
    assert time.monotonic() - started < 1
    for path, payload in ((USER, None), (QML, None), (GUI, {"confirm": "reload_gui"}),
                          (ENSURE, {"confirm": "ensure_homeassistant_user"}),
                          (RESTORE, {"confirm": "restore_ha_user_setup"})):
        assert response(lab.request(path, payload), 409)["error"] == "maintenance_busy"
    assert response(lab.request(USER, headers={}), 401)["error"] == "unauthorized"
    assert response(lab.request(ENSURE, {}, headers={"Authorization": "Bearer " + TOKEN}),
                    403)["error"] == "maintenance_unauthorized"
    lab.release()
    body = response(pending)
    assert body["media_user_label_available"] is True
    assert body["media_user_label_applied"] is True
    assert body["media_user_label_state"] == "patched"
    assert not {"from_aor", "to_aor", "device_domain", "digest"} & body.keys()


@pytest.mark.parametrize("script,available,state", [
    ("exit 1\n", False, "unknown"),
    ("printf invalid\n", False, "unknown"),
    ("printf '{}'\n", True, "unknown"),
    ('printf \'{"media_user_label_state":""}\'\n', True, "unknown"),
    ('printf \'{"media_user_label_state":"patched"}\'\n'
     "head -c 12000 /dev/zero | tr '\\000' ' '\n", True, "patched"),
])
def test_status_script_failure_and_legacy_truncation(lab, script, available, state):
    lab.script(script)
    body = response(lab.request(USER))
    assert body["media_user_label_available"] is available
    assert body["media_user_label_state"] == state
    assert api_get(lab.port, "/api/v1/health")["ok"]


def test_missing_status_script_and_unconfirmed_writes(lab):
    assert response(lab.request(USER))["media_user_label_available"] is False
    for path in (ENSURE, RESTORE):
        assert response(lab.request(path, {}), 400)["error"] == "maintenance_confirmation_required"
    assert not (lab.root / "started").exists()


def test_device_user_disconnect_retains_slot_and_releases_without_churn(lab):
    lab.script('while [ ! -e release ]; do sleep 0.02; done\nprintf "{}"\n')
    before = api_get(lab.port, "/api/v1/diagnostics")
    pending = lab.request(USER)
    lab.started()
    pending.close()
    for _ in range(10):
        assert api_get(lab.port, "/api/v1/health")["agent"] == "native-c"
    assert response(lab.request(USER), 409)["error"] == "maintenance_busy"
    lab.release()
    time.sleep(0.2)
    for _ in range(5):
        assert response(lab.request(USER))["media_user_label_available"]
    after = api_get(lab.port, "/api/v1/diagnostics")
    assert after["open_fd_count"] == before["open_fd_count"]
    assert after["agent_write_count"] == before["agent_write_count"]
    time.sleep(0.3)
    idle = api_get(lab.port, "/api/v1/diagnostics")
    assert idle["loop_iterations"] - after["loop_iterations"] <= 3


def test_status_deadline_with_closed_stdout_reaps_and_returns_legacy_status(lab):
    lab.script("exec 1>&-\nexec sleep 30\n")
    pending = lab.request(USER)
    lab.started()
    pid = int((lab.root / "started").read_text())
    assert api_get(lab.port, "/api/v1/health")["ok"]
    assert response(pending)["media_user_label_available"] is False
    wait_until(lambda: not Path(f"/proc/{pid}").exists())
    lab.script('printf "{}"\n')
    assert response(lab.request(USER))["media_user_label_available"]


def test_shutdown_cancels_device_user_script(lab):
    lab.script("exec sleep 30\n")
    lab.request(USER)
    lab.started()
    pid = int((lab.root / "started").read_text())
    lab.process.terminate()
    assert lab.process.wait(timeout=2) == 0

    def exited():
        try:
            return Path(f"/proc/{pid}/stat").read_text().split()[2] == "Z"
        except (FileNotFoundError, ProcessLookupError):
            return True

    wait_until(exited)


def test_shutdown_cancels_script_process_group(lab):
    lab.script('sleep 30 &\nprintf "%s" "$!" > descendant\nwait\n')
    lab.request(USER)
    lab.started()
    wait_until(lambda: (lab.root / "descendant").exists())
    descendant = int((lab.root / "descendant").read_text())
    lab.process.terminate()
    assert lab.process.wait(timeout=2) == 0

    def exited():
        try:
            return Path(f"/proc/{descendant}/stat").read_text().split()[2] == "Z"
        except (FileNotFoundError, ProcessLookupError):
            return True

    wait_until(exited)
