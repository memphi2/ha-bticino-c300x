from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_config_admin_does_not_bypass_maintenance_gate_with_no_auth() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    body = text.rsplit("static int config_admin_authorized", maxsplit=1)[1].split(
        "\n}\n",
        maxsplit=1,
    )[0]

    assert "config->api_no_auth" not in body
    assert "has_valid_bearer(request, config->api_token)" in body
    assert "maintenance_authorized(config, request)" in body


def test_maintenance_can_explicitly_allow_no_auth_bootstrap() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    body = text.rsplit("static int maintenance_authorized", maxsplit=1)[1].split(
        "\n}\n",
        maxsplit=1,
    )[0]

    assert "config->api_no_auth && config->maintenance_no_auth_allowed" in body


def test_empty_api_token_never_accepts_empty_bearer_header() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    body = text.rsplit("static int has_valid_bearer", maxsplit=1)[1].split(
        "static int api_request_authorized",
        maxsplit=1,
    )[0]

    assert "if (token == NULL || token[0] == '\\0')" in body
    assert "constant_time_equal(token_start, token_len, token)" in body


def test_auth_config_read_remains_available_in_no_auth_bootstrap() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    read_body = text.rsplit("static int auth_config_read_authorized", maxsplit=1)[
        1
    ].split("\n}\n", maxsplit=1)[0]
    route_body = text.split(
        'if (strcmp(request->path, "/api/v1/maintenance/auth") == 0) {',
        maxsplit=1,
    )[1].split("if (!api_request_authorized", maxsplit=1)[0]

    assert "config->api_no_auth || config_admin_authorized(config, request)" in read_body
    assert "auth_config_read_authorized(config, request)" in route_body
    assert "handle_auth_config_post(client_fd, config, runtime, request)" in route_body


def test_setup_page_marks_save_as_bootstrap_completion() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    page_body = text.rsplit("static void handle_setup_page", maxsplit=1)[1].split(
        "static void handle_auth_config_get",
        maxsplit=1,
    )[0]

    assert "setupComplete:true" in page_body
    assert "API token for requests" in page_body
    assert "Maintenance token for requests" in page_body
    assert "enter token if configured" in page_body
    assert "if(d.api_token!==undefined)" not in page_body
    assert "if(d.maintenance_token!==undefined)" not in page_body


def test_setup_page_is_only_served_during_no_auth_bootstrap() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    route_body = text.split(
        'strcmp(request->path, "/setup") == 0',
        maxsplit=1,
    )[1].split('if (strcmp(request->method, "GET") == 0 && strcmp(request->path, "/api/v1/health") == 0)', maxsplit=1)[0]

    assert "if (config->api_no_auth)" in route_body
    assert 'handle_setup_page(client_fd);' in route_body
    assert "setup_disabled" in route_body


def test_auth_config_read_never_returns_configured_tokens() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    get_body = text.rsplit("static void handle_auth_config_get", maxsplit=1)[1].split(
        "static int json_optional_port",
        maxsplit=1,
    )[0]

    assert "json_string(config->api_token" not in get_body
    assert (
        "json_string(config->maintenance_admin_token" not in get_body
    )
    assert '"\\"api_token\\":%s,"' not in get_body
    assert '"\\"maintenance_token\\":%s,"' not in get_body
    assert '"\\"api_token_fingerprint\\":%s,"' in get_body
    assert '"\\"maintenance_token_fingerprint\\":%s,"' in get_body
    assert "fnv1a64_fingerprint(config->api_token" in get_body
    assert "fnv1a64_fingerprint(\n            config->maintenance_admin_token" in get_body


def test_auth_config_exposes_and_updates_activation_settings() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    get_body = text.rsplit("static void handle_auth_config_get", maxsplit=1)[1].split(
        "static int json_optional_port",
        maxsplit=1,
    )[0]
    post_body = text.rsplit("static void handle_auth_config_post", maxsplit=1)[
        1
    ].split("static int legacy_mqtt_installed", maxsplit=1)[0]

    assert '"\\"activations_enabled\\":%s,"' in get_body
    assert '"\\"activations_auto_discover\\":%s"' in get_body
    assert "activation_stair_light_address" not in get_body
    assert 'json_bool_field(request->body, "activationsEnabled", &value)' in post_body
    assert (
        'json_bool_field(request->body, "activationsAutoDiscover", &value)'
        in post_body
    )
    assert '"activationItemsJson"' in post_body
    assert "c300x_config_set_activation_items_json" in post_body
    assert "activationStairLightAddress" not in post_body
    assert "configure_stair_light_activation" not in post_body
    assert "auth_config_activations_changed" in post_body


def test_setup_completion_closes_no_auth_when_api_token_exists() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    post_body = text.rsplit("static void handle_auth_config_post", maxsplit=1)[
        1
    ].split("static void handle_subscription_delete", maxsplit=1)[0]

    assert 'json_bool_field(request->body, "setupComplete", &value)' in post_body
    assert "setup_complete = value" in post_body
    assert "if (setup_complete && updated->api_token[0] != '\\0')" in post_body
    assert "updated->api_no_auth = 0" in post_body
    assert "updated->maintenance_no_auth_allowed = 0" in post_body


def test_remove_agent_endpoint_is_maintenance_guarded_and_confirmed() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    body = text.rsplit("static void handle_remove_agent", maxsplit=1)[1].split(
        "static void handle_restart_agent",
        maxsplit=1,
    )[0]
    route_body = text.split(
        '"/api/v1/maintenance/agent/actions/remove"',
        maxsplit=1,
    )[1].split("handle_gui_reload", maxsplit=1)[0]

    assert "maintenance_authorized(config, request)" in body
    assert 'confirm_matches(request, "remove_agent")' in body
    assert 'run_detached_command("/etc/init.d/dropbear", "start", 0)' in body
    assert "run_detached_command(config->maintenance_agent_remove_script, \"remove\", 500)" in body
    assert "handle_remove_agent(client_fd, config, request)" in route_body


def test_restart_agent_endpoint_is_maintenance_guarded_and_confirmed() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    body = text.rsplit("static void handle_restart_agent", maxsplit=1)[1].split(
        "static void handle_agent_update_status",
        maxsplit=1,
    )[0]
    route_body = text.split(
        '"/api/v1/maintenance/agent/actions/restart"',
        maxsplit=1,
    )[1].split('"/api/v1/maintenance/update/status"', maxsplit=1)[0]

    assert "maintenance_authorized(config, request)" in body
    assert 'confirm_matches(request, "restart_agent")' in body
    assert 'run_detached_command(C300X_AGENT_INIT_SCRIPT, "restart", 500)' in body
    assert "handle_restart_agent(client_fd, config, request)" in route_body


def test_remove_agent_script_restores_before_deleting_agent_files() -> None:
    text = (ROOT / "native_agent" / "scripts" / "remove_agent.sh").read_text(
        encoding="utf-8"
    )

    assert 'Usage: %s remove' in text
    assert 'exec "$TMP_SELF" --run-from-tmp' in text
    assert "restore_qml" in text
    assert "Failed to restore Display patch; keeping agent files and backups in place" in text
    assert "restore_file_or_remove_block \"$IPTABLES6\"" in text
    assert "restore_file_or_remove_block \"$IPTABLES\"" in text
    assert text.index("restore_qml") < text.index('rm -rf "$AGENT_DIR" "$BACKUP_ROOT"')
    assert text.index("restore_file_or_remove_block \"$IPTABLES6\"") < text.index(
        'rm -rf "$AGENT_DIR" "$BACKUP_ROOT"'
    )
    assert text.index("restore_file_or_remove_block \"$IPTABLES\"") < text.index(
        'rm -rf "$AGENT_DIR" "$BACKUP_ROOT"'
    )
    sequence = text.split("start_ssh\nrestore_qml", maxsplit=1)[1]
    assert sequence.index("restore_file_or_remove_block \"$IPTABLES6\"") < sequence.index(
        "remove_startup"
    )
    assert sequence.index("restore_file_or_remove_block \"$IPTABLES\"") < sequence.index(
        "remove_startup"
    )
    assert sequence.index("remove_startup") < sequence.index("stop_agent")
    assert sequence.index("stop_agent") < sequence.index(
        'rm -rf "$AGENT_DIR" "$BACKUP_ROOT"'
    )
    assert sequence.index('rm -rf "$AGENT_DIR" "$BACKUP_ROOT"') < sequence.rindex(
        "start_ssh"
    )
