from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest
from aiohttp import ClientError

from custom_components.bticino_c300x.agent_contracts import (
    AgentDiagnosticsStatus,
    AuthConfigStatus,
    CapabilityPayload,
    DoorbellVideoStatus,
    FirewallStatus,
    HomeCallStatus,
    RingCallStatus,
    SelfTestStatus,
)
from custom_components.bticino_c300x.api import (
    C300XAgentApi,
    C300XAgentApiConnectionError,
    C300XAgentApiResponseError,
    C300XAgentApiUnsupportedError,
    build_agent_base_url,
    display_bridge_callback_fingerprint,
    encode_endpoint_url,
    normalize_activation_id,
    normalize_activations,
    normalize_agent_diagnostics,
    normalize_answering_machine,
    normalize_answering_machine_messages,
    normalize_auth_config_status,
    normalize_device_user_status,
    normalize_doorbell_call,
    normalize_doorbell_video,
    normalize_firewall_status,
    normalize_home_call,
    normalize_legacy_mqtt_status,
    normalize_lock_id,
    normalize_memo_id,
    normalize_memos,
    normalize_mqtt_status,
    normalize_qml_patch_status,
    normalize_ringer,
    normalize_self_test,
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


class _QueuedSession:
    def __init__(self, responses: list[tuple[int, str]]) -> None:
        self.requests: list[dict[str, object]] = []
        self._responses = list(responses)

    def request(self, *args: object, **kwargs: object) -> _FakeResponse:
        self.requests.append({"args": args, "kwargs": kwargs})
        status, text = self._responses.pop(0)
        return _FakeResponse(status=status, text=text)


class _RaisingSession:
    def __init__(self, exception: Exception) -> None:
        self.requests: list[dict[str, object]] = []
        self._exception = exception

    def request(self, *args: object, **kwargs: object) -> _FakeResponse:
        self.requests.append({"args": args, "kwargs": kwargs})
        raise self._exception


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

    assert isinstance(setup, CapabilityPayload)
    assert setup["version"] == "0.2.0"
    assert setup["implementation"] == "native-c"
    assert setup["api_version"] == "1"
    assert setup["device_id"] == "c300x-aabbcc001122"
    assert setup["model"] == "C300X"
    assert setup["capabilities"] == {"doorbell_events": True}
    assert session.requests[0]["kwargs"]["timeout"] == 2.0


def test_validate_setup_rejects_non_object_capabilities() -> None:
    session = _FakeSession("[]")
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    with pytest.raises(C300XAgentApiResponseError):
        asyncio.run(api.async_validate_setup())


def test_json_request_rejects_invalid_json() -> None:
    session = _FakeSession("not json")
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    with pytest.raises(C300XAgentApiResponseError, match="invalid JSON"):
        asyncio.run(api.async_state())


@pytest.mark.parametrize(
    ("exception", "message"),
    [
        (TimeoutError(), "timed out"),
        (ClientError("connection lost"), "connection lost"),
    ],
)
def test_json_request_wraps_transport_errors(
    exception: Exception,
    message: str,
) -> None:
    session = _RaisingSession(exception)
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    with pytest.raises(C300XAgentApiConnectionError, match=message):
        asyncio.run(api.async_state())


def test_byte_request_reports_unsupported_endpoint() -> None:
    session = _FakeSession(
        '{"error": "missing"}',
        response_status=404,
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    with pytest.raises(C300XAgentApiUnsupportedError, match="missing"):
        asyncio.run(api.async_memo_audio("voice/memo_1"))


def test_byte_request_reports_http_error() -> None:
    session = _FakeSession(
        '{"message": "media failed"}',
        response_status=503,
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    with pytest.raises(C300XAgentApiConnectionError, match="media failed"):
        asyncio.run(api.async_memo_audio("voice/memo_1"))


@pytest.mark.parametrize(
    ("exception", "message"),
    [
        (TimeoutError(), "timed out"),
        (ClientError("connection reset"), "connection reset"),
    ],
)
def test_byte_request_wraps_transport_errors(
    exception: Exception,
    message: str,
) -> None:
    session = _RaisingSession(exception)
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    with pytest.raises(C300XAgentApiConnectionError, match=message):
        asyncio.run(api.async_memo_audio("voice/memo_1"))


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


@pytest.mark.parametrize(
    ("method_name", "args", "kwargs", "expected_path", "expected_json"),
    [
        (
            "async_create_text_memo",
            ("hello",),
            {"read": True},
            "/api/v1/memos/text/actions/create",
            {"text_b64": "aGVsbG8=", "read": True},
        ),
        (
            "async_delete_memo",
            ("text/memo_1",),
            {},
            "/api/v1/memos/actions/delete",
            {"id": "text/memo_1"},
        ),
        (
            "async_stop_doorbell_video",
            (),
            {},
            "/api/v1/video/doorbell/actions/stop",
            None,
        ),
        (
            "async_answer_doorbell_call",
            (),
            {},
            "/api/v1/calls/doorbell/actions/answer",
            None,
        ),
        (
            "async_hangup_doorbell_call",
            (),
            {},
            "/api/v1/calls/doorbell/actions/hangup",
            None,
        ),
        (
            "async_capture_doorbell_call",
            (),
            {},
            "/api/v1/calls/doorbell/actions/capture",
            None,
        ),
        (
            "async_start_home_call",
            (),
            {"duration_seconds": 9},
            "/api/v1/calls/home/actions/start",
            {"duration_seconds": 9},
        ),
        (
            "async_stop_home_call",
            (),
            {},
            "/api/v1/calls/home/actions/stop",
            None,
        ),
        (
            "async_migrate_legacy_mqtt_to_native",
            (),
            {},
            "/api/v1/maintenance/mqtt/actions/migrate-legacy",
            {"confirm": "migrate_legacy_mqtt"},
        ),
        (
            "async_restore_homeassistant_media_user_setup",
            (),
            {},
            "/api/v1/maintenance/device-user/actions/restore-homeassistant-setup",
            {"confirm": "restore_ha_user_setup"},
        ),
    ],
)
def test_api_command_methods_use_expected_endpoint_and_payload(
    method_name: str,
    args: tuple[object, ...],
    kwargs: dict[str, object],
    expected_path: str,
    expected_json: dict[str, object] | None,
) -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []
    api = C300XAgentApi(
        _FakeSession(),  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        "maintenance-token",
    )

    async def request_json(method: str, path: str, **request_kwargs: object) -> dict[str, object]:
        calls.append((method, path, request_kwargs))
        return {"ok": True}

    api._request_json = request_json  # type: ignore[method-assign]

    result = asyncio.run(getattr(api, method_name)(*args, **kwargs))

    if "ok" in result:
        assert result["ok"] is True
    assert calls[0][0] == "POST"
    assert calls[0][1] == expected_path
    if expected_json is None:
        assert "json_data" not in calls[0][2]
    else:
        assert calls[0][2]["json_data"] == expected_json


def test_api_control_methods_normalize_payloads_before_posting() -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []
    api = C300XAgentApi(
        _FakeSession(),  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    async def request_json(method: str, path: str, **request_kwargs: object) -> dict[str, object]:
        calls.append((method, path, request_kwargs))
        if path == "/api/v1/smartphone-forwarding":
            return {"mode": "enabled"}
        return {"ok": True}

    api._request_json = request_json  # type: ignore[method-assign]

    forwarding = asyncio.run(api.async_set_smartphone_forwarding_mode(" enabled "))
    stair_light = asyncio.run(api.async_stair_light(" 21 "))
    unlock = asyncio.run(api.async_unlock_door(" front_door "))

    assert forwarding["state"] == "enabled"
    assert stair_light == {"ok": True}
    assert unlock == {"ok": True}
    assert calls == [
        (
            "POST",
            "/api/v1/smartphone-forwarding",
            {"json_data": {"mode": "enabled"}},
        ),
        (
            "POST",
            "/api/v1/stair-light/actions/activate",
            {"json_data": {"address": "21"}},
        ),
        (
            "POST",
            "/api/v1/locks/front_door/actions/unlock",
            {},
        ),
    ]


def test_memo_audio_rejects_text_memo_id_before_request() -> None:
    session = _FakeSession()
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    with pytest.raises(C300XAgentApiResponseError, match="voice memo"):
        asyncio.run(api.async_memo_audio("text/memo_1"))

    assert session.requests == []


def test_api_maintenance_auth_methods_include_safe_payloads_and_headers() -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []
    api = C300XAgentApi(
        _FakeSession(),  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        "maintenance-token",
    )

    async def request_json(method: str, path: str, **request_kwargs: object) -> dict[str, object]:
        calls.append((method, path, request_kwargs))
        return {
            "no_auth": False,
            "api_token_configured": True,
            "maintenance_token_configured": True,
            "maintenance_enabled": True,
            "maintenance_no_auth_allowed": True,
            "mdns_enabled": True,
            "firewall_enabled": True,
            "ipv6_firewall_enabled": True,
        }

    api._request_json = request_json  # type: ignore[method-assign]

    status = asyncio.run(api.async_auth_config_status())

    assert isinstance(status, AuthConfigStatus)
    assert status["maintenance_enabled"] is True
    assert asyncio.run(
        api.async_set_no_auth_enabled(
            True,
            api_token="api",
            maintenance_token="maint",
            maintenance_no_auth_allowed=True,
        )
    )["no_auth"] is False
    assert asyncio.run(api.async_set_mdns_enabled(False))["mdns_enabled"] is True
    assert asyncio.run(
        api.async_configure_device_activations(
            enabled=True,
            auto_discover=False,
            items=[
                {
                    "id": "stair_light",
                    "name": "Stair light",
                    "type": "stair_light",
                    "addressMode": "manual",
                    "address": "22",
                }
            ],
        )
    )["maintenance_enabled"] is True
    assert asyncio.run(api.async_set_ipv6_firewall_enabled(True))["ipv6_firewall_enabled"] is True
    assert asyncio.run(api.async_set_firewall_enabled(True))["firewall_enabled"] is True
    assert asyncio.run(api.async_set_maintenance_no_auth_allowed(True))[
        "maintenance_no_auth_allowed"
    ] is True

    assert calls[0] == (
        "GET",
        "/api/v1/maintenance/auth",
        {"extra_headers": {HEADER_MAINTENANCE_TOKEN: "maintenance-token"}},
    )
    posted_payloads = [call[2]["json_data"] for call in calls[1:]]
    assert posted_payloads == [
        {
            "noAuth": True,
            "apiToken": "api",
            "maintenanceToken": "maint",
            "maintenanceNoAuthAllowed": True,
        },
        {"mdnsEnabled": False},
        {
            "activationsEnabled": True,
            "activationsAutoDiscover": False,
            "activationItemsJson": (
                '[{"id":"stair_light","name":"Stair light",'
                '"type":"stair_light","addressMode":"manual","address":"22"}]'
            ),
        },
        {"ipv6FirewallEnabled": True, "maintenanceEnabled": True},
        {"firewallEnabled": True, "maintenanceEnabled": True},
        {"maintenanceNoAuthAllowed": True, "maintenanceEnabled": True},
    ]


@pytest.mark.parametrize(
    ("method_name", "message"),
    [
        ("async_register_event_subscription", "event subscription"),
        ("async_display_bridge_status", "display bridge status"),
        ("async_notify_display_bridge_event", "display bridge event"),
        ("async_diagnostics", "diagnostics"),
    ],
)
def test_api_object_methods_reject_non_object_json(
    method_name: str,
    message: str,
) -> None:
    api = C300XAgentApi(
        _FakeSession(),  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    async def request_json(
        _method: str,
        _path: str,
        **_request_kwargs: object,
    ) -> list[str]:
        return ["not", "an", "object"]

    api._request_json = request_json  # type: ignore[method-assign]
    call_args: tuple[object, ...] = ()
    if method_name == "async_register_event_subscription":
        call_args = ("http://ha.local/api/webhook/events", "token", ["doorbell.pressed"])
    elif method_name == "async_notify_display_bridge_event":
        call_args = ("alarm",)

    with pytest.raises(C300XAgentApiResponseError, match=message):
        asyncio.run(getattr(api, method_name)(*call_args))


def test_api_delete_subscription_and_update_status_use_expected_headers() -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []
    api = C300XAgentApi(
        _FakeSession(),  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        "maintenance-token",
    )

    async def request_json(method: str, path: str, **request_kwargs: object) -> dict[str, object]:
        calls.append((method, path, request_kwargs))
        return {"ok": True}

    api._request_json = request_json  # type: ignore[method-assign]

    asyncio.run(api.async_delete_event_subscription("sub-1"))
    assert asyncio.run(api.async_agent_update_status()) == {"ok": True}

    assert calls == [
        ("DELETE", "/api/v1/events/subscriptions/sub-1", {}),
        (
            "GET",
            "/api/v1/maintenance/update/status",
            {"extra_headers": {HEADER_MAINTENANCE_TOKEN: "maintenance-token"}},
        ),
    ]


def test_byte_request_merges_extra_headers() -> None:
    session = _FakeSession(
        "",
        response_body=b"voice",
        content_type="audio/wav; charset=binary",
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    body, content_type = asyncio.run(
        api._request_bytes("GET", "/api/v1/test.bin", extra_headers={"X-Test": "1"})
    )

    assert body == b"voice"
    assert content_type == "audio/wav"
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
        "X-Test": "1",
    }


def test_api_update_upload_encodes_chunks_and_uses_long_timeout() -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []
    api = C300XAgentApi(
        _FakeSession(),  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        "maintenance-token",
        timeout=5,
    )

    async def request_json(method: str, path: str, **request_kwargs: object) -> dict[str, object]:
        calls.append((method, path, request_kwargs))
        return {"ok": True}

    api._request_json = request_json  # type: ignore[method-assign]

    asyncio.run(
        api.async_prepare_agent_update(bundle_hash="sha256:abc", agent_version="1.2.0")
    )
    asyncio.run(
        api.async_upload_agent_update_chunk(
            path="bin/agent",
            sha256="sha256:file",
            mode="0755",
            offset=3,
            data=b"abc",
            final=True,
        )
    )
    asyncio.run(api.async_apply_agent_update(bundle_hash="sha256:abc"))
    asyncio.run(api.async_normalize_agent_config())
    asyncio.run(api.async_ensure_homeassistant_user(account_label="Home Assistant Test"))

    assert calls[0][1] == "/api/v1/maintenance/update/prepare"
    assert calls[1][2]["json_data"] == {
        "path": "bin/agent",
        "sha256": "sha256:file",
        "mode": "0755",
        "offset": 3,
        "data": "YWJj",
        "final": True,
    }
    assert calls[1][2]["request_timeout"] == 20.0
    assert calls[2][2]["json_data"] == {
        "bundle_hash": "sha256:abc",
        "confirm": "update_agent",
    }
    assert calls[3][2]["json_data"] == {"confirm": "normalize_config"}
    assert calls[4][2]["json_data"] == {
        "confirm": "ensure_homeassistant_user",
        "account_label": "Home Assistant Test",
    }


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
                "last_block_reason": "external_session_active",
            },
        }
    )

    assert status["media_owner"] == "device_display"
    assert status["external_media_active"] is True
    assert status["external_owner"] == "device_display"
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


@pytest.mark.parametrize(
    "response_text",
    [
        "not json",
        "[]",
        '{"message": "   "}',
    ],
)
def test_agent_http_error_omits_unusable_detail(response_text: str) -> None:
    session = _FakeSession(response_text, response_status=500)
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    with pytest.raises(
        C300XAgentApiConnectionError,
        match="device agent returned HTTP 500$",
    ):
        asyncio.run(api.async_state())


def test_agent_http_error_compacts_long_detail() -> None:
    session = _FakeSession(
        '{"ok": false, "error": "'
        "very "
        + ("long " * 40)
        + 'error"}',
        response_status=500,
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    with pytest.raises(C300XAgentApiConnectionError) as err:
        asyncio.run(api.async_state())

    message = str(err.value)
    assert message.startswith("device agent returned HTTP 500: very long")
    assert message.endswith("...")
    assert "\n" not in message


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
        '"firewall_enabled": false, "ipv6_firewall_enabled": true, '
        '"activations_enabled": true, "activations_auto_discover": false}'
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
    assert status["activations_enabled"] is True
    assert status["activations_auto_discover"] is False
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


def test_configure_device_activations_sends_maintenance_update() -> None:
    session = _FakeSession(
        '{"ok": true, "activations_enabled": true, '
        '"activations_auto_discover": false}'
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    status = asyncio.run(
        api.async_configure_device_activations(
            enabled=True,
            auto_discover=False,
            items=[
                {
                    "id": "front_lock",
                    "name": "Front lock",
                    "type": "lock",
                    "addressMode": "manual",
                    "address": "10",
                }
            ],
        )
    )

    assert status["activations_enabled"] is True
    assert status["activations_auto_discover"] is False
    assert session.requests[0]["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/auth",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
        HEADER_MAINTENANCE_TOKEN: "maintenance-token",
    }
    assert session.requests[0]["kwargs"]["json"] == {
        "activationsEnabled": True,
        "activationsAutoDiscover": False,
        "activationItemsJson": (
            '[{"id":"front_lock","name":"Front lock","type":"lock",'
            '"addressMode":"manual","address":"10"}]'
        ),
    }


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


def test_restart_agent_sends_maintenance_token_and_confirmation() -> None:
    session = _FakeSession('{"ok": true, "action": "restart_agent"}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    assert asyncio.run(api.async_restart_agent())["action"] == "restart_agent"

    request = session.requests[0]
    assert request["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/agent/actions/restart",
    )
    assert request["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
        HEADER_MAINTENANCE_TOKEN: "maintenance-token",
    }
    assert request["kwargs"]["json"] == {"confirm": "restart_agent"}


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

    status = asyncio.run(api.async_firewall_status())

    assert isinstance(status, FirewallStatus)
    assert status["patched"] is True
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

    status = asyncio.run(api.async_ipv6_firewall_status())

    assert isinstance(status, FirewallStatus)
    assert status["family"] == "ipv6"
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
    assert request["kwargs"]["json"] == {
        "confirm": "apply_qml_patch",
        "dynamic_homepage": False,
    }


def test_apply_qml_patch_sends_dynamic_homepage_flag() -> None:
    session = _FakeSession('{"ok": true, "state": "patched"}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    assert (
        asyncio.run(api.async_apply_qml_patch(dynamic_homepage=True))["state"]
        == "patched"
    )
    request = session.requests[0]
    assert request["kwargs"]["json"] == {
        "confirm": "apply_qml_patch",
        "dynamic_homepage": True,
    }


def test_apply_qml_core_patch_sends_maintenance_confirmation() -> None:
    session = _FakeSession(
        '{"ok": true, "state": "original", "core_state": "patched", "core_patched": true}'
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    assert asyncio.run(api.async_apply_qml_core_patch())["core_patched"] is True
    request = session.requests[0]
    assert request["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/qml-patch/actions/apply-core",
    )
    assert request["kwargs"]["json"] == {"confirm": "apply_qml_core_patch"}


def test_restore_qml_core_patch_sends_maintenance_confirmation() -> None:
    session = _FakeSession(
        '{"ok": true, "state": "original", "core_state": "original", "core_patched": false}'
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    assert asyncio.run(api.async_restore_qml_core_patch())["core_patched"] is False
    request = session.requests[0]
    assert request["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/qml-patch/actions/restore-core",
    )
    assert request["kwargs"]["json"] == {"confirm": "restore_qml_core_patch"}


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
        '{"ok": true, "agent_write_count": 2, "last_write_class": "config", '
        '"last_write_reason": "updated", '
        '"last_wake_reason": "api", "open_fd_count": 7}'
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    status = asyncio.run(api.async_diagnostics())

    assert isinstance(status, AgentDiagnosticsStatus)
    assert status["agent_write_count"] == 2
    assert session.requests[0]["args"] == (
        "GET",
        "http://agent.local:8080/api/v1/diagnostics",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
    }


def test_device_user_status_requests_read_only_endpoint() -> None:
    session = _FakeSession(
        '{"ok": true, "supported": true, "homeassistant_user_present": true, '
        '"media_identity_available": true, '
        '"routes_consistent": false}'
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    status = asyncio.run(api.async_device_user_status())

    assert status["supported"] is True
    assert status["homeassistant_user_present"] is True
    assert status["media_identity_available"] is True
    assert status["routes_consistent"] is False
    assert session.requests[0]["args"] == (
        "GET",
        "http://agent.local:8080/api/v1/device-user",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
    }


def test_self_test_requests_read_only_endpoint() -> None:
    session = _FakeSession(
        '{"api_version":"1.1","agent_version":"1.2.0","firmware_family":"1.7.x",'
        '"ok":false,"checks":{"startup":{"ok":false,"reason":"startup_link_missing"}}}'
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    status = asyncio.run(api.async_self_test())

    assert isinstance(status, SelfTestStatus)
    assert status.ok is False
    assert status.checks["startup"].reason == "startup_link_missing"
    assert session.requests[0]["args"] == (
        "GET",
        "http://agent.local:8080/api/v1/self-test",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
    }
    assert session.requests[0]["kwargs"]["timeout"] == 2.0


def test_normalize_self_test_rejects_non_object() -> None:
    with pytest.raises(C300XAgentApiResponseError):
        normalize_self_test([])


def test_ensure_homeassistant_user_sends_maintenance_confirmation() -> None:
    session = _FakeSession(
        '{"ok": true, "supported": true, "homeassistant_user_present": true, '
        '"media_identity_available": true, "routes_consistent": true}'
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    status = asyncio.run(api.async_ensure_homeassistant_user())

    assert status["homeassistant_user_present"] is True
    assert status["routes_consistent"] is True
    assert session.requests[0]["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/maintenance/device-user/actions/ensure-homeassistant",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
        HEADER_MAINTENANCE_TOKEN: "maintenance-token",
    }
    assert session.requests[0]["kwargs"]["json"] == {
        "confirm": "ensure_homeassistant_user"
    }
    assert session.requests[0]["kwargs"]["timeout"] == 20.0


def test_ensure_homeassistant_user_can_send_account_label() -> None:
    session = _FakeSession(
        '{"ok": true, "supported": true, "homeassistant_user_present": true, '
        '"account_label": "Home Assistant Test", '
        '"media_identity_available": true, "routes_consistent": true}'
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
        maintenance_token="maintenance-token",
    )

    status = asyncio.run(
        api.async_ensure_homeassistant_user(account_label="Home Assistant Test")
    )

    assert status["account_label"] == "Home Assistant Test"
    assert session.requests[0]["kwargs"]["json"] == {
        "confirm": "ensure_homeassistant_user",
        "account_label": "Home Assistant Test",
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


def test_set_doorstation_audio_gain_requests_runtime_endpoint() -> None:
    session = _FakeSession('{"ok": true}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    assert asyncio.run(api.async_set_doorstation_audio_gain_db(6.0)) == {"ok": True}
    assert session.requests[0]["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/video/doorbell/audio",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
    }
    assert session.requests[0]["kwargs"]["json"] == {"doorstation_audio_gain_tenths": 60}


def test_activate_doorbell_video_accepts_active_ring_conflict() -> None:
    session = _QueuedSession(
        [
            (
                409,
                '{"ok": false, "error": "external_session_active"}',
            ),
            (
                200,
                '{"available": true, "window_available": false, '
                '"stream_path": "/doorbell-video", "audio_stream_path": "/doorbell", '
                '"bridge": {"media_owner": "ring", "ring_call_active": true, '
                '"ring_media_active": false}}',
            ),
        ]
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    response = asyncio.run(api.async_activate_doorbell_video(audio=True))

    assert response["ok"] is True
    assert response["ring_active"] is True
    assert response["status"]["window_available"] is False
    assert session.requests[0]["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/video/doorbell/actions/activate",
    )
    assert session.requests[1]["args"] == (
        "GET",
        "http://agent.local:8080/api/v1/video/doorbell/status",
    )


def test_activate_doorbell_video_reraises_unrelated_conflict() -> None:
    session = _FakeSession(
        '{"ok": false, "error": "busy"}',
        response_status=409,
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    with pytest.raises(C300XAgentApiConnectionError, match="busy"):
        asyncio.run(api.async_activate_doorbell_video(audio=False))


def test_activate_doorbell_video_reraises_external_conflict_without_ring() -> None:
    session = _QueuedSession(
        [
            (
                409,
                '{"ok": false, "error": "external_session_active"}',
            ),
            (
                200,
                '{"available": true, "window_available": false, '
                '"stream_path": "/doorbell-video", '
                '"bridge": {"media_owner": "device_display"}}',
            ),
        ]
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    with pytest.raises(C300XAgentApiConnectionError, match="external_session_active"):
        asyncio.run(api.async_activate_doorbell_video(audio=True))


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

    status = asyncio.run(api.async_doorbell_video_status())

    assert isinstance(status, DoorbellVideoStatus)
    assert status["stream_path"] == "/doorbell-video"
    assert session.requests[0]["args"] == (
        "GET",
        "http://agent.local:8080/api/v1/video/doorbell/status",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
    }


def test_doorbell_video_status_does_not_fallback_to_legacy_state() -> None:
    session = _QueuedSession(
        [
            (404, '{"error": "not_found"}'),
            (
                200,
                '{"state": {"video_available": true, "video_stream_path": "/legacy"}}',
            ),
        ]
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    with pytest.raises(C300XAgentApiUnsupportedError):
        asyncio.run(api.async_doorbell_video_status())

    assert [request["args"] for request in session.requests] == [
        ("GET", "http://agent.local:8080/api/v1/video/doorbell/status"),
    ]


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


def test_doorbell_call_status_requests_authenticated_endpoint() -> None:
    session = _FakeSession(
        '{"ok": true, "supported": true, "active": true, '
        '"early_media_active": true, "audio_active": false, '
        '"answer_requested": false, "answered": false, "can_answer": true, '
        '"can_hangup": true, "media_owner": "ring", '
        '"ring_receiver_running": true, "ring_registered": true, '
        '"capture_supported": false, "open_fds": 5, "active_threads": 2}'
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    status = asyncio.run(api.async_doorbell_call_status())

    assert isinstance(status, RingCallStatus)
    assert status["active"] is True
    assert status["can_answer"] is True
    assert status["capture_supported"] is False
    assert status["open_fds"] == 5
    assert session.requests[0]["args"] == (
        "GET",
        "http://agent.local:8080/api/v1/calls/doorbell/status",
    )


def test_answer_doorbell_call_requests_authenticated_endpoint() -> None:
    session = _FakeSession('{"ok": true, "audio": true, "answer_requested": true}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    assert asyncio.run(api.async_answer_doorbell_call()) == {
        "ok": True,
        "audio": True,
        "answer_requested": True,
    }
    assert session.requests[0]["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/calls/doorbell/actions/answer",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
    }
    assert session.requests[0]["kwargs"]["json"] is None


def test_hangup_doorbell_call_requests_authenticated_endpoint() -> None:
    session = _FakeSession('{"ok": true}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    assert asyncio.run(api.async_hangup_doorbell_call()) == {"ok": True}
    assert session.requests[0]["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/calls/doorbell/actions/hangup",
    )


def test_capture_doorbell_call_requests_authenticated_endpoint() -> None:
    session = _FakeSession('{"ok": true, "path": "/tmp/capture.jpg"}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    assert asyncio.run(api.async_capture_doorbell_call()) == {
        "ok": True,
        "path": "/tmp/capture.jpg",
    }
    assert session.requests[0]["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/calls/doorbell/actions/capture",
    )


def test_normalize_doorbell_call_rejects_non_object() -> None:
    with pytest.raises(C300XAgentApiResponseError):
        normalize_doorbell_call([])


def test_home_call_status_requests_authenticated_endpoint() -> None:
    session = _FakeSession(
        '{"ok": true, "available": true, "running": true, "active": true, '
        '"answered": true, "rtp_proxy": true, "target_audio_port": 41528, '
        '"rtp_packets": 3, "rtcp_packets": 1}'
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    status = asyncio.run(api.async_home_call_status())

    assert isinstance(status, HomeCallStatus)
    assert status["target_audio_port"] == 41528
    assert session.requests[0]["args"] == (
        "GET",
        "http://agent.local:8080/api/v1/calls/home/status",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
    }


def test_start_home_call_requests_authenticated_endpoint() -> None:
    session = _FakeSession('{"ok": true, "duration_seconds": 30}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    assert asyncio.run(api.async_start_home_call(duration_seconds=30)) == {
        "ok": True,
        "duration_seconds": 30,
    }
    assert session.requests[0]["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/calls/home/actions/start",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
    }
    assert session.requests[0]["kwargs"]["json"] == {"duration_seconds": 30}


def test_stop_home_call_requests_authenticated_endpoint() -> None:
    session = _FakeSession('{"ok": true}')
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    assert asyncio.run(api.async_stop_home_call()) == {"ok": True}
    assert session.requests[0]["args"] == (
        "POST",
        "http://agent.local:8080/api/v1/calls/home/actions/stop",
    )
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "Bearer agent-token",
    }


def test_normalize_ssh_status_accepts_running_flag() -> None:
    assert normalize_ssh_status({"running": "true"})["running"] is True
    assert normalize_ssh_status({"enabled": False})["running"] is False
    assert normalize_ssh_status({"running": "disabled"})["running"] is False
    assert normalize_ssh_status({"running": "maybe"}) == {
        "running": None,
        "enabled": None,
        "raw": {"running": "maybe"},
    }
    assert normalize_ssh_status({"raw": "missing"}) == {
        "running": None,
        "enabled": None,
        "raw": {"raw": "missing"},
    }


def test_normalize_qml_patch_status_derives_state() -> None:
    assert normalize_qml_patch_status({"patched": True}) == {
        "available": True,
        "patched": True,
        "state": "patched",
        "core_patched": None,
        "core_state": None,
        "backup_available": None,
        "core_backup_available": None,
        "gui_running": None,
        "raw": {"patched": True},
    }
    assert normalize_qml_patch_status({"state": "original"})["patched"] is False
    assert normalize_qml_patch_status({"state": "applied"})["patched"] is True
    assert normalize_qml_patch_status({"state": "restored"})["patched"] is False
    assert normalize_qml_patch_status({"patched": False})["state"] == "original"
    assert normalize_qml_patch_status({})["state"] == "unknown"
    detailed = normalize_qml_patch_status(
        {
            "state": "patched",
            "core_patched": "yes",
            "backup_available": "no",
            "core_backup_available": "bad",
            "gui_running": "enabled",
        }
    )
    assert detailed["core_patched"] is True
    assert detailed["backup_available"] is False
    assert detailed["core_backup_available"] is None
    assert detailed["gui_running"] is True
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
        "rtsp_port": None,
        "talkback_rtp_port": None,
        "media_ports_enabled": None,
        "changed_files": None,
        "raw": {"state": "patched", "api_port": "8091"},
    }
    assert normalize_firewall_status({"state": "missing"})["patched"] is False
    assert normalize_firewall_status({"state": "partial"})["patched"] is None
    assert normalize_firewall_status({"api_port": "bad"})["api_port"] is None


def test_normalize_auth_config_status_accepts_camel_case_no_auth() -> None:
    assert normalize_auth_config_status({"noAuth": True})["no_auth"] is True


def test_normalize_auth_config_status_accepts_snake_case_no_auth() -> None:
    assert normalize_auth_config_status({"no_auth": True})["no_auth"] is True


def test_normalize_device_user_status_is_non_sensitive() -> None:
    raw = {
        "ok": True,
        "supported": True,
        "device_domain": "private-device.example.invalid",
        "homeassistant_aor": "homeassistant-private@private-device.example.invalid",
        "route_int": "<sip:alluser@private-device.example.invalid> <sip:private>",
        "digest": "0123456789abcdef0123456789abcdef",
        "domain_present": True,
        "homeassistant_user_present": True,
        "accounts_homeassistant_present": True,
        "route_int_homeassistant_present": True,
        "route_ext_homeassistant_present": False,
        "route_conf_homeassistant_present": False,
        "route_conf_is_symlink": True,
        "writable_files_present": True,
        "media_identity_available": True,
        "routes_consistent": True,
        "device_routing_supported": True,
        "device_routing_applied": True,
        "device_routing_state": "patched",
        "device_routing_backup_present": True,
        "device_routing_error": "",
        "media_user_label_available": True,
        "media_user_label_applied": True,
        "media_user_label_state": "patched",
        "account_label": "Home Assistant Test",
        "error": "",
    }

    status = normalize_device_user_status(raw)

    assert status == {
        "available": True,
        "supported": True,
        "domain_present": True,
        "homeassistant_user_present": True,
        "accounts_homeassistant_present": True,
        "route_int_homeassistant_present": True,
        "route_ext_homeassistant_present": False,
        "route_conf_homeassistant_present": False,
        "route_conf_is_symlink": True,
        "writable_files_present": True,
        "media_identity_available": True,
        "routes_consistent": True,
        "device_routing_supported": True,
        "device_routing_applied": True,
        "device_routing_state": "patched",
        "device_routing_backup_present": True,
        "device_routing_error": None,
        "media_user_label_available": True,
        "media_user_label_applied": True,
        "media_user_label_state": "patched",
        "account_label": "Home Assistant Test",
        "error": None,
        "raw": {
            "ok": True,
            "supported": True,
            "domain_present": True,
            "homeassistant_user_present": True,
            "accounts_homeassistant_present": True,
            "route_int_homeassistant_present": True,
            "route_ext_homeassistant_present": False,
            "route_conf_homeassistant_present": False,
            "route_conf_is_symlink": True,
            "writable_files_present": True,
            "media_identity_available": True,
            "routes_consistent": True,
            "device_routing_supported": True,
            "device_routing_applied": True,
            "device_routing_state": "patched",
            "device_routing_backup_present": True,
            "device_routing_error": "",
            "media_user_label_available": True,
            "media_user_label_applied": True,
            "media_user_label_state": "patched",
            "error": "",
        },
    }
    assert "device_domain" not in status["raw"]
    assert "homeassistant_aor" not in status["raw"]
    assert "route_int" not in status["raw"]
    assert "digest" not in status["raw"]


def test_normalize_device_user_status_keeps_unavailable_unknown() -> None:
    status = normalize_device_user_status(
        {
            "ok": False,
            "status_available": False,
            "supported": True,
            "homeassistant_user_present": False,
            "media_identity_available": False,
            "routes_consistent": False,
            "error": "status_failed",
        }
    )

    assert status["available"] is False
    assert status["supported"] is True
    assert status["homeassistant_user_present"] is None
    assert status["media_identity_available"] is None
    assert status["routes_consistent"] is None
    assert status["error"] == "status_failed"


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


@pytest.mark.parametrize(
    ("normalizer", "message"),
    [
        (normalize_doorbell_video, "doorbell video"),
        (normalize_doorbell_call, "doorbell call"),
        (normalize_home_call, "home call"),
        (normalize_activations, "activations"),
        (normalize_system_metrics, "system metrics"),
        (normalize_agent_diagnostics, "diagnostics"),
        (normalize_device_user_status, "device user status"),
        (normalize_auth_config_status, "auth config"),
        (normalize_ssh_status, "SSH status"),
        (normalize_qml_patch_status, "Display patch status"),
        (normalize_firewall_status, "firewall status"),
        (normalize_mqtt_status, "MQTT status"),
        (normalize_legacy_mqtt_status, "legacy MQTT status"),
        (normalize_smartphone_forwarding, "smartphone-forwarding"),
        (normalize_ringer, "ringer"),
        (normalize_answering_machine, "answering-machine"),
        (normalize_answering_machine_messages, "answering-machine messages"),
        (normalize_memos, "memos"),
    ],
)
def test_normalizers_reject_non_object_payloads(
    normalizer: Callable[[object], object],
    message: str,
) -> None:
    with pytest.raises(C300XAgentApiResponseError, match=message):
        normalizer([])


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


def test_normalize_smartphone_forwarding_mode_accepts_known_values() -> None:
    assert normalize_smartphone_forwarding_mode(" Enabled ") == "enabled"


def test_smartphone_forwarding_status_falls_back_to_state_endpoint() -> None:
    session = _QueuedSession(
        [
            (404, '{"error": "not_found"}'),
            (200, '{"state": {"smartphone_forwarding": "enabled"}}'),
        ]
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    assert asyncio.run(api.async_smartphone_forwarding_status())["state"] == "enabled"
    assert [request["args"] for request in session.requests] == [
        ("GET", "http://agent.local:8080/api/v1/smartphone-forwarding"),
        ("GET", "http://agent.local:8080/api/v1/state"),
    ]


def test_state_returns_empty_dict_for_non_object_agent_state() -> None:
    session = _FakeSession("[]")
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    assert asyncio.run(api.async_state()) == {}
    assert session.requests[0]["args"] == (
        "GET",
        "http://agent.local:8080/api/v1/state",
    )


def test_ringer_status_falls_back_to_state_endpoint() -> None:
    session = _QueuedSession(
        [
            (500, '{"error": "ringer_unavailable"}'),
            (200, '{"state": {"ringer_muted": true, "ringer_volume": 3}}'),
        ]
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    status = asyncio.run(api.async_ringer_status())
    assert status["muted"] is True
    assert status["volume"] == 3
    assert [request["args"] for request in session.requests] == [
        ("GET", "http://agent.local:8080/api/v1/ringer"),
        ("GET", "http://agent.local:8080/api/v1/state"),
    ]


def test_answering_machine_status_falls_back_to_state_endpoint() -> None:
    session = _QueuedSession(
        [
            (500, '{"error": "answering_machine_unavailable"}'),
            (200, '{"state": {"answering_machine_enabled": false}}'),
        ]
    )
    api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )

    assert asyncio.run(api.async_answering_machine_status())["enabled"] is False
    assert [request["args"] for request in session.requests] == [
        ("GET", "http://agent.local:8080/api/v1/answering-machine"),
        ("GET", "http://agent.local:8080/api/v1/state"),
    ]


def test_ringer_and_answering_machine_setters_post_payloads() -> None:
    api = C300XAgentApi(
        _FakeSession(),  # type: ignore[arg-type]
        "http://agent.local:8080",
        "agent-token",
    )
    calls: list[tuple[str, str, dict[str, object]]] = []

    async def request_json(
        method: str,
        path: str,
        **request_kwargs: object,
    ) -> dict[str, object]:
        calls.append((method, path, request_kwargs))
        if path == "/api/v1/ringer":
            payload = request_kwargs["json_data"]  # type: ignore[index]
            return {
                key: payload[key]  # type: ignore[index]
                for key in ("muted", "volume")
                if key in payload
            }
        return {"enabled": request_kwargs["json_data"]["enabled"]}  # type: ignore[index]

    api._request_json = request_json  # type: ignore[method-assign]

    assert asyncio.run(api.async_set_ringer_muted(True))["muted"] is True
    assert asyncio.run(api.async_set_ringer_volume(3))["volume"] == 3
    assert asyncio.run(api.async_set_answering_machine_enabled(False))[
        "enabled"
    ] is False
    assert calls == [
        ("POST", "/api/v1/ringer", {"json_data": {"muted": True}}),
        ("POST", "/api/v1/ringer", {"json_data": {"volume": 3}}),
        ("POST", "/api/v1/answering-machine", {"json_data": {"enabled": False}}),
    ]


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
                [],
                {"id": "scene_1", "name": "", "type": "scenario", "executable": True},
                {"id": "broken/path", "name": "Broken", "executable": True},
                {
                    "id": "unknown",
                    "name": "Unknown",
                    "type": "bad",
                    "addressMode": "bad",
                },
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
                [],
                {"id": "scene_1", "name": "", "type": "scenario", "executable": True},
                {"id": "broken/path", "name": "Broken", "executable": True},
                {
                    "id": "unknown",
                    "name": "Unknown",
                    "type": "bad",
                    "addressMode": "bad",
                },
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
                "audio_codec": "PCMU/8000",
                "talkback_supported": True,
                "talkback_payload_type": 97,
            },
        }
    ) == {
        "available": True,
        "window_available": False,
        "stream_path": "/doorbell-video",
        "audio_stream_path": "/doorbell",
        "recorder_stream_path": "/doorbell-recorder",
        "media_owner": "unknown",
        "external_media_active": False,
        "external_owner": None,
        "last_block_reason": None,
        "bridge": {
            "enabled": True,
            "running": True,
            "audio_codec": "PCMU/8000",
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
                "audio_codec": "PCMU/8000",
                "talkback_supported": True,
                "talkback_payload_type": 97,
            },
        },
    }


def test_normalize_doorbell_video_trusts_agent_window_available_field() -> None:
    status = normalize_doorbell_video(
        {
            "available": True,
            "window_available": False,
            "stream_path": "/doorbell-video",
            "audio_stream_path": "/doorbell",
            "bridge": {
                "media_owner": "ring",
                "ring_call_active": True,
                "ring_media_active": False,
            },
        }
    )

    assert status["window_available"] is False
    assert status["media_owner"] == "ring"


def test_normalize_home_call_from_agent_status() -> None:
    assert normalize_home_call(
        {
            "available": True,
            "running": True,
            "active": True,
            "answered": True,
            "rtp_proxy": True,
            "target_audio_port": 41528,
            "rtp_packets": 5,
            "rtcp_packets": 2,
            "max_duration_seconds": 3600,
            "last_error": None,
        }
    ) == {
        "available": True,
        "running": True,
        "active": True,
        "answered": True,
        "rtp_proxy": True,
        "target_audio_port": 41528,
        "rtp_packets": 5,
        "rtcp_packets": 2,
        "max_duration_seconds": 3600,
        "last_error": None,
        "raw": {
            "available": True,
            "running": True,
            "active": True,
            "answered": True,
            "rtp_proxy": True,
            "target_audio_port": 41528,
            "rtp_packets": 5,
            "rtcp_packets": 2,
            "max_duration_seconds": 3600,
            "last_error": None,
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
            "last_write_class": "config",
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
            "ui_event_waiters": "2",
            "ui_event_waiter_capacity": "4",
            "ui_event_waiter_overflows": "1",
            "video_running": True,
            "video_rtsp_server_running": True,
            "video_media_starting": False,
            "video_call_active": True,
            "video_clients": "1",
            "video_bridge_running": True,
            "video_bridge_media_active": True,
            "video_bridge_stop_in_progress": False,
            "video_bridge_open_fds": "5",
            "video_bridge_active_threads": "2",
            "ring_receiver_running": True,
            "ring_registered": True,
            "ring_call_active": False,
            "ring_media_active": False,
            "home_call_running": False,
            "home_call_active": False,
            "flexisip_backup_available": True,
            "flexisip_restart_marker": False,
            "flexisip_backup_marker": True,
            "flexisip_reference_state": "original",
        }
    )

    assert normalized["agent_write_count"] == 2
    assert normalized["last_write_at"] == 1770000000
    assert normalized["last_write_reason"] == "updated"
    assert normalized["last_write_class"] == "config"
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
    assert normalized["ui_event_waiters"] == 2
    assert normalized["ui_event_waiter_capacity"] == 4
    assert normalized["ui_event_waiter_overflows"] == 1
    assert normalized["video_running"] is True
    assert normalized["video_rtsp_server_running"] is True
    assert normalized["video_media_starting"] is False
    assert normalized["video_call_active"] is True
    assert normalized["video_clients"] == 1
    assert normalized["video_bridge_running"] is True
    assert normalized["video_bridge_media_active"] is True
    assert normalized["video_bridge_stop_in_progress"] is False
    assert normalized["video_bridge_open_fds"] == 5
    assert normalized["video_bridge_active_threads"] == 2
    assert normalized["ring_receiver_running"] is True
    assert normalized["ring_registered"] is True
    assert normalized["ring_call_active"] is False
    assert normalized["ring_media_active"] is False
    assert normalized["home_call_running"] is False
    assert normalized["home_call_active"] is False
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
        {"state": {"smartphone_forwarding": "homeassistant"}}
    ) == {
        "mode": 1,
        "state": "homeassistant",
        "raw": {"state": {"smartphone_forwarding": "homeassistant"}},
    }


def test_normalize_smartphone_forwarding_from_numeric_agent_state() -> None:
    assert normalize_smartphone_forwarding({"state": {"smartphone_forwarding": 2}}) == {
        "mode": 2,
        "state": "blocked",
        "raw": {"state": {"smartphone_forwarding": 2}},
    }


def test_normalize_smartphone_forwarding_from_unprovisioned_agent_state() -> None:
    assert normalize_smartphone_forwarding({"state": {"smartphone_forwarding": 3}}) == {
        "mode": 3,
        "state": "unprovisioned",
        "raw": {"state": {"smartphone_forwarding": 3}},
    }


def test_normalize_smartphone_forwarding_handles_missing_agent_state() -> None:
    assert normalize_smartphone_forwarding({"state": {}}) == {
        "mode": None,
        "state": "unknown",
        "raw": {"state": {}},
    }


def test_normalize_smartphone_forwarding_accepts_legacy_enabled_flag() -> None:
    assert normalize_smartphone_forwarding({"enabled": False, "raw": "legacy"}) == {
        "mode": 2,
        "state": "blocked",
        "raw": "legacy",
    }


def test_normalize_smartphone_forwarding_from_agent_command_response() -> None:
    assert normalize_smartphone_forwarding({"mode": "blocked", "raw": "*x##"}) == {
        "mode": 2,
        "state": "blocked",
        "raw": "*x##",
    }


def test_normalize_smartphone_forwarding_from_unprovisioned_agent_response() -> None:
    assert normalize_smartphone_forwarding(
        {"mode": "unprovisioned", "raw": "*#8**37*3##"}
    ) == {
        "mode": 3,
        "state": "unprovisioned",
        "raw": "*#8**37*3##",
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
    with pytest.raises(C300XAgentApiResponseError):
        normalize_smartphone_forwarding_mode("unprovisioned")


def test_normalize_smartphone_forwarding_rejects_missing_mode() -> None:
    with pytest.raises(C300XAgentApiResponseError):
        normalize_smartphone_forwarding({})


def test_normalize_ringer_from_agent_state() -> None:
    assert normalize_ringer({"state": {"ringer_muted": True, "ringer_volume": 10}}) == {
        "muted": True,
        "volume": 10,
        "raw": {"state": {"ringer_muted": True, "ringer_volume": 10}},
    }


def test_normalize_ringer_from_command_response() -> None:
    assert normalize_ringer(
        {"muted": False, "volume": "5", "raw": "*#8**33*1##"}
    ) == {
        "muted": False,
        "volume": 5,
        "raw": "*#8**33*1##",
    }


def test_normalize_ringer_accepts_string_state() -> None:
    assert normalize_ringer({"state": {"ringer_muted": "off"}}) == {
        "muted": False,
        "raw": {"state": {"ringer_muted": "off"}},
    }
    assert normalize_ringer({"muted": "muted"}) == {
        "muted": True,
        "raw": {"muted": "muted"},
    }


def test_normalize_ringer_accepts_unknown_state() -> None:
    assert normalize_ringer({"muted": None, "volume": "not-a-volume", "raw": "state"}) == {
        "muted": None,
        "volume": None,
        "raw": "state",
    }


def test_normalize_ringer_rejects_volume_outside_device_scale() -> None:
    assert normalize_ringer({"muted": False, "volume": 11}) == {
        "muted": False,
        "volume": None,
        "raw": {"muted": False, "volume": 11},
    }


def test_normalize_ringer_treats_unknown_string_as_boolean() -> None:
    assert normalize_ringer({"muted": "unknown"}) == {
        "muted": True,
        "raw": {"muted": "unknown"},
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
    assert normalize_answering_machine({"enabled": "disabled"}) == {
        "enabled": False,
        "greeting_message_enabled": None,
        "status_fields": [],
        "raw": {"enabled": "disabled"},
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


def test_normalize_answering_machine_accepts_unknown_state() -> None:
    assert normalize_answering_machine({"enabled": None}) == {
        "enabled": None,
        "greeting_message_enabled": None,
        "status_fields": [],
        "raw": {"enabled": None},
    }


def test_normalize_answering_machine_treats_unknown_string_as_boolean() -> None:
    assert normalize_answering_machine({"enabled": "unknown"}) == {
        "enabled": True,
        "greeting_message_enabled": None,
        "status_fields": [],
        "raw": {"enabled": "unknown"},
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


def test_normalize_answering_machine_messages_drops_invalid_entries() -> None:
    assert normalize_answering_machine_messages(
        {"messages": [[], {"id": ""}, {"id": "message_1"}]}
    ) == {
        "available": True,
        "total": 1,
        "unread": 0,
        "read": 0,
        "newest_at": None,
        "messages": [
            {
                "id": "message_1",
                "read": None,
                "date": None,
                "unix_time": None,
                "iso_time": None,
                "has_thumbnail": False,
                "has_video": False,
                "media_mime_type": None,
                "media_size": None,
            }
        ],
        "raw": {"messages": [[], {"id": ""}, {"id": "message_1"}]},
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


def test_normalize_memos_drops_invalid_entries_and_counts_remaining() -> None:
    assert normalize_memos(
        {
            "memos": [
                [],
                {"id": "", "kind": "text"},
                {"id": "video/memo_1", "kind": "video"},
                {"id": "text/memo_1", "kind": "text"},
            ]
        }
    ) == {
        "available": True,
        "total": 1,
        "text_total": 1,
        "voice_total": 0,
        "unread": 0,
        "read": 0,
        "newest_at": None,
        "memos": [
            {
                "id": "text/memo_1",
                "kind": "text",
                "read": None,
                "date": None,
                "unix_time": None,
                "iso_time": None,
                "has_text": False,
                "has_audio": False,
                "audio_mime_type": None,
                "audio_size": None,
                "text": None,
                "text_truncated": False,
            }
        ],
        "raw": {
            "memos": [
                [],
                {"id": "", "kind": "text"},
                {"id": "video/memo_1", "kind": "video"},
                {"id": "text/memo_1", "kind": "text"},
            ]
        },
    }
