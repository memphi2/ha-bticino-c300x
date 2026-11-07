"""Verify native authorization over loopback, including persisted config."""

import pytest
import test_native_display_roundtrip as native_lab

auth_config = native_lab.auth_config
lab = native_lab.lab
native_binary = native_lab.native_binary
request = native_lab.request

AUTH = "/api/v1/maintenance/auth"
STATUS = "/api/v1/maintenance/update/status"
HEADER = "X-Bticino-C300X-Maintenance-Token"


@pytest.mark.parametrize("auth_config", [
    {"maintenance": {"enabled": False}},
    {"maintenance": {"enabled": False, "adminToken": "existing-admin"}},
    {"maintenance": {"enabled": True, "adminToken": "existing-admin"}},
], indirect=True)
def test_api_token_cannot_change_security_config(lab):
    before = lab.config_path.read_bytes()
    assert request(lab.api, AUTH)[0] == 200
    for headers in ({}, {HEADER: "wrong-admin"}):
        status, _ = request(lab.api, AUTH, {
            "maintenanceEnabled": True, "maintenanceToken": "chosen-admin",
            "noAuth": True, "maintenanceNoAuthAllowed": True,
        }, headers=headers)
        assert status == 403
        assert lab.config_path.read_bytes() == before
        assert request(lab.api, STATUS, headers={HEADER: "chosen-admin"})[0] == 403


@pytest.mark.parametrize("auth_config", [
    {"maintenance": {"enabled": enabled, "adminToken": "existing-admin"}}
    for enabled in (False, True)
], indirect=True)
def test_admin_can_enable_maintenance_and_rotate_credentials(lab):
    assert request(lab.api, AUTH, {
        "maintenanceEnabled": True, "maintenanceToken": "new-admin",
    }, headers={HEADER: "existing-admin"})[0] == 200
    assert request(lab.api, STATUS, headers={HEADER: "existing-admin"})[0] == 403
    assert request(lab.api, STATUS, headers={HEADER: "new-admin"})[0] == 200
    assert request(lab.api, AUTH, {"maintenanceEnabled": False},
                   headers={HEADER: "new-admin"})[0] == 200
    assert request(lab.api, STATUS, headers={HEADER: "new-admin"})[0] == 403
    assert request(lab.api, AUTH, {"maintenanceEnabled": True},
                   headers={HEADER: "new-admin"})[0] == 200


@pytest.mark.parametrize("auth_config,expected", [
    ({"api": {"noAuth": True}, "maintenance": {
        "enabled": enabled, "allowNoAuth": allowed,
    }}, 200 if enabled and allowed else 403)
    for enabled in (False, True) for allowed in (False, True)
], indirect=["auth_config"])
def test_only_explicit_bootstrap_can_install_credentials(lab, expected):
    status, _ = request(lab.api, AUTH, {
        "apiToken": "new-api", "maintenanceToken": "new-admin",
        "maintenanceEnabled": True, "setupComplete": True,
    }, headers={"Authorization": ""})
    assert status == expected
    if status == 200:
        assert request(lab.api, AUTH, {"noAuth": True})[0] == 403
        headers = {"Authorization": "Bearer new-api", HEADER: "new-admin"}
        status, body = request(lab.api, AUTH, headers=headers)
        assert status == 200
        assert body["noAuth"] is False
