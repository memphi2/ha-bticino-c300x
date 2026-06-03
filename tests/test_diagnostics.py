from __future__ import annotations

import asyncio
import json
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
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_ADDRESS,
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
    async_get_config_entry_diagnostics,
)


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
            "last_write_class": "subscription",
            "last_write_reason": "updated",
            "subscription_store_writes": 1,
            "raw": {"token": "private-token"},
        },
        agent_diagnostics_updated_at=datetime(2026, 6, 2, tzinfo=UTC),
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
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_ADDRESS: "77",
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
