from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.bticino_c300x.device_installer import (  # noqa: E402
    DEFAULT_REMOTE_DIR,
    _device_config_json,
)


def test_sample_config_is_bootstrap_only_and_does_not_enable_heavy_paths() -> None:
    config = json.loads(
        (ROOT / "native_agent" / "config.example.json").read_text(encoding="utf-8")
    )

    assert config["listen"] == {
        "host": "127.0.0.1",
        "apiPort": 8091,
        "uiPort": 8090,
        "allowLan": False,
    }
    assert config["api"] == {"token": "", "noAuth": True}
    assert config["maintenance"]["enabled"] is True
    assert config["maintenance"]["allowNoAuth"] is True
    assert config["maintenance"]["sshStart"]["enabled"] is False
    assert config["maintenance"]["reboot"]["enabled"] is False
    assert config["maintenance"]["agentRemove"]["enabled"] is False
    assert config["maintenance"]["guiReload"]["enabled"] is False
    assert config["maintenance"]["qmlPatch"]["enabled"] is False
    assert config["maintenance"]["firewall"]["enabled"] is False
    assert config["maintenance"]["ipv6Firewall"]["enabled"] is False
    assert config["video"]["enabled"] is False
    assert config["displayBridge"]["enabled"] is True
    assert config["displayBridge"]["homeAssistant"]["webhookUrl"].startswith(
        "http://homeassistant.local:"
    )


def test_installer_config_closes_noauth_and_enables_runtime_defaults() -> None:
    config = json.loads(
        _device_config_json(
            api_token="api-token",
            maintenance_token="maintenance-token",
            agent_port=8091,
        )
    )

    assert config["listen"] == {
        "host": "0.0.0.0",
        "apiPort": 8091,
        "uiPort": 8090,
        "allowLan": True,
    }
    assert config["api"] == {"token": "api-token", "noAuth": False}
    assert config["maintenance"]["adminToken"] == "maintenance-token"
    assert config["maintenance"]["allowNoAuth"] is False
    assert config["maintenance"]["firewall"]["enabled"] is True
    assert config["maintenance"]["ipv6Firewall"]["enabled"] is False
    assert config["maintenance"]["qmlPatch"] == {
        "enabled": True,
        "script": f"{DEFAULT_REMOTE_DIR}/qml_patch.sh",
    }
    assert config["maintenance"]["agentRemove"] == {
        "enabled": True,
        "script": f"{DEFAULT_REMOTE_DIR}/remove_agent.sh",
    }
    assert config["video"]["enabled"] is True
    assert config["displayBridge"]["enabled"] is False


def test_agent_setup_completion_closes_noauth_without_disabling_token_auth() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    body = text.rsplit("static void handle_auth_config_post", maxsplit=1)[1].split(
        "static void handle_subscription_delete",
        maxsplit=1,
    )[0]

    assert 'json_bool_field(request->body, "setupComplete", &value)' in body
    assert "if (setup_complete && updated.api_token[0] != '\\0')" in body
    assert "updated.api_no_auth = 0" in body
    assert "updated.maintenance_no_auth_allowed = 0" in body
    assert "updated.api_token[0] = '\\0'" not in body
    assert "updated.maintenance_admin_token[0] = '\\0'" not in body


def test_video_default_is_webrtc_on_demand_with_idle_rtsp_closed() -> None:
    camera_text = (
        ROOT / "custom_components" / "bticino_c300x" / "camera.py"
    ).read_text(encoding="utf-8")
    smoke_text = (ROOT / "native_agent" / "test" / "smoke.py").read_text(
        encoding="utf-8"
    )

    assert (
        "Camera that exposes the agent media bridge through native WebRTC"
        in camera_text
    )
    assert "_attr_frontend_stream_type = \"web_rtc\"" in camera_text
    assert "async_handle_async_webrtc_offer" in camera_text
    assert "async_activate_doorbell_video(audio=True)" in camera_text
    assert "assert_rtsp_not_listening(rtsp_port)" in smoke_text
    assert '"/api/v1/video/doorbell/actions/activate"' in smoke_text
    assert '"/api/v1/video/doorbell/actions/stop"' in smoke_text


def test_gui_and_firewall_writes_are_maintenance_only() -> None:
    http_text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    setup_body = http_text.rsplit("static void handle_setup_page", maxsplit=1)[1].split(
        "static void handle_auth_config_get",
        maxsplit=1,
    )[0]

    assert "apply_qml_patch" not in setup_body
    assert "apply_firewall" not in setup_body
    assert "apply_ipv6_firewall" not in setup_body
    assert "confirm_matches(request, confirmation)" in http_text
    assert '"apply_qml_patch"' in http_text
    assert '"apply_firewall"' in http_text
    assert '"apply_ipv6_firewall"' in http_text


def test_config_mutation_writes_are_semantic_and_idempotent() -> None:
    http_text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    config_text = (ROOT / "native_agent" / "src" / "config.c").read_text(
        encoding="utf-8"
    )
    auth_body = http_text.rsplit("static void handle_auth_config_post", maxsplit=1)[
        1
    ].split("static void handle_mqtt_status", maxsplit=1)[0]
    mqtt_body = http_text.rsplit("static void handle_mqtt_post", maxsplit=1)[1].split(
        "static void handle_subscription_delete",
        maxsplit=1,
    )[0]
    normalize_body = http_text.rsplit(
        "static void handle_config_normalize",
        maxsplit=1,
    )[1].split("static void handle_api_request", maxsplit=1)[0]

    assert "c300x_config_persisted_equal(&baseline, &updated)" in auth_body
    assert "c300x_config_persisted_equal(config, &updated)" in mqtt_body
    assert "c300x_save_config_if_changed(&updated" in auth_body
    assert "c300x_save_config_if_changed(&updated" in mqtt_body
    assert "c300x_save_config_if_changed(config" in normalize_body
    assert "if (changed)" in normalize_body
    assert "memcmp(&baseline" not in auth_body
    assert "memcmp(config, &updated" not in mqtt_body
    assert "return config->api_token_from_env ? config->api_file_token : config->api_token" in config_text
