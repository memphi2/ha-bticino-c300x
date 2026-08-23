from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
import sys
import types
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

if "homeassistant.config_entries" not in sys.modules:
    homeassistant = sys.modules.setdefault(
        "homeassistant",
        types.ModuleType("homeassistant"),
    )
    config_entries = types.ModuleType("homeassistant.config_entries")
    core = types.ModuleType("homeassistant.core")
    helpers = sys.modules.setdefault(
        "homeassistant.helpers",
        types.ModuleType("homeassistant.helpers"),
    )
    config_validation = types.ModuleType("homeassistant.helpers.config_validation")
    dispatcher = types.ModuleType("homeassistant.helpers.dispatcher")
    entity = types.ModuleType("homeassistant.helpers.entity")

    class ConfigEntry:  # pragma: no cover - import-time stub only
        pass

    class HomeAssistant:  # pragma: no cover - import-time stub only
        pass

    class Entity:  # pragma: no cover - import-time stub only
        pass

    class DeviceInfo(dict):  # pragma: no cover - import-time stub only
        pass

    config_entries.ConfigEntry = ConfigEntry
    core.HomeAssistant = HomeAssistant
    core.callback = lambda func: func
    config_validation.config_entry_only_config_schema = lambda _domain: dict
    dispatcher.async_dispatcher_connect = lambda *args, **kwargs: lambda: None
    entity.Entity = Entity
    entity.DeviceInfo = DeviceInfo
    homeassistant.config_entries = config_entries
    homeassistant.core = core
    homeassistant.helpers = helpers
    helpers.config_validation = config_validation
    helpers.dispatcher = dispatcher
    helpers.entity = entity
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers.config_validation"] = config_validation
    sys.modules["homeassistant.helpers.dispatcher"] = dispatcher
    sys.modules["homeassistant.helpers.entity"] = entity

from custom_components.bticino_c300x.const import (
    CONF_ACTIONS,
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_ALARM_ENTITY_ID,
    CONF_CALLBACK_BASE_URL,
    CONF_DASHBOARD_ENTITIES,
    CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P,
    CONF_EVENT_WEBHOOK_ID,
    CONF_MAINTENANCE_TOKEN,
    CONF_SHARED_SECRET,
    CONF_VIDEO_ENABLED,
    CONF_VIDEO_PORT,
    CONF_VIDEO_STREAM_PATH,
    CONF_WEATHER_ENTITY_ID,
    CONF_WEBHOOK_ID,
)
from custom_components.bticino_c300x.data import (
    C300XCallbackDiagnostics,
    C300XConnectionState,
    C300XEventState,
    C300XOperationDiagnostics,
)
from custom_components.bticino_c300x.diagnostics import (
    _agent_info_diagnostics,
    _agent_write_diagnostics,
    _async_installer_bundle_status,
    _async_network_diagnostics,
    _async_video_bridge_diagnostics,
    _capability_diagnostics,
    _connection_diagnostics,
    _device_user_diagnostics,
    _entity_domain_counts,
    _event_state_diagnostics,
    _host_private_address,
    _isoformat,
    _media_readiness_diagnostics,
    _media_user_setup_entity_diagnostics,
    _redact_error_message,
    _route_diagnostics,
    _safe_error_summary,
    _safe_status_dict,
    _safe_system_metrics,
    _same_lan_prefix_guess,
    _self_test_diagnostics,
    _sequence_count,
    async_get_config_entry_diagnostics,
)
from custom_components.bticino_c300x.media_timeline import C300XMediaTimeline


@dataclass
class _FakeEntry:
    title: str = "Private door station"
    entry_id: str = "entry-private-id"
    version: int = 1
    minor_version: int = 2
    disabled_by: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    runtime_data: Any | None = None


class _FakeHass:
    async def async_add_executor_job(self, func: Any, *args: Any) -> dict[str, Any]:
        if getattr(func, "__name__", "") != "_route_diagnostics":
            return func(*args)
        return {
            "resolved": True,
            "selected_source_type": "ipv4",
            "selected_target_type": "ipv4",
            "same_lan_prefix_guess": True,
            "error": None,
        }


def test_config_entry_diagnostics_explain_setup_without_private_values() -> None:
    connection_state = C300XConnectionState()
    connection_state.mark_reconnecting(
        "setup_probe",
        30,
        "ClientConnectorError: http://192.0.2.60:8091/api/v1/capabilities failed",
    )
    connection_state.mark_event_subscription_attempt(
        "http://192.0.2.10:8123/api/webhook/private-webhook",
        3,
        datetime(2026, 6, 2, tzinfo=UTC),
    )
    connection_state.mark_event_subscription_success(
        "private-subscription-id",
        3,
        "http://192.0.2.10:8123/api/webhook/private-webhook",
        datetime(2026, 6, 2, tzinfo=UTC),
    )
    event_state = C300XEventState(
        video_available=True,
        last_event="doorbell.pressed",
        last_event_time="2026-06-02T12:00:00+00:00",
        event_sequence=7,
    )
    runtime_data = SimpleNamespace(
        loaded_platforms=("sensor", "switch"),
        connection_state=connection_state,
        event_state=event_state,
        agent_info={
            "version": "0.3.4",
            "implementation": "native-c",
            "api_version": "1",
            "model": "C300X",
            "firmware": "1.7.19",
            "device_id": "c300x-private-device-id",
        },
        capabilities={
            "doorbell_events": True,
            "maintenance": {"supported": True, "reboot": True},
        },
        agent_update_state=SimpleNamespace(
            state="up_to_date",
            reason="bticino_c300x",
            update_required=False,
            repair_fixable=False,
            self_update_supported=True,
            installed_version="0.3.4",
            available_version="0.3.4",
            installed_api_version="1",
            available_api_version="1",
            installed_bundle_hash="sha256:installed",
            available_bundle_hash="sha256:installed",
        ),
        qml_patch_status={
            "available": True,
            "state": "patched",
            "patched": True,
            "script_path": "/home/bticino/private/qml_patch.sh",
            "token": "private-token",
            "raw": {"path": "/home/bticino/private"},
        },
        system_metrics={
            "cpu_count": 2,
            "cpu_usage_percent": 3.5,
            "memory_total_kb": 262144,
            "memory_available_kb": 151978,
            "memory_used_kb": 110166,
            "memory_usage_percent": 42.0,
            "temperature_c": 41.2,
        },
        system_metrics_updated_at=datetime(2026, 6, 2, tzinfo=UTC),
        answering_machine_messages={"messages": [{"id": "private-video"}]},
        answering_machine_messages_updated_at=datetime(2026, 6, 2, tzinfo=UTC),
        memos={"text": [{"id": "private-text"}], "voice": []},
        memos_updated_at=datetime(2026, 6, 2, tzinfo=UTC),
        agent_diagnostics={
            "agent_write_count": 2,
            "last_write_class": "config",
            "last_write_reason": "updated",
            "raw": {"token": "private-token"},
        },
        agent_diagnostics_updated_at=datetime(2026, 6, 2, tzinfo=UTC),
        device_user_status={
            "available": True,
            "supported": True,
            "domain_present": True,
            "homeassistant_user_present": False,
            "media_identity_available": False,
            "account_label": "Private Home Label",
        },
        device_user_status_updated_at=datetime(2026, 6, 2, tzinfo=UTC),
        self_test_status={
            "ok": False,
            "checks": {
                "homeassistant_user": {
                    "ok": False,
                    "reason": "media_identity_missing",
                    "details": {"users_file": "/home/bticino/cfg/private-users"},
                }
            },
        },
        self_test_status_updated_at=datetime(2026, 6, 2, tzinfo=UTC),
        media_timeline=C300XMediaTimeline(),
    )
    runtime_data.media_timeline.record(
        kind="webrtc",
        event="session_prepared",
        media_state="on_demand_active",
        owner="doorbell",
        session_count=1,
        ring_preview_sessions=0,
        ready_sessions=0,
        details={
            "provider": "go2rtc",
            "stream_url": "rtsp://192.0.2.60:6554/private-stream",
            "wants_audio": True,
        },
        now=datetime(2026, 6, 2, tzinfo=UTC),
    )
    entry = _FakeEntry(
        data={
            CONF_AGENT_HOST: "192.0.2.60",
            CONF_AGENT_PORT: 8091,
            CONF_AGENT_TOKEN: "private-agent-token",
            CONF_MAINTENANCE_TOKEN: "private-maintenance-token",
            CONF_WEBHOOK_ID: "private-webhook-id",
            CONF_EVENT_WEBHOOK_ID: "private-event-webhook-id",
            CONF_SHARED_SECRET: "private-shared-secret",
            CONF_CALLBACK_BASE_URL: "http://192.0.2.10:8123",
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P: "07",
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N: "07",
            CONF_VIDEO_ENABLED: True,
            CONF_VIDEO_PORT: 6554,
            CONF_VIDEO_STREAM_PATH: "/private-stream",
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.private_alarm",
            CONF_WEATHER_ENTITY_ID: "weather.private_home",
        },
        options={
            CONF_ACTIONS: {
                "private-action": {
                    "service": "button.press",
                    "target": {"entity_id": "button.private_button"},
                }
            },
            CONF_DASHBOARD_ENTITIES: [
                "switch.private_switch",
                "sensor.private_temperature",
            ],
            CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: {
                "sensor.private_temperature": {"secondary": "none"},
            },
        },
        runtime_data=runtime_data,
    )

    diagnostics = asyncio.run(
        async_get_config_entry_diagnostics(_FakeHass(), entry)  # type: ignore[arg-type]
    )

    assert diagnostics["network"]["same_lan_prefix_guess"] is True
    assert diagnostics["network"]["callback_base_url_override"] == {
        "configured": True,
        "scheme": "http",
        "host_type": "ipv4",
        "is_clean_local_http": True,
    }
    assert diagnostics["runtime"]["connection"]["last_connection_error"] == {
        "type": "ClientConnectorError",
        "message": "<url> failed",
    }
    # A self-test failure is the reason people are asked for diagnostics, so the
    # report has to name the failed check and which identity half is missing.
    assert diagnostics["runtime"]["self_test"]["ok"] is False
    assert diagnostics["runtime"]["self_test"]["checks"]["homeassistant_user"] == {
        "ok": False,
        "reason": "media_identity_missing",
    }
    assert diagnostics["runtime"]["media_user_bootstrapped_once"] is False
    assert diagnostics["runtime"]["device_user"]["domain_present"] is True
    assert diagnostics["runtime"]["device_user"]["homeassistant_user_present"] is False
    assert diagnostics["runtime"]["connection"]["event_subscription"] == {
        "id_configured": True,
        "event_count": 3,
        "callback_scheme": "http",
        "callback_host_type": "ipv4",
        "callback_is_clean_local_http": True,
        "last_attempt_at": "2026-06-02T00:00:00+00:00",
        "last_success_at": "2026-06-02T00:00:00+00:00",
        "last_failure_at": None,
        "last_error": None,
    }
    assert diagnostics["installation"]["event_subscription_endpoint_usable"] is True
    assert diagnostics["configuration"]["dashboard_entity_domains"] == {
        "sensor": 1,
        "switch": 1,
    }
    assert diagnostics["configuration"]["dashboard_entity_display_override_count"] == 1
    assert diagnostics["runtime"]["system_metrics"] == {
        "cpu_count": 2,
        "cpu_usage_percent": 3.5,
        "load_1m": None,
        "load_5m": None,
        "load_15m": None,
        "load_1m_percent": None,
        "memory_total_kb": 262144,
        "memory_available_kb": 151978,
        "memory_used_kb": 110166,
        "memory_usage_percent": 42.0,
        "temperature_c": 41.2,
        "temperature_source": None,
    }
    assert diagnostics["runtime"]["media_timeline"] == [
        {
            "at": "2026-06-02T00:00:00+00:00",
            "kind": "webrtc",
            "event": "session_prepared",
            "media_state": "on_demand_active",
            "owner": "doorbell",
            "session_count": 1,
            "ring_preview_sessions": 0,
            "ready_sessions": 0,
            "details": {"provider": "go2rtc", "wants_audio": True},
        }
    ]

    encoded = json.dumps(diagnostics, sort_keys=True)
    for private_value in (
        "192.0.2.60",
        "192.0.2.10",
        "private-agent-token",
        "private-maintenance-token",
        "private-webhook",
        "private-event-webhook-id",
        "private-shared-secret",
        "alarm_control_panel.private_alarm",
        "weather.private_home",
        "button.private_button",
        "switch.private_switch",
        "sensor.private_temperature",
        "/home/bticino/private",
        "/private-stream",
    ):
        assert private_value not in encoded


def test_config_entry_diagnostics_describe_unloaded_installation() -> None:
    entry = _FakeEntry(
        data={
            CONF_AGENT_HOST: "",
            CONF_AGENT_PORT: 8091,
            CONF_AGENT_TOKEN: "",
        },
        options={},
        runtime_data=None,
    )

    diagnostics = asyncio.run(
        async_get_config_entry_diagnostics(_FakeHass(), entry)  # type: ignore[arg-type]
    )

    assert diagnostics["runtime"]["loaded"] is False
    assert diagnostics["network"]["agent_endpoint"]["host_configured"] is False
    assert diagnostics["installation"]["runtime_loaded"] is False
    assert diagnostics["installation"]["agent_reachable"] is None
    assert diagnostics["network"]["callback_base_url_override"] == {
        "configured": False,
        "scheme": None,
        "host_type": None,
        "is_clean_local_http": None,
    }


def test_network_diagnostics_uses_direct_route_without_executor(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "custom_components.bticino_c300x.diagnostics._route_diagnostics",
        lambda host, port: {
            "resolved": True,
            "selected_source_type": "ipv4",
            "selected_target_type": "ipv4",
            "same_lan_prefix_guess": host == "c300x.local" and port == 8091,
            "error": None,
        },
    )
    entry = _FakeEntry(data={CONF_AGENT_HOST: "c300x.local", CONF_AGENT_PORT: "bad"})

    diagnostics = asyncio.run(
        _async_network_diagnostics(SimpleNamespace(), entry)  # type: ignore[arg-type]
    )

    assert diagnostics["agent_endpoint"]["port"] == 8091
    assert diagnostics["route"] == {
        "resolved": True,
        "selected_source_type": "ipv4",
        "selected_target_type": "ipv4",
        "same_lan_prefix_guess": True,
        "error": None,
    }


def test_route_diagnostics_reports_resolution_and_unusable_route_errors(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("dns failed")),
    )

    assert _route_diagnostics("c300x.local", 8091)["error"] == "OSError"

    class _FailingSocket:
        def __enter__(self) -> _FailingSocket:
            return self

        def __exit__(self, *args: object) -> None:
            _ = args

        def connect(self, sockaddr: tuple[str, int]) -> None:
            _ = sockaddr
            raise OSError("route failed")

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (
                socket.AF_INET,
                socket.SOCK_DGRAM,
                socket.IPPROTO_UDP,
                "",
                ("192.0.2.60", 8091),
            )
        ],
    )
    monkeypatch.setattr(socket, "socket", lambda *_args: _FailingSocket())

    result = _route_diagnostics("c300x.local", 8091)

    assert result["resolved"] is True
    assert result["error"] == "no_usable_route"


def test_route_diagnostics_reports_selected_udp_route(
    monkeypatch: Any,
) -> None:
    class _FakeSocket:
        def __enter__(self) -> _FakeSocket:
            return self

        def __exit__(self, *args: object) -> None:
            _ = args

        def connect(self, sockaddr: tuple[str, int]) -> None:
            self.sockaddr = sockaddr

        def getsockname(self) -> tuple[str, int]:
            return ("192.0.2.20", 54321)

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (
                socket.AF_INET,
                socket.SOCK_DGRAM,
                socket.IPPROTO_UDP,
                "",
                ("192.0.2.60", 8091),
            )
        ],
    )
    monkeypatch.setattr(socket, "socket", lambda *_args: _FakeSocket())

    assert _route_diagnostics("c300x.local", 8091) == {
        "resolved": True,
        "selected_source_type": "ipv4",
        "selected_target_type": "ipv4",
        "same_lan_prefix_guess": True,
        "error": None,
    }


def test_installer_bundle_status_uses_direct_call_without_executor(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "custom_components.bticino_c300x.diagnostics.installer_bundle_status",
        lambda: {"available": True, "reason": None},
    )

    assert asyncio.run(_async_installer_bundle_status(SimpleNamespace())) == {
        "available": True,
        "reason": None,
    }


def test_config_entry_diagnostics_reject_localhost_callback_override() -> None:
    entry = _FakeEntry(
        data={
            CONF_AGENT_HOST: "c300x.local",
            CONF_AGENT_PORT: 8091,
            CONF_CALLBACK_BASE_URL: "http://localhost:8123",
        },
        runtime_data=None,
    )

    diagnostics = asyncio.run(
        async_get_config_entry_diagnostics(_FakeHass(), entry)  # type: ignore[arg-type]
    )

    assert diagnostics["network"]["callback_base_url_override"] == {
        "configured": True,
        "scheme": "http",
        "host_type": "loopback",
        "is_clean_local_http": False,
    }


def test_config_entry_diagnostics_flag_unclean_subscription_callback() -> None:
    connection_state = C300XConnectionState()
    connection_state.mark_event_subscription_attempt(
        "http://homeassistant.local:8123/api/webhook/private-webhook",
        1,
        datetime(2026, 6, 2, tzinfo=UTC),
    )
    entry = _FakeEntry(
        data={
            CONF_AGENT_HOST: "c300x.local",
            CONF_AGENT_PORT: 8091,
        },
        runtime_data=SimpleNamespace(
            loaded_platforms=(),
            connection_state=connection_state,
            event_state=C300XEventState(),
            agent_info={},
            capabilities={},
            agent_update_state=None,
            qml_patch_status={},
            system_metrics={},
            agent_diagnostics={},
        ),
    )

    diagnostics = asyncio.run(
        async_get_config_entry_diagnostics(_FakeHass(), entry)  # type: ignore[arg-type]
    )

    subscription = diagnostics["runtime"]["connection"]["event_subscription"]
    assert subscription["callback_host_type"] == "mdns"
    assert subscription["callback_is_clean_local_http"] is False


def test_config_entry_diagnostics_redact_hostname_errors() -> None:
    connection_state = C300XConnectionState()
    connection_state.mark_reconnecting(
        "setup_probe",
        30,
        "ClientConnectorError: Cannot connect to host c300x.local:8091 "
        "ssl:default [Connect call failed ('c300x.local', 8091)]",
    )
    entry = _FakeEntry(
        data={CONF_AGENT_HOST: "c300x.local", CONF_AGENT_PORT: 8091},
        runtime_data=SimpleNamespace(
            loaded_platforms=(),
            connection_state=connection_state,
            event_state=C300XEventState(),
            agent_info={},
            capabilities={},
            agent_update_state=None,
            qml_patch_status={},
            system_metrics={},
            agent_diagnostics={},
        ),
    )

    diagnostics = asyncio.run(
        async_get_config_entry_diagnostics(_FakeHass(), entry)  # type: ignore[arg-type]
    )

    error = diagnostics["runtime"]["connection"]["last_connection_error"]
    assert error == {
        "type": "ClientConnectorError",
        "message": "Cannot connect to host <hostname> ssl:default [Connect call failed ('<hostname>', 8091)]",
    }
    assert "c300x.local" not in json.dumps(diagnostics)


def test_config_entry_diagnostics_explain_callback_and_maintenance_failures() -> None:
    display_bridge = C300XCallbackDiagnostics()
    display_bridge.mark_callback_attempt(
        "https://ha.example.local:8123/api/webhook/private-webhook",
        datetime(2026, 6, 2, tzinfo=UTC),
    )
    display_bridge.mark_failure(
        "C300XAgentApiConnectionError: device agent returned HTTP 400: unsupported_webhook_url",
        datetime(2026, 6, 2, tzinfo=UTC),
    )
    qml_patch = C300XOperationDiagnostics()
    qml_patch.mark_attempt(datetime(2026, 6, 2, tzinfo=UTC))
    qml_patch.mark_failure(
        "C300XAgentApiConnectionError: device agent returned HTTP 403: maintenance_unauthorized",
        datetime(2026, 6, 2, tzinfo=UTC),
    )
    entry = _FakeEntry(
        data={CONF_AGENT_HOST: "c300x.local", CONF_AGENT_PORT: 8091},
        runtime_data=SimpleNamespace(
            loaded_platforms=(),
            connection_state=C300XConnectionState(),
            event_state=C300XEventState(),
            agent_info={},
            capabilities={},
            agent_update_state=None,
            qml_patch_status={},
            qml_patch_diagnostics=qml_patch,
            display_bridge_diagnostics=display_bridge,
            system_metrics={},
            agent_diagnostics={},
        ),
    )

    diagnostics = asyncio.run(
        async_get_config_entry_diagnostics(_FakeHass(), entry)  # type: ignore[arg-type]
    )

    bridge = diagnostics["runtime"]["display_bridge"]
    assert bridge["callback_scheme"] == "https"
    assert bridge["callback_host_type"] == "mdns"
    assert bridge["callback_is_clean_local_http"] is False
    assert bridge["last_error"] == {
        "type": "C300XAgentApiConnectionError",
        "message": "device agent returned HTTP 400: unsupported_webhook_url",
    }
    assert diagnostics["runtime"]["qml_patch_check"]["last_error"] == {
        "type": "C300XAgentApiConnectionError",
        "message": "device agent returned HTTP 403: maintenance_unauthorized",
    }


def test_diagnostics_helpers_keep_runtime_data_safe_and_useful() -> None:
    runtime = SimpleNamespace(
        agent_info={
            "version": "1.2.1",
            "implementation": "native",
            "api_version": "1.1",
            "model": "C300X",
            "firmware": "1.7.19",
            "device_id": "private-device-id",
        },
        capabilities={
            "video": {"supported": True, "internal": "hidden", "count": 2},
            "home_call": True,
            "custom": ["not safe"],
        },
        system_metrics={
            "cpu_count": 1,
            "cpu_usage_percent": 2.5,
            "temperature_c": 41.2,
            "extra": "ignored",
        },
        agent_diagnostics={
            "agent_write_count": 3,
            "last_write_reason": "config_changed",
            "token": "secret",
            "nested": {"hidden": True},
        },
        agent_diagnostics_updated_by="push_event",
        agent_diagnostics_change_reason="write_diagnostics_changed",
    )
    entry = _FakeEntry(runtime_data=runtime)

    agent_info = _agent_info_diagnostics(runtime)
    assert agent_info == {
        "version": "1.2.1",
        "implementation": "native",
        "api_version": "1.1",
        "model": "C300X",
        "firmware": "1.7.19",
        "device_id_configured": True,
        "device_id_fingerprint": agent_info["device_id_fingerprint"],
    }
    assert "private-device-id" not in json.dumps(agent_info)

    assert _capability_diagnostics(runtime) == {
        "custom": {"configured": True},
        "home_call": {"supported": True},
        "video": {"count": 2, "supported": True},
    }
    assert _safe_system_metrics(runtime) == {
        "cpu_count": 1,
        "cpu_usage_percent": 2.5,
        "load_1m": None,
        "load_5m": None,
        "load_15m": None,
        "load_1m_percent": None,
        "memory_total_kb": None,
        "memory_available_kb": None,
        "memory_used_kb": None,
        "memory_usage_percent": None,
        "temperature_c": 41.2,
        "temperature_source": None,
    }

    writes = _agent_write_diagnostics(entry)  # type: ignore[arg-type]
    assert writes["agent_write_count"] == 3
    assert writes["last_write_reason"] == "config_changed"
    assert writes["agent_diagnostics_updated_by"] == "push_event"
    assert "token" not in writes
    assert "nested" not in writes


def test_diagnostics_report_media_user_and_self_test_failure_reasons() -> None:
    """A failed self-test is only actionable with its per-check reason codes,
    and the media-user flags say which half of the identity is missing."""

    runtime = SimpleNamespace(
        device_user_status={
            "available": True,
            "supported": True,
            "domain_present": True,
            "homeassistant_user_present": False,
            "media_identity_available": False,
            "routes_consistent": True,
            "device_routing_applied": False,
            "device_routing_state": "missing",
            "device_routing_error": "RuntimeError: /home/bticino/cfg/private.conf",
            "account_label": "Private Home Label",
            "raw": {"aor": "sip:private@device"},
        },
        device_user_status_updated_at=datetime(2026, 8, 20, 7, 27, tzinfo=UTC),
        self_test_status={
            "ok": False,
            "agent_version": "1.9.0",
            "api_version": "1",
            "firmware_family": "1.7.19",
            "checks": {
                "homeassistant_user": {
                    "ok": False,
                    "reason": "media_identity_missing",
                    "details": {"users_file": "/home/bticino/cfg/private-users"},
                },
                "firewall": {"ok": True, "reason": "media_ports_open"},
            },
        },
        self_test_status_updated_at=datetime(2026, 8, 20, 7, 27, tzinfo=UTC),
    )

    device_user = _device_user_diagnostics(runtime)
    assert device_user is not None
    assert device_user["domain_present"] is True
    assert device_user["homeassistant_user_present"] is False
    assert device_user["media_identity_available"] is False
    assert device_user["device_routing_state"] == "missing"
    # Label, AOR and raw device paths never reach the report.
    assert "account_label" not in device_user
    assert "raw" not in device_user
    assert "Private Home Label" not in json.dumps(device_user)
    assert "private.conf" not in json.dumps(device_user)

    self_test = _self_test_diagnostics(runtime)
    assert self_test is not None
    assert self_test["ok"] is False
    assert self_test["checks"]["homeassistant_user"] == {
        "ok": False,
        "reason": "media_identity_missing",
    }
    assert self_test["checks"]["firewall"] == {"ok": True, "reason": "media_ports_open"}
    # Per-check details carry device paths and stay out of the report.
    assert "private-users" not in json.dumps(self_test)


def test_diagnostics_helpers_handle_missing_or_invalid_runtime_data() -> None:
    assert _device_user_diagnostics(None) is None
    assert _device_user_diagnostics(SimpleNamespace(device_user_status={})) is None
    assert _device_user_diagnostics(SimpleNamespace(device_user_status=[])) is None
    assert _self_test_diagnostics(None) is None
    assert _self_test_diagnostics(SimpleNamespace(self_test_status={})) is None
    assert _self_test_diagnostics(SimpleNamespace(self_test_status=[])) is None
    assert (
        _self_test_diagnostics(SimpleNamespace(self_test_status={"ok": True}))["checks"]
        is None
    )
    assert _agent_info_diagnostics(None) is None
    assert _agent_info_diagnostics(SimpleNamespace(agent_info=[])) is None
    assert _connection_diagnostics(None) is None
    assert _connection_diagnostics(SimpleNamespace(connection_state=None)) is None
    assert _event_state_diagnostics(None) is None
    assert _event_state_diagnostics(SimpleNamespace(event_state=None)) is None
    assert _capability_diagnostics(None) is None
    assert _capability_diagnostics(SimpleNamespace(capabilities=[])) is None
    assert _safe_system_metrics(None) is None
    assert _safe_system_metrics(SimpleNamespace(system_metrics=[])) is None
    empty_writes = _agent_write_diagnostics(_FakeEntry())  # type: ignore[arg-type]
    assert isinstance(empty_writes, dict)
    assert empty_writes["agent_write_count"] is None
    assert _agent_write_diagnostics(SimpleNamespace()) is None  # type: ignore[arg-type]
    assert (
        _agent_write_diagnostics(  # type: ignore[arg-type]
            _FakeEntry(runtime_data=SimpleNamespace(agent_diagnostics=[]))
        )
        is None
    )


def test_diagnostics_value_helpers_redact_and_normalize_values() -> None:
    assert _safe_status_dict(
        {
            "ok": True,
            "host": "192.0.2.60",
            "nested": {"hidden": True},
            "path": "/secret",
            "count": 2,
        }
    ) == {"count": 2, "ok": True}
    assert _safe_status_dict([]) is None

    assert _entity_domain_counts(["light.a", "sensor.temp", "light.b", "invalid"]) == {
        "light": 2,
        "sensor": 1,
    }
    assert _entity_domain_counts("sensor.temp") == {}
    assert _sequence_count([1, 2, 3]) == 3
    assert _sequence_count("abc") is None
    assert _isoformat(datetime(2026, 6, 15, tzinfo=UTC)) == "2026-06-15T00:00:00+00:00"
    assert _isoformat("already") == "already"
    assert _isoformat(1) is None

    summary = _safe_error_summary(
        "ClientConnectorError: failed http://ha.local:8123 for 192.0.2.10 and [fe80::1]:8123"
    )
    assert summary == {
        "type": "ClientConnectorError",
        "message": "failed <url> for <ipv4> and <ipv6>",
    }
    assert _safe_error_summary("") is None
    assert _safe_error_summary("   ") is None
    assert _safe_error_summary("ConnectionError:   ") == {
        "type": "ConnectionError",
        "message": None,
    }
    assert _redact_error_message("failed via fe80::abcd%eth0 and port 8091") == (
        "failed via <ipv6> and port 8091"
    )

    private_a = ".".join(("192", "168", "1", "10"))
    private_b = ".".join(("192", "168", "1", "20"))
    assert _host_private_address(private_a) is True
    assert _host_private_address("example.invalid") is None
    assert _same_lan_prefix_guess(None, None) is None
    assert (
        _same_lan_prefix_guess(
            ipaddress.ip_address(private_a),
            ipaddress.ip_address(private_b),
        )
        is True
    )


def test_diagnostics_answer_why_media_setup_is_blocked() -> None:
    """Issue #43 had to be diagnosed by elimination: the report said forwarding
    was "known" without saying what it was, carried no readiness verdict, and
    said nothing about the setup switch the reporter saw greyed out."""

    runtime = SimpleNamespace(
        capabilities={"doorbell_call": {"supported": True}},
        connection_state=C300XConnectionState(),
        self_test_status={},
        device_user_status={},
        agent_info={"version": "1.9.2"},
        event_state=C300XEventState(smartphone_forwarding_mode="blocked"),
    )
    entry = _FakeEntry(data={CONF_VIDEO_ENABLED: True}, runtime_data=runtime)

    event_state = _event_state_diagnostics(runtime)
    readiness = _media_readiness_diagnostics(entry, runtime)  # type: ignore[arg-type]

    assert event_state is not None
    assert event_state["smartphone_forwarding_mode"] == "blocked"
    assert readiness is not None
    assert readiness["status"] == "blocked"
    assert readiness["failed_checks"] == ["forwarding_homeassistant"]
    assert readiness["forwarding_state"] == "blocked"


def test_diagnostics_describe_the_setup_switch_without_its_entity_id() -> None:
    """"Greyed out" can mean disabled or an orphaned registry entry. The flags
    tell them apart; the entity id stays out, it carries device names."""

    section = _media_user_setup_entity_diagnostics(
        SimpleNamespace(),  # type: ignore[arg-type]
        _FakeEntry(),  # type: ignore[arg-type]
    )

    assert set(section) == {
        "registry_available",
        "registry_present",
        "disabled_by",
        "state_present",
        "error",
    }


def test_diagnostics_carry_the_bridge_counters_issue_44_needs() -> None:
    """The counters that decide issue #44 live only in the video-status
    endpoint: the reporter was asked for fields the download never contained,
    so he supplied a report that could not answer the question."""

    class _Api:
        def __init__(self) -> None:
            self.calls = 0

        async def async_doorbell_video_status(self) -> dict[str, Any]:
            self.calls += 1
            return {
                "bridge": {
                    "media_owner": "idle",
                    "clients": 0,
                    "rtsp_describe_requests": 88,
                    "rtsp_play_requests": 0,
                    "rtsp_rejected_clients": 0,
                    "last_rtsp_reject_reason": "",
                    "bt_media_start_attempts": 0,
                    "rtp_packets": 0,
                    "last_error": "connect /dev/video0 failed",
                }
            }

    api = _Api()
    entry = _FakeEntry(
        data={CONF_VIDEO_ENABLED: True},
        runtime_data=SimpleNamespace(api=api),
    )

    section = asyncio.run(
        _async_video_bridge_diagnostics(entry, entry.runtime_data)  # type: ignore[arg-type]
    )

    assert api.calls == 1
    assert section is not None
    assert section["rtsp_describe_requests"] == 88
    assert section["rtsp_play_requests"] == 0
    assert section["rtp_packets"] == 0
    assert section["bt_media_start_attempts"] == 0
    # The error text stays out; only that there is one.
    assert section["last_error_present"] is True
    assert "/dev/video0" not in json.dumps(section)


def test_diagnostics_survive_an_agent_that_cannot_be_reached() -> None:
    """The download is what people fetch when the agent misbehaves."""

    class _FailingApi:
        async def async_doorbell_video_status(self) -> dict[str, Any]:
            raise TimeoutError("agent unreachable")

    entry = _FakeEntry(
        data={CONF_VIDEO_ENABLED: True},
        runtime_data=SimpleNamespace(api=_FailingApi()),
    )

    section = asyncio.run(
        _async_video_bridge_diagnostics(entry, entry.runtime_data)  # type: ignore[arg-type]
    )

    assert section == {"error": "TimeoutError"}
