from __future__ import annotations

import asyncio

import pytest

from custom_components.bticino_c300x.api import (
    C300XAgentApi,
    C300XAgentApiConnectionError,
    C300XAgentApiResponseError,
    build_agent_base_url,
    display_bridge_callback_fingerprint,
    encode_endpoint_url,
    normalize_activation_id,
    normalize_activations,
    normalize_agent_diagnostics,
    normalize_answering_machine,
    normalize_answering_machine_messages,
    normalize_auth_config_status,
    normalize_doorbell_video,
    normalize_firewall_status,
    normalize_legacy_mqtt_status,
    normalize_lock_id,
    normalize_memo_id,
    normalize_memos,
    normalize_mqtt_status,
    normalize_qml_patch_status,
    normalize_ringer,
    normalize_smartphone_forwarding,
    normalize_smartphone_forwarding_mode,
    normalize_ssh_status,
    normalize_stair_light_address,
    normalize_system_metrics,
    normalize_text_memo_text,
    normalize_video_message_id,
)
from custom_components.bticino_c300x.const import HEADER_MAINTENANCE_TOKEN


class _FakeResponse:
    def __init__(
        self,
        status: int = 200,
        text: str = '{"ok": true}',
        body: bytes | None = None,
        content_type: str = "application/json",
    ) -> None:
        self.status = status
        self._text = text
        self._body = body
        self.headers = {"Content-Type": content_type}

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def text(self) -> str:
        return self._text

    async def read(self) -> bytes:
        return self._body if self._body is not None else self._text.encode()


class _FakeSession:
    def __init__(
        self,
        response_text: str = '{"ok": true}',
        *,
        response_status: int = 200,
        response_body: bytes | None = None,
        content_type: str = "application/json",
    ) -> None:
        self.requests: list[dict[str, object]] = []
        self._response_text = response_text
        self._response_status = response_status
        self._response_body = response_body
        self._content_type = content_type

    def request(self, *args: object, **kwargs: object) -> _FakeResponse:
        self.requests.append({"args": args, "kwargs": kwargs})
        return _FakeResponse(
            status=self._response_status,
            text=self._response_text,
            body=self._response_body,
            content_type=self._content_type,
        )


def test_build_agent_base_url_defaults_to_http() -> None:
    assert build_agent_base_url("agent.local", 8080) == (
        "http://agent.local:8080"
    )


def test_build_agent_base_url_handles_ipv6() -> None:
    assert build_agent_base_url("fd00::1", 8080) == "http://[fd00::1]:8080"


def test_encode_endpoint_url_uses_base64() -> None:
    assert encode_endpoint_url("https://ha.example/api/webhook/x") == (
        "aHR0cHM6Ly9oYS5leGFtcGxlL2FwaS93ZWJob29rL3g="
    )


def test_validate_setup_uses_native_agent_version() -> None:
    session = _FakeSession(
        '{"api_version": "1", '
        '"agent": {"implementation": "native-c", "version": "0.2.0"}, '
        '"device": {"id": "c300x-aabbcc001122", '
        '"model": "C300X", "firmware": "1.7.19"}, '
        '"capabilities": {"doorbell_events": true}}'
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    setup = asyncio.run(api.async_validate_setup())

    assert setup["version"] == "0.2.0"
    assert setup["implementation"] == "native-c"
    assert setup["api_version"] == "1"
    assert setup["device_id"] == "c300x-aabbcc001122"
    assert setup["model"] == "C300X"
    assert setup["capabilities"] == {"doorbell_events": True}
    assert session.requests[0]["kwargs"]["timeout"] == 2.0


def test_configure_display_bridge_registers_runtime_webhook() -> None:
    session = _FakeSession('{"ok": true, "configured": true, "source": "runtime"}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    result = asyncio.run(
        api.async_configure_display_bridge(
            enabled=True,
            webhook_url="http://ha.local/api/webhook/display",
            shared_secret="shared-secret",
        )
    )

    assert result["source"] == "runtime"
    request = session.requests[0]
    assert request["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/display-bridge",
    )
    assert request["kwargs"]["headers"] == {"Authorization": "Bearer agent-token"}
    assert request["kwargs"]["json"] == {
        "enabled": True,
        "webhook_url": "http://ha.local/api/webhook/display",
        "shared_secret": "shared-secret",
    }


def test_configure_display_bridge_can_disable_runtime_webhook() -> None:
    session = _FakeSession('{"ok": true, "configured": false}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    assert asyncio.run(api.async_configure_display_bridge(enabled=False))["ok"] is True

    assert session.requests[0]["kwargs"]["json"] == {"enabled": False}


def test_display_bridge_status_requests_read_only_endpoint() -> None:
    session = _FakeSession(
        '{"ok": true, "enabled": true, "configured": true, '
        '"callback_hash": "fnv1a64:abc", "source": "runtime"}'
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    status = asyncio.run(api.async_display_bridge_status())

    assert status["callback_hash"] == "fnv1a64:abc"
    assert session.requests[0]["args"] == (
        "GET",
        "http://agent.local:8080/api/v1/display-bridge",
    )


def test_notify_display_bridge_event_posts_topic() -> None:
    session = _FakeSession('{"ok": true, "revision": 2, "topic": "alarm"}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    result = asyncio.run(api.async_notify_display_bridge_event("alarm"))

    assert result["revision"] == 2
    request = session.requests[0]
    assert request["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/display-bridge/events",
    )
    assert request["kwargs"]["json"] == {"topic": "alarm"}
    assert request["kwargs"]["timeout"] == 2.0


def test_display_bridge_callback_fingerprint_is_stable() -> None:
    assert display_bridge_callback_fingerprint(
        True,
        "http://ha.local/api/webhook/display",
        "shared-secret",
    ) == "fnv1a64:36c9cd1dc3a06b34"


def test_normalize_doorbell_video_exposes_external_media_owner() -> None:
    status = normalize_doorbell_video(
        {
            "ok": True,
            "available": True,
            "window_available": False,
            "stream_path": "/doorbell-video",
            "bridge": {
                "media_owner": "device_display",
                "external_media_active": True,
                "external_owner": "device_display",
                "external_active_until": 1780500000,
                "last_block_reason": "external_session_active",
            },
        }
    )

    assert status["media_owner"] == "device_display"
    assert status["external_media_active"] is True
    assert status["external_owner"] == "device_display"
    assert status["external_active_until"] == 1780500000
    assert status["last_block_reason"] == "external_session_active"
    assert display_bridge_callback_fingerprint(False, "ignored", "ignored") == (
        "fnv1a64:48f6eb502600b569"
    )


def test_agent_http_error_includes_safe_error_name() -> None:
    session = _FakeSession(
        '{"ok": false, "error": "unsupported_webhook_url"}',
        response_status=400,
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    with pytest.raises(
        C300XAgentApiConnectionError,
        match="device agent returned HTTP 400: unsupported_webhook_url",
    ):
        asyncio.run(
            api.async_configure_display_bridge(
                enabled=True,
                webhook_url="https://ha.local/api/webhook/display",
                shared_secret="shared-secret",
            )
        )


def test_mqtt_status_uses_maintenance_endpoint_and_hides_broker_secret() -> None:
    session = _FakeSession(
        '{"ok": true, "enabled": true, "configured": true, "connected": false, '
        '"subscribed": false, "host_configured": true, '
        '"username_configured": true, "password_configured": true, '
        '"port": 1883, "client_id": "c300x-native-agent", '
        '"command_host": "127.0.0.1", "command_port": 30006, '
        '"topics": {"command": "Bticino/rx", "event": "Bticino/tx", '
        '"json_event": "", "status": "Bticino/start_date", '
        '"availability": "Bticino/LastWillT"}, "qos": 0, '
        '"legacy_installed": true, "legacy_enabled": false, '
        '"legacy_running": false, "exclusive": true}'
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    status = asyncio.run(api.async_mqtt_status())

    assert status["enabled"] is True
    assert status["host_configured"] is True
    assert status["password_configured"] is True
    assert status["event_topic"] == "Bticino/tx"
    assert status["legacy_installed"] is True
    assert status["legacy_enabled"] is False
    assert status["exclusive"] is True
    assert "host" not in status
    assert "password" not in status
    request = session.requests[0]
    assert request["args"] == (
        "GET",
        "http://agent.local:8080/api/v1/maintenance/mqtt",
    )
    assert request["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
        HEADER_MAINTENANCE_TOKEN: "maintenance-token",
    }


def test_set_mqtt_enabled_posts_only_enabled_flag() -> None:
    session = _FakeSession('{"ok": true, "enabled": false, "configured": true}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    status = asyncio.run(api.async_set_mqtt_enabled(False))

    assert status["enabled"] is False
    assert session.requests[0]["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/mqtt",
    )
    assert session.requests[0]["kwargs"]["json"] == {"enabled": False}


def test_migrate_legacy_mqtt_posts_explicit_confirmation() -> None:
    session = _FakeSession(
        '{"ok": true, "migrated": true, "legacy_removed": false, '
        '"legacy_disabled": true, '
        '"native_enabled": true}'
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    result = asyncio.run(api.async_migrate_legacy_mqtt_to_native())

    assert result["native_enabled"] is True
    assert session.requests[0]["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/mqtt/actions/migrate-legacy",
    )
    assert session.requests[0]["kwargs"]["json"] == {
        "confirm": "migrate_legacy_mqtt"
    }
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
        HEADER_MAINTENANCE_TOKEN: "maintenance-token",
    }


def test_legacy_mqtt_status_uses_separate_maintenance_endpoint() -> None:
    session = _FakeSession(
        '{"ok": true, "enabled": true, "installed": true, "running": false, '
        '"backup_available": true, "native_enabled": false, "exclusive": true, '
        '"script_path": "/etc/tcpdump2mqtt/TcpDump2Mqtt.sh", '
        '"init_link": "/etc/rc5.d/S99TcpDump2Mqtt", '
        '"flexisip_backup_available": true, '
        '"flexisip_restart_marker": true, '
        '"flexisip_reference_state": "legacy_mqtt_patch"}'
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    status = asyncio.run(api.async_legacy_mqtt_status())

    assert status["enabled"] is True
    assert status["installed"] is True
    assert status["backup_available"] is True
    assert status["native_enabled"] is False
    assert status["script_path"] == "/etc/tcpdump2mqtt/TcpDump2Mqtt.sh"
    assert status["flexisip_backup_available"] is True
    assert status["flexisip_restart_marker"] is True
    assert status["flexisip_reference_state"] == "legacy_mqtt_patch"
    assert session.requests[0]["args"] == (
        "GET",
        "http://agent.local:8080/api/v1/maintenance/legacy-mqtt",
    )


def test_set_legacy_mqtt_enabled_posts_only_enabled_flag() -> None:
    session = _FakeSession('{"ok": true, "enabled": false, "installed": false}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    status = asyncio.run(api.async_set_legacy_mqtt_enabled(False))

    assert status["enabled"] is False
    assert session.requests[0]["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/legacy-mqtt",
    )
    assert session.requests[0]["kwargs"]["json"] == {"enabled": False}


def test_normalize_legacy_mqtt_status_accepts_minimal_payload() -> None:
    assert normalize_legacy_mqtt_status({"enabled": False}) == {
        "available": True,
        "enabled": False,
        "installed": None,
        "running": None,
        "backup_available": None,
        "native_enabled": None,
        "exclusive": False,
        "script_path": None,
        "init_link": None,
        "flexisip_backup_available": None,
        "flexisip_restart_marker": None,
        "flexisip_reference_state": None,
        "raw": {"enabled": False},
    }


def test_normalize_mqtt_status_accepts_minimal_payload() -> None:
    assert normalize_mqtt_status({"enabled": False}) == {
        "available": True,
        "enabled": False,
        "configured": None,
        "connected": None,
        "subscribed": None,
        "host_configured": None,
        "username_configured": None,
        "password_configured": None,
        "port": None,
        "client_id": None,
        "command_host": None,
        "command_port": None,
        "command_topic": None,
        "event_topic": None,
        "json_event_topic": None,
        "status_topic": None,
        "availability_topic": None,
        "qos": None,
        "keepalive_seconds": None,
        "reconnect_initial_seconds": None,
        "reconnect_max_seconds": None,
        "legacy_installed": None,
        "legacy_enabled": None,
        "legacy_running": None,
        "exclusive": False,
        "raw": {"enabled": False},
    }


def test_list_event_subscriptions_requests_authenticated_endpoint() -> None:
    session = _FakeSession(
        '{"ok": true, "subscriptions": ['
        '{"id": "sub-1", "callback_url": "http://ha.local/webhook", '
        '"events": ["agent.restarted"]}]}'
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    subscriptions = asyncio.run(api.async_list_event_subscriptions())

    assert subscriptions["subscriptions"][0]["id"] == "sub-1"
    assert session.requests[0]["args"] == (
        "GET",
        "http://agent.local:8080/api/v1/events/subscriptions",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
    }


def test_start_ssh_sends_maintenance_token_and_confirmation() -> None:
    session = _FakeSession()
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    assert asyncio.run(api.async_start_ssh()) == {"ok": True}

    request = session.requests[0]
    assert request["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/ssh/actions/start",
    )
    assert request["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
        HEADER_MAINTENANCE_TOKEN: "maintenance-token",
    }
    assert request["kwargs"]["json"] == {"confirm": "start_ssh"}


def test_auth_config_status_uses_maintenance_endpoint() -> None:
    session = _FakeSession(
        '{"ok": true, "noAuth": true, "api_token_configured": false, '
        '"maintenance_token_configured": true, "restart_required": true, '
        '"maintenance_no_auth_allowed": false, "mdns_enabled": true, '
        '"firewall_enabled": false, "ipv6_firewall_enabled": true}'
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "",
        maintenance_token="maintenance-token",
    )

    status = asyncio.run(api.async_auth_config_status())

    assert status["no_auth"] is True
    assert status["api_token_configured"] is False
    assert status["maintenance_token_configured"] is True
    assert status["restart_required"] is True
    assert status["maintenance_no_auth_allowed"] is False
    assert status["mdns_enabled"] is True
    assert status["firewall_enabled"] is False
    assert status["ipv6_firewall_enabled"] is True
    assert session.requests[0]["args"] == (
        "GET",
        "http://agent.local:8080/api/v1/maintenance/auth",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer ",
        HEADER_MAINTENANCE_TOKEN: "maintenance-token",
    }


def test_set_no_auth_sends_maintenance_update_with_tokens() -> None:
    session = _FakeSession('{"ok": true, "noAuth": false}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    status = asyncio.run(
        api.async_set_no_auth_enabled(
            False,
            api_token="configured-agent-token",
            maintenance_token="configured-maintenance-token",
            maintenance_no_auth_allowed=False,
        )
    )

    assert status["no_auth"] is False
    request = session.requests[0]
    assert request["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/auth",
    )
    assert request["kwargs"]["json"] == {
        "noAuth": False,
        "apiToken": "configured-agent-token",
        "maintenanceToken": "configured-maintenance-token",
        "maintenanceNoAuthAllowed": False,
    }


def test_set_mdns_discovery_sends_maintenance_update() -> None:
    session = _FakeSession('{"ok": true, "mdns_enabled": false}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    status = asyncio.run(api.async_set_mdns_enabled(False))

    assert status["mdns_enabled"] is False
    assert session.requests[0]["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/auth",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
        HEADER_MAINTENANCE_TOKEN: "maintenance-token",
    }
    assert session.requests[0]["kwargs"]["json"] == {"mdnsEnabled": False}


def test_set_ipv6_firewall_enabled_sends_maintenance_update() -> None:
    session = _FakeSession('{"ok": true, "ipv6_firewall_enabled": true}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    status = asyncio.run(api.async_set_ipv6_firewall_enabled(True))

    assert status["ipv6_firewall_enabled"] is True
    assert session.requests[0]["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/auth",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
        HEADER_MAINTENANCE_TOKEN: "maintenance-token",
    }
    assert session.requests[0]["kwargs"]["json"] == {
        "ipv6FirewallEnabled": True,
        "maintenanceEnabled": True,
    }


def test_set_firewall_enabled_sends_maintenance_update() -> None:
    session = _FakeSession('{"ok": true, "firewall_enabled": true}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    status = asyncio.run(api.async_set_firewall_enabled(True))

    assert status["firewall_enabled"] is True
    assert session.requests[0]["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/auth",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
        HEADER_MAINTENANCE_TOKEN: "maintenance-token",
    }
    assert session.requests[0]["kwargs"]["json"] == {
        "firewallEnabled": True,
        "maintenanceEnabled": True,
    }


def test_set_maintenance_no_auth_sends_maintenance_update() -> None:
    session = _FakeSession('{"ok": true, "maintenance_no_auth_allowed": true}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    status = asyncio.run(api.async_set_maintenance_no_auth_allowed(True))

    assert status["maintenance_no_auth_allowed"] is True
    assert session.requests[0]["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/auth",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
        HEADER_MAINTENANCE_TOKEN: "maintenance-token",
    }
    assert session.requests[0]["kwargs"]["json"] == {
        "maintenanceEnabled": True,
        "maintenanceNoAuthAllowed": True,
    }


def test_agent_update_methods_use_maintenance_endpoints() -> None:
    session = _FakeSession('{"ok": true}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    asyncio.run(
        api.async_prepare_agent_update(
            bundle_hash="sha256:bundle",
            agent_version="0.3.0",
        )
    )
    asyncio.run(
        api.async_upload_agent_update_chunk(
            path="device_agent/scripts/qml_patch.sh",
            sha256="abc",
            mode="700",
            offset=0,
            data=b"payload",
            final=True,
        )
    )
    asyncio.run(api.async_apply_agent_update(bundle_hash="sha256:bundle"))
    asyncio.run(api.async_normalize_agent_config())

    assert session.requests[0]["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/update/prepare",
    )
    assert session.requests[0]["kwargs"]["json"] == {
        "bundle_hash": "sha256:bundle",
        "agent_version": "0.3.0",
    }
    assert session.requests[1]["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/update/file",
    )
    assert session.requests[1]["kwargs"]["json"] == {
        "path": "device_agent/scripts/qml_patch.sh",
        "sha256": "abc",
        "mode": "700",
        "offset": 0,
        "data": "cGF5bG9hZA==",
        "final": True,
    }
    assert session.requests[2]["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/update/apply",
    )
    assert session.requests[2]["kwargs"]["json"] == {
        "bundle_hash": "sha256:bundle",
        "confirm": "update_agent",
    }
    assert session.requests[3]["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/config/actions/normalize",
    )
    assert session.requests[3]["kwargs"]["json"] == {"confirm": "normalize_config"}
    assert session.requests[3]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
        HEADER_MAINTENANCE_TOKEN: "maintenance-token",
    }


def test_start_ssh_omits_maintenance_token_when_unconfigured() -> None:
    session = _FakeSession()
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    assert asyncio.run(api.async_start_ssh()) == {"ok": True}

    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
    }


def test_stop_ssh_sends_maintenance_token_and_confirmation() -> None:
    session = _FakeSession('{"ok": true, "running": false}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    assert asyncio.run(api.async_stop_ssh())["running"] is False

    request = session.requests[0]
    assert request["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/ssh/actions/stop",
    )
    assert request["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
        HEADER_MAINTENANCE_TOKEN: "maintenance-token",
    }
    assert request["kwargs"]["json"] == {"confirm": "stop_ssh"}


def test_set_ssh_enabled_uses_switch_endpoint() -> None:
    session = _FakeSession('{"ok": true, "running": true}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    assert asyncio.run(api.async_set_ssh_enabled(True))["running"] is True

    request = session.requests[0]
    assert request["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/ssh",
    )
    assert request["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
        HEADER_MAINTENANCE_TOKEN: "maintenance-token",
    }
    assert request["kwargs"]["json"] == {"enabled": True}


def test_ssh_status_uses_maintenance_endpoint() -> None:
    session = _FakeSession('{"ok": true, "running": true}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    assert asyncio.run(api.async_ssh_status())["running"] is True
    assert session.requests[0]["args"] == (
        "GET",
        "http://agent.local:8080/api/v1/maintenance/ssh",
    )


def test_reboot_sends_maintenance_token_and_confirmation() -> None:
    session = _FakeSession()
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    assert asyncio.run(api.async_reboot()) == {"ok": True}

    request = session.requests[0]
    assert request["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/reboot",
    )
    assert request["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
        HEADER_MAINTENANCE_TOKEN: "maintenance-token",
    }
    assert request["kwargs"]["json"] == {"confirm": "reboot"}


def test_remove_agent_sends_maintenance_token_and_confirmation() -> None:
    session = _FakeSession('{"ok": true, "action": "remove_agent"}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    assert asyncio.run(api.async_remove_agent())["action"] == "remove_agent"

    request = session.requests[0]
    assert request["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/agent/actions/remove",
    )
    assert request["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
        HEADER_MAINTENANCE_TOKEN: "maintenance-token",
    }
    assert request["kwargs"]["json"] == {"confirm": "remove_agent"}


def test_qml_patch_status_uses_maintenance_endpoint() -> None:
    session = _FakeSession('{"ok": true, "state": "patched"}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    assert asyncio.run(api.async_qml_patch_status())["state"] == "patched"
    assert session.requests[0]["args"] == (
        "GET",
        "http://agent.local:8080/api/v1/maintenance/qml-patch",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
        HEADER_MAINTENANCE_TOKEN: "maintenance-token",
    }


def test_reload_gui_sends_maintenance_confirmation() -> None:
    session = _FakeSession('{"ok": true, "action": "reload_gui"}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    assert asyncio.run(api.async_reload_gui())["action"] == "reload_gui"
    request = session.requests[0]
    assert request["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/gui/actions/reload",
    )
    assert request["kwargs"]["json"] == {"confirm": "reload_gui"}


def test_firewall_status_uses_maintenance_endpoint() -> None:
    session = _FakeSession('{"ok": true, "state": "patched", "api_port": 8091}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    assert asyncio.run(api.async_firewall_status())["patched"] is True
    request = session.requests[0]
    assert request["args"] == (
        "GET",
        "http://agent.local:8080/api/v1/maintenance/firewall",
    )
    assert request["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
        HEADER_MAINTENANCE_TOKEN: "maintenance-token",
    }


def test_apply_firewall_sends_maintenance_confirmation() -> None:
    session = _FakeSession('{"ok": true, "state": "patched", "changed_files": 1}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    assert asyncio.run(api.async_apply_firewall())["changed_files"] == 1
    request = session.requests[0]
    assert request["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/firewall/actions/apply",
    )
    assert request["kwargs"]["json"] == {"confirm": "apply_firewall"}


def test_restore_firewall_sends_maintenance_confirmation() -> None:
    session = _FakeSession('{"ok": true, "state": "original", "changed_files": 1}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    assert asyncio.run(api.async_restore_firewall())["patched"] is False
    request = session.requests[0]
    assert request["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/firewall/actions/restore",
    )
    assert request["kwargs"]["json"] == {"confirm": "restore_firewall"}


def test_ipv6_firewall_methods_use_separate_maintenance_endpoint() -> None:
    session = _FakeSession('{"ok": true, "state": "patched", "family": "ipv6"}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    assert asyncio.run(api.async_ipv6_firewall_status())["family"] == "ipv6"
    assert asyncio.run(api.async_apply_ipv6_firewall())["patched"] is True
    assert asyncio.run(api.async_restore_ipv6_firewall())["patched"] is True
    assert [request["args"] for request in session.requests] == [
        ("GET", "http://agent.local:8080/api/v1/maintenance/ipv6-firewall"),
        (
            "POST",
            "http://agent.local:8080/api/v1/maintenance/ipv6-firewall/actions/apply",
        ),
        (
            "POST",
            "http://agent.local:8080/api/v1/maintenance/ipv6-firewall/actions/restore",
        ),
    ]
    assert session.requests[1]["kwargs"]["json"] == {
        "confirm": "apply_ipv6_firewall"
    }
    assert session.requests[2]["kwargs"]["json"] == {
        "confirm": "restore_ipv6_firewall"
    }


def test_apply_qml_patch_sends_maintenance_confirmation() -> None:
    session = _FakeSession('{"ok": true, "state": "patched"}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    assert asyncio.run(api.async_apply_qml_patch())["state"] == "patched"
    request = session.requests[0]
    assert request["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/qml-patch/actions/apply",
    )
    assert request["kwargs"]["json"] == {"confirm": "apply_qml_patch"}


def test_restore_qml_patch_sends_maintenance_confirmation() -> None:
    session = _FakeSession('{"ok": true, "state": "original"}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    assert asyncio.run(api.async_restore_qml_patch())["state"] == "original"
    request = session.requests[0]
    assert request["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/qml-patch/actions/restore",
    )
    assert request["kwargs"]["json"] == {"confirm": "restore_qml_patch"}


def test_system_metrics_requests_authenticated_metrics_endpoint() -> None:
    session = _FakeSession(
        '{"ok": true, "cpu_count": 2, "cpu_usage_percent": 3.5, '
        '"load_1m": 0.12, "load_5m": 0.34, '
        '"load_15m": 0.56, "load_1m_percent": 6.0, '
        '"load_5m_percent": 17.0, "load_15m_percent": 28.0, '
        '"memory_total_kb": 262144, "memory_available_kb": 196608, '
        '"memory_used_kb": 65536, "memory_usage_percent": 25.0, '
        '"temperature_c": 41.2}'
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    assert asyncio.run(api.async_system_metrics())["load_1m"] == 0.12
    assert session.requests[0]["args"] == (
        "GET",
        "http://agent.local:8080/api/v1/system/metrics",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
    }


def test_agent_diagnostics_requests_authenticated_endpoint() -> None:
    session = _FakeSession(
        '{"ok": true, "agent_write_count": 2, "last_write_class": "subscription", '
        '"last_write_reason": "updated", "subscription_store_writes": 1, '
        '"last_wake_reason": "api", "open_fd_count": 7}'
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    assert asyncio.run(api.async_diagnostics())["agent_write_count"] == 2
    assert session.requests[0]["args"] == (
        "GET",
        "http://agent.local:8080/api/v1/diagnostics",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
    }


def test_activate_doorbell_video_requests_authenticated_endpoint() -> None:
    session = _FakeSession('{"ok": true, "audio": true}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    assert asyncio.run(api.async_activate_doorbell_video(audio=True)) == {
        "ok": True,
        "audio": True,
    }
    assert session.requests[0]["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/video/doorbell/actions/activate",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
    }
    assert session.requests[0]["kwargs"]["json"] == {"audio": True}


def test_doorbell_video_status_uses_reference_status_endpoint() -> None:
    session = _FakeSession(
        '{"available": true, "stream_path": "/doorbell-video", '
        '"audio_stream_path": "/doorbell"}'
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    assert asyncio.run(api.async_doorbell_video_status())["stream_path"] == (
        "/doorbell-video"
    )
    assert session.requests[0]["args"] == (
        "GET",
        "http://agent.local:8080/api/v1/video/doorbell/status",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
    }


def test_stop_doorbell_video_requests_authenticated_endpoint() -> None:
    session = _FakeSession('{"ok": true}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    assert asyncio.run(api.async_stop_doorbell_video()) == {"ok": True}
    assert session.requests[0]["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/video/doorbell/actions/stop",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
    }


def test_normalize_ssh_status_accepts_running_flag() -> None:
    assert normalize_ssh_status({"running": "true"})["running"] is True
    assert normalize_ssh_status({"enabled": False})["running"] is False


def test_normalize_qml_patch_status_derives_state() -> None:
    assert normalize_qml_patch_status({"patched": True}) == {
        "available": True,
        "patched": True,
        "state": "patched",
        "backup_available": None,
        "gui_running": None,
        "raw": {"patched": True},
    }
    assert normalize_qml_patch_status({"state": "original"})["patched"] is False
    partial = normalize_qml_patch_status({"state": "partial", "patched": None})
    assert partial["state"] == "partial"
    assert partial["patched"] is None


def test_normalize_firewall_status_derives_patched_state() -> None:
    assert normalize_firewall_status({"state": "patched", "api_port": "8091"}) == {
        "available": True,
        "state": "patched",
        "patched": True,
        "family": None,
        "exists": None,
        "backup_available": None,
        "api_port": 8091,
        "changed_files": None,
        "raw": {"state": "patched", "api_port": "8091"},
    }
    assert normalize_firewall_status({"state": "missing"})["patched"] is False
    assert normalize_firewall_status({"state": "partial"})["patched"] is None


def test_normalize_auth_config_status_accepts_camel_case_no_auth() -> None:
    assert normalize_auth_config_status({"noAuth": True})["no_auth"] is True


def test_normalize_auth_config_status_accepts_snake_case_no_auth() -> None:
    assert normalize_auth_config_status({"no_auth": True})["no_auth"] is True


def test_answering_machine_messages_requests_authenticated_endpoint() -> None:
    session = _FakeSession(
        '{"ok": true, "available": true, "total": 1, "unread": 1, '
        '"messages": [{"id": "message_1", "read": false, "unix_time": 1710000000}]}'
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    assert asyncio.run(api.async_answering_machine_messages())["unread"] == 1
    assert session.requests[0]["args"] == (
        "GET",
        "http://agent.local:8080/api/v1/answering-machine/messages",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
    }


def test_answering_machine_message_video_requests_authenticated_endpoint() -> None:
    session = _FakeSession(
        response_body=b"video-bytes",
        content_type="video/x-msvideo",
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    body, content_type = asyncio.run(
        api.async_answering_machine_message_video(" message_1 ")
    )

    assert body == b"video-bytes"
    assert content_type == "video/x-msvideo"
    assert session.requests[0]["args"] == (
        "GET",
        "http://agent.local:8080/api/v1/answering-machine/messages/message_1/video",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
    }


def test_delete_answering_machine_message_requests_authenticated_endpoint() -> None:
    session = _FakeSession('{"ok": true, "deleted": true, "id": "message_1"}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    assert asyncio.run(api.async_delete_answering_machine_message("message_1"))[
        "id"
    ] == "message_1"
    assert session.requests[0]["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/answering-machine/messages/actions/delete",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
    }
    assert session.requests[0]["kwargs"]["json"] == {"id": "message_1"}


def test_memos_requests_authenticated_endpoint() -> None:
    session = _FakeSession(
        '{"ok": true, "available": true, "total": 2, "text_total": 1, '
        '"voice_total": 1, "memos": []}'
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    assert asyncio.run(api.async_memos())["text_total"] == 1
    assert session.requests[0]["args"] == (
        "GET",
        "http://agent.local:8080/api/v1/memos",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
    }


def test_delete_memo_requests_authenticated_endpoint() -> None:
    session = _FakeSession('{"ok": true, "deleted": true, "id": "text/memo_1"}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    assert asyncio.run(api.async_delete_memo(" text/memo_1 "))["id"] == "text/memo_1"
    assert session.requests[0]["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/memos/actions/delete",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
    }
    assert session.requests[0]["kwargs"]["json"] == {"id": "text/memo_1"}


def test_create_text_memo_requests_authenticated_endpoint() -> None:
    session = _FakeSession('{"ok": true, "created": true, "id": "text/memo_2"}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    assert asyncio.run(api.async_create_text_memo("Grüße\r\nTest", read=True))[
        "id"
    ] == "text/memo_2"
    assert session.requests[0]["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/memos/text/actions/create",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
    }
    assert session.requests[0]["kwargs"]["json"] == {
        "text_b64": "R3LDvMOfZQpUZXN0",
        "read": True,
    }


def test_normalize_text_memo_text_validates_content() -> None:
    assert normalize_text_memo_text(" a\r\nb ") == " a\nb "
    with pytest.raises(C300XAgentApiResponseError):
        normalize_text_memo_text("   ")
    with pytest.raises(C300XAgentApiResponseError):
        normalize_text_memo_text("a" * 513)
    with pytest.raises(C300XAgentApiResponseError):
        normalize_text_memo_text("bad\x00text")


def test_activations_requests_authenticated_endpoint() -> None:
    session = _FakeSession(
        '{"ok": true, "supported": true, "count": 2, "items": ['
        '{"id": "front_lock", "name": "Front lock", "type": "lock", '
        '"address": "20", "source": "config", "executable": true},'
        '{"id": "unsafe/path", "name": "Unsafe", "executable": true}'
        "]}"
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    activations = asyncio.run(api.async_activations())

    assert activations["supported"] is True
    assert activations["count"] == 2
    assert activations["items"] == [
        {
            "id": "front_lock",
            "name": "Front lock",
            "type": "lock",
            "address_mode": "manual",
            "address": "20",
            "source": "config",
            "executable": True,
        }
    ]
    assert session.requests[0]["args"] == (
        "GET",
        "http://agent.local:8080/api/v1/activations",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
    }


def test_run_device_activation_uses_safe_post_path() -> None:
    session = _FakeSession('{"ok": true, "id": "front_lock"}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    assert asyncio.run(api.async_run_device_activation(" front_lock "))["id"] == (
        "front_lock"
    )
    assert session.requests[0]["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/activations/front_lock/actions/run",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
    }


def test_memo_audio_requests_authenticated_endpoint() -> None:
    session = _FakeSession(response_body=b"RIFF....WAVE", content_type="audio/wav")
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    content, content_type = asyncio.run(api.async_memo_audio(" voice/memo_1 "))

    assert content == b"RIFF....WAVE"
    assert content_type == "audio/wav"
    assert session.requests[0]["args"] == (
        "GET",
        "http://agent.local:8080/api/v1/memos/voice/memo_1/audio",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
    }


def test_normalize_memo_id_rejects_paths_or_unknown_kind() -> None:
    assert normalize_memo_id("voice/memo-1") == "voice/memo-1"
    for value in ("", "memo_1", "text/../memo", "video/memo_1", "text/memo/1"):
        with pytest.raises(C300XAgentApiResponseError):
            normalize_memo_id(value)


def test_normalize_video_message_id_rejects_paths() -> None:
    assert normalize_video_message_id("message-1_2") == "message-1_2"
    for value in ("", "../message_1", "message/1", "message 1"):
        with pytest.raises(C300XAgentApiResponseError):
            normalize_video_message_id(value)


def test_smartphone_forwarding_cached_status_uses_agent_state_endpoint() -> None:
    session = _FakeSession(
        '{"state": {"smartphone_forwarding": "blocked"}}'
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    assert asyncio.run(api.async_smartphone_forwarding_cached_status()) == {
        "mode": 2,
        "state": "blocked",
        "raw": {"state": {"smartphone_forwarding": "blocked"}},
    }
    assert session.requests[0]["args"] == (
        "GET",
        "http://agent.local:8080/api/v1/state",
    )


def test_normalize_stair_light_address_accepts_address() -> None:
    assert normalize_stair_light_address("10") == "10"
    assert normalize_stair_light_address("20#1") == "20#1"


def test_normalize_stair_light_address_rejects_raw_command() -> None:
    with pytest.raises(C300XAgentApiResponseError):
        normalize_stair_light_address("*8*21*10##")


def test_normalize_lock_id_accepts_safe_ids() -> None:
    assert normalize_lock_id("default") == "default"
    assert normalize_lock_id("side_door-1") == "side_door-1"


def test_normalize_lock_id_rejects_paths_or_raw_commands() -> None:
    with pytest.raises(C300XAgentApiResponseError):
        normalize_lock_id("../default")
    with pytest.raises(C300XAgentApiResponseError):
        normalize_lock_id("*8*19*20##")


def test_normalize_activation_id_rejects_paths_or_raw_commands() -> None:
    assert normalize_activation_id("scene_1") == "scene_1"
    for value in ("", "../scene", "scene/1", "*8*21*10##"):
        with pytest.raises(C300XAgentApiResponseError):
            normalize_activation_id(value)


def test_normalize_activations_hides_incomplete_or_invalid_items() -> None:
    assert normalize_activations(
        {
            "supported": True,
            "items": [
                {"id": "scene_1", "name": "", "type": "scenario", "executable": True},
                {"id": "broken/path", "name": "Broken", "executable": True},
                {"id": "unknown", "name": "Unknown", "type": "bad"},
            ],
        }
    ) == {
        "available": True,
        "supported": True,
        "count": 2,
        "items": [
            {
                "id": "scene_1",
                "name": "Scene 1",
                "type": "scenario",
                "address_mode": "manual",
                "address": None,
                "source": "agent",
                "executable": True,
            },
            {
                "id": "unknown",
                "name": "Unknown",
                "type": "unknown",
                "address_mode": "manual",
                "address": None,
                "source": "agent",
                "executable": False,
            },
        ],
        "raw": {
            "supported": True,
            "items": [
                {"id": "scene_1", "name": "", "type": "scenario", "executable": True},
                {"id": "broken/path", "name": "Broken", "executable": True},
                {"id": "unknown", "name": "Unknown", "type": "bad"},
            ],
        },
    }


def test_normalize_doorbell_video_from_agent_bridge() -> None:
    assert normalize_doorbell_video(
        {
            "available": True,
            "window_available": False,
            "stream_path": "/doorbell-video",
            "audio_stream_path": "/doorbell",
            "recorder_stream_path": "/doorbell-recorder",
            "bridge": {
                "enabled": True,
                "running": True,
                "audio_codec": "speex/8000",
                "talkback_supported": True,
                "talkback_payload_type": 97,
            },
        }
    ) == {
        "available": True,
        "window_available": False,
        "active_until": None,
        "stream_path": "/doorbell-video",
        "audio_stream_path": "/doorbell",
        "recorder_stream_path": "/doorbell-recorder",
        "media_owner": "unknown",
        "external_media_active": False,
        "external_owner": None,
        "external_active_until": None,
        "last_block_reason": None,
        "bridge": {
            "enabled": True,
            "running": True,
            "audio_codec": "speex/8000",
            "talkback_supported": True,
            "talkback_payload_type": 97,
        },
        "raw": {
            "available": True,
            "window_available": False,
            "stream_path": "/doorbell-video",
            "audio_stream_path": "/doorbell",
            "recorder_stream_path": "/doorbell-recorder",
            "bridge": {
                "enabled": True,
                "running": True,
                "audio_codec": "speex/8000",
                "talkback_supported": True,
                "talkback_payload_type": 97,
            },
        },
    }


def test_normalize_system_metrics_accepts_missing_temperature() -> None:
    assert normalize_system_metrics(
        {
            "cpu_count": "2",
            "cpu_usage_percent": "3.5",
            "load_1m": "0.1",
            "load_5m": 0.2,
            "load_15m": 0.3,
            "load_1m_percent": "5.0",
            "load_5m_percent": 10.0,
            "load_15m_percent": 15.0,
            "memory_total_kb": "262144",
            "memory_available_kb": 196608,
            "memory_used_kb": 65536,
            "memory_usage_percent": "25.0",
            "temperature_c": None,
        }
    ) == {
        "cpu_count": 2,
        "cpu_usage_percent": 3.5,
        "load_1m": 0.1,
        "load_5m": 0.2,
        "load_15m": 0.3,
        "load_1m_percent": 5.0,
        "load_5m_percent": 10.0,
        "load_15m_percent": 15.0,
        "memory_total_kb": 262144,
        "memory_available_kb": 196608,
        "memory_used_kb": 65536,
        "memory_usage_percent": 25.0,
        "temperature_c": None,
        "temperature_source": None,
        "raw": {
            "cpu_count": "2",
            "cpu_usage_percent": "3.5",
            "load_1m": "0.1",
            "load_5m": 0.2,
            "load_15m": 0.3,
            "load_1m_percent": "5.0",
            "load_5m_percent": 10.0,
            "load_15m_percent": 15.0,
            "memory_total_kb": "262144",
            "memory_available_kb": 196608,
            "memory_used_kb": 65536,
            "memory_usage_percent": "25.0",
            "temperature_c": None,
        },
    }


def test_normalize_system_metrics_rejects_invalid_values() -> None:
    with pytest.raises(C300XAgentApiResponseError):
        normalize_system_metrics({"load_1m": "busy"})


def test_normalize_agent_diagnostics_removes_unusable_values() -> None:
    normalized = normalize_agent_diagnostics(
        {
            "agent_write_count": "2",
            "last_write_at": "1770000000",
            "last_write_reason": " updated ",
            "last_write_class": "subscription",
            "subscription_store_writes": 1,
            "qml_patch_last_action": "",
            "loop_iterations": "10",
            "poll_wakeups": "4",
            "accepted_clients": "3",
            "last_wake_reason": " api ",
            "last_poll_timeout_ms": "5000",
            "last_poll_count": "6",
            "open_fd_count": "9",
            "agent_init_script_present": True,
            "agent_init_link_ok": False,
            "subscription_count": "1",
            "recent_event_count": "4",
            "recent_event_capacity": "16",
            "display_bridge_registered": True,
            "display_bridge_disabled": False,
            "home_assistant_connected_this_run": True,
            "home_assistant_last_seen_at": "1770000010",
            "ui_event_revision": "7",
            "video_running": True,
            "video_media_starting": False,
            "video_call_active": True,
            "video_clients": "1",
            "video_bridge_open_fds": "5",
            "video_bridge_active_threads": "2",
            "flexisip_backup_available": True,
            "flexisip_restart_marker": False,
            "flexisip_backup_marker": True,
            "flexisip_reference_state": "original",
        }
    )

    assert normalized["agent_write_count"] == 2
    assert normalized["last_write_at"] == 1770000000
    assert normalized["last_write_reason"] == "updated"
    assert normalized["last_write_class"] == "subscription"
    assert normalized["subscription_store_writes"] == 1
    assert normalized["qml_patch_last_action"] is None
    assert normalized["loop_iterations"] == 10
    assert normalized["poll_wakeups"] == 4
    assert normalized["accepted_clients"] == 3
    assert normalized["last_wake_reason"] == "api"
    assert normalized["last_poll_timeout_ms"] == 5000
    assert normalized["last_poll_count"] == 6
    assert normalized["open_fd_count"] == 9
    assert normalized["agent_init_script_present"] is True
    assert normalized["agent_init_link_ok"] is False
    assert normalized["subscription_count"] == 1
    assert normalized["recent_event_count"] == 4
    assert normalized["recent_event_capacity"] == 16
    assert normalized["display_bridge_registered"] is True
    assert normalized["display_bridge_disabled"] is False
    assert normalized["home_assistant_connected_this_run"] is True
    assert normalized["home_assistant_last_seen_at"] == 1770000010
    assert normalized["ui_event_revision"] == 7
    assert normalized["video_running"] is True
    assert normalized["video_media_starting"] is False
    assert normalized["video_call_active"] is True
    assert normalized["video_clients"] == 1
    assert normalized["video_bridge_open_fds"] == 5
    assert normalized["video_bridge_active_threads"] == 2
    assert normalized["flexisip_backup_available"] is True
    assert normalized["flexisip_restart_marker"] is False
    assert normalized["flexisip_backup_marker"] is True
    assert normalized["flexisip_reference_state"] == "original"


def test_normalize_smartphone_forwarding() -> None:
    assert normalize_smartphone_forwarding({"mode": "2", "raw": "*#8**37*2##"}) == {
        "mode": 2,
        "state": "blocked",
        "raw": "*#8**37*2##",
    }


def test_normalize_smartphone_forwarding_from_agent_state() -> None:
    assert normalize_smartphone_forwarding(
        {"state": {"smartphone_forwarding": "in-house-only"}}
    ) == {
        "mode": 1,
        "state": "in-house-only",
        "raw": {"state": {"smartphone_forwarding": "in-house-only"}},
    }


def test_normalize_smartphone_forwarding_from_numeric_agent_state() -> None:
    assert normalize_smartphone_forwarding({"state": {"smartphone_forwarding": 2}}) == {
        "mode": 2,
        "state": "blocked",
        "raw": {"state": {"smartphone_forwarding": 2}},
    }


def test_normalize_smartphone_forwarding_from_agent_command_response() -> None:
    assert normalize_smartphone_forwarding({"mode": "blocked", "raw": "*x##"}) == {
        "mode": 2,
        "state": "blocked",
        "raw": "*x##",
    }


def test_normalize_smartphone_forwarding_accepts_unknown_agent_response() -> None:
    assert normalize_smartphone_forwarding({"mode": None, "state": "unknown", "raw": "*#*1##"}) == {
        "mode": None,
        "state": "unknown",
        "raw": "*#*1##",
    }


def test_normalize_smartphone_forwarding_accepts_boolean_agent_state() -> None:
    assert normalize_smartphone_forwarding(
        {"state": {"smartphone_forwarding": True}}
    ) == {
        "mode": 0,
        "state": "enabled",
        "raw": {"state": {"smartphone_forwarding": True}},
    }


def test_normalize_smartphone_forwarding_mode_rejects_unknown_mode() -> None:
    with pytest.raises(C300XAgentApiResponseError):
        normalize_smartphone_forwarding_mode("unknown")


def test_normalize_smartphone_forwarding_rejects_missing_mode() -> None:
    with pytest.raises(C300XAgentApiResponseError):
        normalize_smartphone_forwarding({})


def test_normalize_ringer_from_agent_state() -> None:
    assert normalize_ringer({"state": {"ringer_muted": True}}) == {
        "muted": True,
        "raw": {"state": {"ringer_muted": True}},
    }


def test_normalize_ringer_from_command_response() -> None:
    assert normalize_ringer({"muted": False, "raw": "*#8**33*1##"}) == {
        "muted": False,
        "raw": "*#8**33*1##",
    }


def test_normalize_ringer_accepts_string_state() -> None:
    assert normalize_ringer({"state": {"ringer_muted": "off"}}) == {
        "muted": False,
        "raw": {"state": {"ringer_muted": "off"}},
    }


def test_normalize_answering_machine_from_agent_state() -> None:
    assert normalize_answering_machine(
        {"state": {"answering_machine_enabled": "on"}}
    ) == {
        "enabled": True,
        "greeting_message_enabled": None,
        "status_fields": [],
        "raw": {"state": {"answering_machine_enabled": "on"}},
    }


def test_normalize_answering_machine_from_command_response() -> None:
    assert normalize_answering_machine({"enabled": False, "raw": "*#8**40*0*0##"}) == {
        "enabled": False,
        "greeting_message_enabled": None,
        "status_fields": [],
        "raw": "*#8**40*0*0##",
    }


def test_normalize_answering_machine_keeps_greeting_status() -> None:
    assert normalize_answering_machine(
        {
            "enabled": True,
            "greeting_message_enabled": False,
            "status_fields": ["1", "0", "0153", "1", "25"],
            "raw": "*#8**40*1*0*0153*1*25##",
        }
    ) == {
        "enabled": True,
        "greeting_message_enabled": False,
        "status_fields": ["1", "0", "0153", "1", "25"],
        "raw": "*#8**40*1*0*0153*1*25##",
    }


def test_normalize_answering_machine_messages() -> None:
    assert normalize_answering_machine_messages(
        {
            "available": True,
            "total": "2",
            "unread": "1",
            "read": 1,
            "newest_at": "2024-03-09T16:02:00.000Z",
            "messages": [
                {
                    "id": "message_2",
                    "read": True,
                    "date": "09/03/2024",
                    "unix_time": "1710000120",
                    "iso_time": "2024-03-09T16:02:00.000Z",
                    "has_thumbnail": False,
                    "has_video": True,
                    "media_mime_type": "video/x-msvideo",
                    "media_size": "42",
                }
            ],
        }
    ) == {
        "available": True,
        "total": 2,
        "unread": 1,
        "read": 1,
        "newest_at": "2024-03-09T16:02:00.000Z",
        "messages": [
            {
                "id": "message_2",
                "read": True,
                "date": "09/03/2024",
                "unix_time": 1710000120,
                "iso_time": "2024-03-09T16:02:00.000Z",
                "has_thumbnail": False,
                "has_video": True,
                "media_mime_type": "video/x-msvideo",
                "media_size": 42,
            }
        ],
        "raw": {
            "available": True,
            "total": "2",
            "unread": "1",
            "read": 1,
            "newest_at": "2024-03-09T16:02:00.000Z",
            "messages": [
                {
                    "id": "message_2",
                    "read": True,
                    "date": "09/03/2024",
                    "unix_time": "1710000120",
                    "iso_time": "2024-03-09T16:02:00.000Z",
                    "has_thumbnail": False,
                    "has_video": True,
                    "media_mime_type": "video/x-msvideo",
                    "media_size": "42",
                }
            ],
        },
    }


def test_normalize_memos() -> None:
    assert normalize_memos(
        {
            "available": True,
            "total": "2",
            "text_total": "1",
            "voice_total": "1",
            "unread": "2",
            "read": 0,
            "newest_at": "2024-03-09T16:02:00Z",
            "memos": [
                {
                    "id": "text/memo_1",
                    "kind": "text",
                    "read": False,
                    "date": "09/03/2024",
                    "unix_time": "1710000120",
                    "iso_time": "2024-03-09T16:02:00Z",
                    "has_text": True,
                    "has_audio": False,
                    "text": "local memo",
                    "text_truncated": False,
                },
                {
                    "id": "voice/memo_1",
                    "kind": "voice",
                    "read": False,
                    "has_text": False,
                    "has_audio": True,
                    "audio_mime_type": "audio/wav",
                    "audio_size": "12",
                },
            ],
        }
    ) == {
        "available": True,
        "total": 2,
        "text_total": 1,
        "voice_total": 1,
        "unread": 2,
        "read": 0,
        "newest_at": "2024-03-09T16:02:00Z",
        "memos": [
            {
                "id": "text/memo_1",
                "kind": "text",
                "read": False,
                "date": "09/03/2024",
                "unix_time": 1710000120,
                "iso_time": "2024-03-09T16:02:00Z",
                "has_text": True,
                "has_audio": False,
                "audio_mime_type": None,
                "audio_size": None,
                "text": "local memo",
                "text_truncated": False,
            },
            {
                "id": "voice/memo_1",
                "kind": "voice",
                "read": False,
                "date": None,
                "unix_time": None,
                "iso_time": None,
                "has_text": False,
                "has_audio": True,
                "audio_mime_type": "audio/wav",
                "audio_size": 12,
                "text": None,
                "text_truncated": False,
            },
        ],
        "raw": {
            "available": True,
            "total": "2",
            "text_total": "1",
            "voice_total": "1",
            "unread": "2",
            "read": 0,
            "newest_at": "2024-03-09T16:02:00Z",
            "memos": [
                {
                    "id": "text/memo_1",
                    "kind": "text",
                    "read": False,
                    "date": "09/03/2024",
                    "unix_time": "1710000120",
                    "iso_time": "2024-03-09T16:02:00Z",
                    "has_text": True,
                    "has_audio": False,
                    "text": "local memo",
                    "text_truncated": False,
                },
                {
                    "id": "voice/memo_1",
                    "kind": "voice",
                    "read": False,
                    "has_text": False,
                    "has_audio": True,
                    "audio_mime_type": "audio/wav",
                    "audio_size": "12",
                },
            ],
        },
    }
