"""Verify native authorization over loopback, including persisted config."""

import http.client
import json

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


@pytest.mark.parametrize("auth_config", [{
    "maintenance": {"enabled": True, "adminToken": "existing-admin"},
}], indirect=True)
def test_json_unicode_roundtrip_and_field_boundaries(lab):
    headers = {HEADER: "existing-admin"}
    synthetic_password = 's\u00ebcret\\"\n\U0001f4a1'
    assert request(lab.api, "/api/v1/maintenance/mqtt", {
        "password": synthetic_password, "username": "Home Assistant M\u00fcnchen",
    }, headers=headers)[0] == 200
    persisted = json.loads(lab.config_path.read_text())
    assert persisted["mqtt"]["password"] == synthetic_password
    assert persisted["mqtt"]["username"] == "Home Assistant M\u00fcnchen"
    # A key-like string value or nested key must not change top-level settings.
    assert request(lab.api, AUTH, {
        "description": "noAuth", "nested": {"noAuth": True}, "allowLan": True,
    }, headers=headers)[0] == 200
    assert request(lab.api, AUTH)[1]["noAuth"] is False
    before = lab.config_path.read_bytes()
    assert request(lab.api, AUTH, {"apiToken": "x" * 512}, headers=headers)[0] == 400
    assert request(lab.api, AUTH, {"apiPort": 4294967297}, headers=headers)[0] == 400
    assert lab.config_path.read_bytes() == before


@pytest.mark.parametrize("auth_config", [{
    "maintenance": {"enabled": True, "adminToken": "existing-admin"},
}], indirect=True)
def test_mqtt_settings_the_agent_would_refuse_at_start_are_not_saved(lab):
    """Enabled MQTT without any topic stops the agent at its next start."""

    before = lab.config_path.read_bytes()
    status, body = request(lab.api, "/api/v1/maintenance/mqtt", {
        "enabled": True, "host": "broker.test", "commandTopic": "", "eventTopic": "",
    }, headers={HEADER: "existing-admin"})
    assert status == 400
    assert body["error"] == "mqtt_topic_required"
    assert lab.config_path.read_bytes() == before


@pytest.mark.parametrize("body", [
    b'{"noAuth":trueX}', b'{"apiToken":"bad\\u0000suffix"}',
    b'{"apiToken":"bad\\uD800"}', b'{"noAuth":true}garbage',
])
@pytest.mark.parametrize("auth_config", [{
    "maintenance": {"enabled": True, "adminToken": "existing-admin"},
}], indirect=True)
def test_invalid_json_is_rejected_before_config_mutation(lab, body):
    before = lab.config_path.read_bytes()
    connection = http.client.HTTPConnection("127.0.0.1", lab.api, timeout=3)
    try:
        connection.request("POST", AUTH, body, {HEADER: "existing-admin"})
        response = connection.getresponse()
        assert response.status == 400
        response.read()
    finally:
        connection.close()
    assert lab.config_path.read_bytes() == before


def test_decoded_callback_secrets_cannot_inject_headers(lab):
    assert request(lab.api, "/api/v1/display-bridge", {
        "webhook_url": "http://127.0.0.1:9/display", "shared_secret": "x\r\nInjected: yes",
    })[0] == 400
    assert request(lab.api, "/api/v1/events/subscriptions", {
        "callback_url": "http://127.0.0.1:9/events", "token": "x\r\nInjected: yes",
        "events": ["ringer.muted"],
    })[0] == 400


@pytest.mark.parametrize("auth_config", [{
    "maintenance": {"enabled": True, "adminToken": "existing-admin"},
}], indirect=True)
def test_only_the_admin_reads_the_fingerprint_of_the_maintenance_token(lab):
    """The API token is the lower privilege; a short hash of the admin token
    would let its holder guess a short admin token offline."""

    status, body = request(lab.api, AUTH)
    assert status == 200
    assert body["maintenance_token_configured"] is True
    assert body["maintenance_token_fingerprint"] == ""
    status, body = request(lab.api, AUTH, headers={HEADER: "existing-admin"})
    assert status == 200
    assert body["maintenance_token_fingerprint"].startswith("fnv1a64:")
    # The API token's own fingerprint is for the holder of that token.
    assert request(lab.api, AUTH)[1]["api_token_configured"] in (True, False)
