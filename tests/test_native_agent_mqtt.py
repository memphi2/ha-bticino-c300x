from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_native_mqtt_bridge_has_no_external_runtime_dependency() -> None:
    bridge = _read("native_agent/src/mqtt_bridge.c")

    forbidden = ("libmosquitto", "mosquitto_", "paho", "tcpdump", "TcpDump2Mqtt")
    assert not any(token in bridge for token in forbidden)
    assert "MQTT_PACKET_CONNECT" in bridge
    assert "MQTT_PACKET_PUBLISH" in bridge


def test_native_mqtt_config_uses_agent_json_not_legacy_files() -> None:
    source = "\n".join(
        _read(path)
        for path in (
            "native_agent/src/config.c",
            "native_agent/config.example.json",
        )
    )

    assert "TcpDump2Mqtt" not in source
    assert "StartMqttSend" not in source
    assert "StartMqttReceive" not in source
    assert "mqtt_host" in source
    assert '"mqtt"' in source


def test_legacy_mqtt_patch_has_separate_maintenance_path() -> None:
    http = _read("native_agent/src/http.c")

    assert '"/api/v1/maintenance/legacy-mqtt"' in http
    assert '"/api/v1/maintenance/mqtt/actions/migrate-legacy"' in http
    assert "legacy_mqtt_disable_patch" in http
    assert "legacy_mqtt_enable_patch" in http
    assert "legacy_mqtt_restore_from_backup" in http
    assert "legacy_mqtt_import_config" in http
    assert "MQTT_HOST" in http
    assert "TOPIC_RX" in http
    assert "mqtt_disabled_for_legacy" in http
    assert "/usr/bin/jq" not in http
    assert "/usr/bin/evtest" not in http


def test_legacy_mqtt_disable_does_not_touch_flexisip_or_delete_patch_files() -> None:
    http = _read("native_agent/src/http.c")
    disable = http[
        http.rindex("static int legacy_mqtt_disable_patch") :
        http.rindex("static void handle_legacy_mqtt_status")
    ]
    migrate = http[
        http.rindex("static void handle_mqtt_migrate_legacy_post") :
        http.rindex("static int maybe_json_mqtt_string")
    ]

    assert "flexisip" not in disable.lower()
    assert "flexisip" not in migrate.lower()
    assert "mosquitto" not in http.lower()
    assert "unlink_if_exists(C300X_LEGACY_MQTT_INIT_LINK" in disable
    assert "C300X_LEGACY_MQTT_BROKER" not in http
    assert "legacy_mqtt_start_broker_if_needed" not in http
    assert "legacy_mqtt_broker_running" not in http
    assert "remove_tree" not in disable
    assert 'unlink("/home/root/filter.py")' not in disable
    assert 'rm -rf /etc/tcpdump2mqtt' not in disable


def test_legacy_mqtt_enable_does_not_start_duplicate_processes() -> None:
    http = _read("native_agent/src/http.c")
    handler = http[
        http.index("static void handle_legacy_mqtt_post") :
        http.index("static void handle_mqtt_migrate_legacy_post")
    ]

    assert "bridge_was_running = legacy_mqtt_bridge_running();" in handler
    assert "should_start_bridge = !bridge_was_running;" in handler
    assert "should_start_bridge = 1;" not in handler
    assert "legacy_mqtt_start_broker_if_needed" not in handler


def test_native_mqtt_default_config_is_disabled_with_legacy_topics() -> None:
    config = json.loads(_read("native_agent/config.example.json"))

    assert config["mqtt"]["enabled"] is False
    assert config["mqtt"]["host"] == ""
    assert config["mqtt"]["port"] == 1883
    assert config["mqtt"]["commandHost"] == "127.0.0.1"
    assert config["mqtt"]["commandPort"] == 30006
    assert config["mqtt"]["topics"] == {
        "command": "Bticino/rx",
        "event": "Bticino/tx",
        "jsonEvent": "",
        "status": "Bticino/start_date",
        "availability": "Bticino/LastWillT",
    }


def test_native_mqtt_events_do_not_depend_on_ha_webhook_subscriptions() -> None:
    http = _read("native_agent/src/http.c")
    start = http.rindex("static void dispatch_event_internal")
    dispatch = http[start : http.index("static int has_matching_subscription", start)]

    assert dispatch.index("c300x_mqtt_publish_event") < dispatch.index(
        "has_matching_subscription"
    )


def test_native_mqtt_loop_is_event_driven_and_disabled_by_config() -> None:
    http = _read("native_agent/src/http.c")
    bridge = _read("native_agent/src/mqtt_bridge.c")

    assert "c300x_mqtt_open_if_needed(&runtime->mqtt, config, network_online, now)" in http
    assert "c300x_mqtt_handle_poll" in http
    assert "c300x_mqtt_tick" in http
    assert "handle_mqtt_commands(config, runtime)" in http
    assert "if (!config->mqtt_enabled || !network_online)" in bridge


def test_native_mqtt_start_date_matches_legacy_datetime_payload() -> None:
    bridge = _read("native_agent/src/mqtt_bridge.c")

    assert 'strftime(payload, payload_len, "%Y-%m-%dT%H:%M:%S"' in bridge
    assert "mqtt_format_start_date(now, payload, sizeof(payload))" in bridge


def test_native_mqtt_reconfiguration_clears_stale_retry_deadline() -> None:
    header = _read("native_agent/src/mqtt_bridge.h")
    bridge = _read("native_agent/src/mqtt_bridge.c")
    http = _read("native_agent/src/http.c")

    assert "void c300x_mqtt_reset_retry(struct c300x_mqtt *mqtt);" in header
    assert "mqtt->next_connect_at = 0;" in bridge
    assert "mqtt->reconnect_delay_seconds = 0;" in bridge

    migrate = http[
        http.rindex("static void handle_mqtt_migrate_legacy_post") :
        http.rindex("static int maybe_json_mqtt_string")
    ]
    config = http[
        http.rindex("static void handle_mqtt_post") :
        http.rindex("static void handle_subscription_delete")
    ]
    assert "c300x_mqtt_close(&runtime->mqtt);\n            c300x_mqtt_reset_retry(&runtime->mqtt);" in migrate
    assert "c300x_mqtt_close(&runtime->mqtt);\n        c300x_mqtt_reset_retry(&runtime->mqtt);" in config


def test_native_mqtt_status_response_checks_for_truncation() -> None:
    http = _read("native_agent/src/http.c")
    status = http[
        http.rindex("static void handle_mqtt_status") :
        http.rindex("static int mqtt_runtime_config_is_valid")
    ]

    assert "MQTT_STATUS_BODY_LEN = 8192" in status
    assert "written = snprintf(" in status
    assert "written < 0 || written >= (int)sizeof(workspace->body)" in status
    assert "mqtt_status_too_large" in status


def test_native_mqtt_config_is_saved_before_legacy_bridge_disable() -> None:
    http = _read("native_agent/src/http.c")
    handler = http[
        http.rindex("static void handle_mqtt_post") :
        http.rindex("static void handle_subscription_delete")
    ]

    assert handler.index("c300x_save_config_if_changed") < handler.index(
        "legacy_mqtt_disable_patch"
    )


def test_native_mqtt_migration_saves_config_before_legacy_bridge_disable() -> None:
    http = _read("native_agent/src/http.c")
    handler = http[
        http.rindex("static void handle_mqtt_migrate_legacy_post") :
        http.rindex("static int maybe_json_mqtt_string")
    ]

    assert handler.index("c300x_save_config_if_changed") < handler.index(
        "legacy_mqtt_disable_patch"
    )
