from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace
from typing import Any

import pytest

import custom_components.bticino_c300x as integration
import custom_components.bticino_c300x.entry_locks as entry_locks
import custom_components.bticino_c300x.runtime_manager as runtime_manager
from custom_components.bticino_c300x.const import (
    CONF_AGENT_HOST,
    CONF_AGENT_TOKEN,
    CONF_ALARM_ENTITY_ID,
    CONF_CREATE_HOMEASSISTANT_USER,
    CONF_DEVICE_ACTIVATION_MODE,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P,
    CONF_DEVICE_ACTIVATIONS,
    CONF_DEVICE_UI_ENABLED,
    CONF_EVENT_WEBHOOK_ID,
    CONF_EVENT_WEBHOOK_TOKEN,
    CONF_HOMEASSISTANT_MEDIA_USER_BOOTSTRAPPED,
    CONF_MAINTENANCE_TOKEN,
    CONF_SHARED_SECRET,
    CONF_VIDEO_ENABLED,
    CONF_WEBHOOK_ID,
    DATA_RUNTIME_ENTRIES,
    DEVICE_ACTIVATION_MODE_MANUAL,
    DOMAIN,
)
from custom_components.bticino_c300x.data import (
    C300XCallbackDiagnostics,
    C300XConnectionState,
    C300XOperationDiagnostics,
)


def _stub_homeassistant_http() -> None:
    core = sys.modules.setdefault(
        "homeassistant.core",
        types.ModuleType("homeassistant.core"),
    )
    if not hasattr(core, "ServiceCall"):
        core.ServiceCall = type("ServiceCall", (), {})
    dispatcher = sys.modules.setdefault(
        "homeassistant.helpers.dispatcher",
        types.ModuleType("homeassistant.helpers.dispatcher"),
    )
    if not hasattr(dispatcher, "async_dispatcher_send"):
        dispatcher.async_dispatcher_send = lambda *args, **kwargs: None
    if not hasattr(dispatcher, "async_dispatcher_connect"):
        dispatcher.async_dispatcher_connect = lambda *_args, **_kwargs: lambda: None

    components = sys.modules.setdefault(
        "homeassistant.components",
        types.ModuleType("homeassistant.components"),
    )
    http = sys.modules.setdefault(
        "homeassistant.components.http",
        types.ModuleType("homeassistant.components.http"),
    )

    if not hasattr(http, "HomeAssistantView"):

        class HomeAssistantView:  # pragma: no cover - import-time stub only
            pass

        http.HomeAssistantView = HomeAssistantView

    components.http = http

    webhook = sys.modules.setdefault(
        "homeassistant.components.webhook",
        types.ModuleType("homeassistant.components.webhook"),
    )
    if not hasattr(webhook, "async_register"):
        webhook.async_register = lambda *_args, **_kwargs: None
    if not hasattr(webhook, "async_unregister"):
        webhook.async_unregister = lambda *_args, **_kwargs: None
    components.webhook = webhook


def test_migrate_entry_generates_missing_setup_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    updates: list[dict[str, Any]] = []
    entry = SimpleNamespace(
        data={"controller_host": "192.0.2.60"},
        options={},
        minor_version=1,
    )
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_update_entry=lambda _entry, **kwargs: updates.append(kwargs)
        )
    )
    monkeypatch.setattr(integration.secrets, "token_urlsafe", lambda n: f"token-{n}")

    assert asyncio.run(integration.async_migrate_entry(hass, entry)) is True

    assert updates == [
        {
            "data": {
                "controller_host": "192.0.2.60",
                CONF_AGENT_HOST: "192.0.2.60",
                CONF_WEBHOOK_ID: "token-24",
                CONF_SHARED_SECRET: "token-32",
                CONF_EVENT_WEBHOOK_ID: "token-24",
                CONF_EVENT_WEBHOOK_TOKEN: "token-32",
            },
            "options": {},
            "version": 1,
            "minor_version": 2,
        }
    ]


def test_async_setup_registers_frontend_services_and_websocket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    blueprint_installer = types.ModuleType(
        "custom_components.bticino_c300x.blueprint_installer"
    )
    blueprint_installer.async_install_bundled_blueprints = (
        lambda _hass: _async_value(calls.append("blueprints"))
    )
    frontend = types.ModuleType("custom_components.bticino_c300x.frontend")
    frontend.async_setup_frontend = lambda _hass: _async_value(calls.append("frontend"))
    services = types.ModuleType("custom_components.bticino_c300x.services")
    services.async_setup_services = lambda _hass: _async_value(calls.append("services"))
    debug_ws = types.ModuleType("custom_components.bticino_c300x.debug_ws")
    debug_ws.async_register_debug_ws = lambda _hass: calls.append("debug-ws")
    camera = types.ModuleType("custom_components.bticino_c300x.camera")
    camera.async_register_home_call_ws = lambda _hass: calls.append("ws")
    monkeypatch.setitem(
        sys.modules,
        "custom_components.bticino_c300x.blueprint_installer",
        blueprint_installer,
    )
    monkeypatch.setitem(
        sys.modules,
        "custom_components.bticino_c300x.frontend",
        frontend,
    )
    monkeypatch.setitem(
        sys.modules,
        "custom_components.bticino_c300x.services",
        services,
    )
    monkeypatch.setitem(
        sys.modules,
        "custom_components.bticino_c300x.debug_ws",
        debug_ws,
    )
    monkeypatch.setitem(sys.modules, "custom_components.bticino_c300x.camera", camera)
    hass = SimpleNamespace(data={})

    assert asyncio.run(integration.async_setup(hass, {})) is True

    assert hass.data[DOMAIN] == {}
    assert calls == ["blueprints", "frontend", "services", "debug-ws", "ws"]


def test_setup_entry_builds_runtime_and_forwards_platforms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _stub_homeassistant_http()
    aiohttp_client = sys.modules.setdefault(
        "homeassistant.helpers.aiohttp_client",
        types.ModuleType("homeassistant.helpers.aiohttp_client"),
    )
    aiohttp_client.async_get_clientsession = lambda _hass: "session"

    import custom_components.bticino_c300x.agent_update as agent_update
    import custom_components.bticino_c300x.capabilities as capabilities
    import custom_components.bticino_c300x.events as events
    import custom_components.bticino_c300x.media as media
    import custom_components.bticino_c300x.repair_issues as repair_issues
    import custom_components.bticino_c300x.services as services
    import custom_components.bticino_c300x.webhook as webhook

    monkeypatch.setattr(agent_update, "async_load_packaged_bundle_metadata", _async_empty)
    monkeypatch.setattr(
        agent_update,
        "compare_agent_bundle",
        lambda _setup, _bundle: {"available": False},
    )
    monkeypatch.setattr(
        capabilities,
        "gate_capabilities",
        lambda caps, *, doorbell_video_enabled: caps,
    )
    monkeypatch.setattr(
        events,
        "async_start_agent_event_registration",
        lambda *_args, **_kwargs: _async_value(lambda: calls.append("event-registration")),
    )
    monkeypatch.setattr(media, "async_setup_media_view", lambda _hass: calls.append("media-view"))
    monkeypatch.setattr(
        repair_issues,
        "async_sync_entry_repair_issues",
        lambda _hass, _entry: calls.append("repair-sync"),
    )
    monkeypatch.setattr(
        services,
        "async_setup_services",
        lambda _hass: _async_value(calls.append("services")),
    )
    monkeypatch.setattr(
        webhook,
        "async_register_webhook",
        lambda _hass, _entry: lambda: calls.append("webhook-unregister"),
    )
    monkeypatch.setattr(
        webhook,
        "async_register_agent_event_webhook",
        lambda *_args: lambda: calls.append("event-webhook-unregister"),
    )
    monkeypatch.setattr(
        runtime_manager,
        "_async_configure_device_activations",
        _record_async(calls, "activations"),
    )
    monkeypatch.setattr(
        runtime_manager,
        "_async_configure_display_bridge",
        _record_async(calls, "display"),
    )
    monkeypatch.setattr(
        runtime_manager,
        "_async_sync_device_ui_patch",
        _record_async(calls, "qml"),
    )
    monkeypatch.setattr(
        runtime_manager,
        "_async_sync_device_user",
        _record_async(calls, "user"),
    )
    monkeypatch.setattr(
        runtime_manager,
        "_async_track_display_bridge_updates",
        lambda _hass, _entry: lambda: calls.append("display-unregister"),
    )
    monkeypatch.setattr(
        runtime_manager,
        "_async_remove_stale_gui_dependent_entities",
        lambda _hass, _entry: calls.append("remove-stale"),
    )
    monkeypatch.setattr(runtime_manager, "C300XAgentApi", _SetupApi)

    entry = _entry(
        data={
            CONF_AGENT_HOST: "192.0.2.60",
            CONF_AGENT_TOKEN: "agent-token",
            CONF_MAINTENANCE_TOKEN: "maintenance-token",
            CONF_WEBHOOK_ID: "webhook-id",
            CONF_SHARED_SECRET: "secret",
            CONF_EVENT_WEBHOOK_ID: "event-webhook-id",
            CONF_EVENT_WEBHOOK_TOKEN: "event-token",
        },
        options={CONF_VIDEO_ENABLED: True},
    )
    entry.added_listeners = []
    entry.async_on_unload = lambda callback: entry.added_listeners.append(callback)
    entry.add_update_listener = lambda callback: ("listener", callback)
    hass = SimpleNamespace(
        data={},
        config_entries=SimpleNamespace(
            async_forward_entry_setups=lambda _entry, platforms: _async_value(
                calls.append(f"forward:{','.join(platforms)}")
            )
        ),
    )

    assert asyncio.run(integration.async_setup_entry(hass, entry)) is True

    assert entry.runtime_data.agent_info["version"] == "1.2.0"
    assert integration.CAMERA_PLATFORM in entry.runtime_data.loaded_platforms
    assert entry.runtime_data.agent_update_state == {"available": False}
    assert calls == [
        "remove-stale",
        "repair-sync",
        "services",
        "qml",
        "media-view",
        "forward:binary_sensor,button,event,number,sensor,select,switch,camera",
        "activations",
        "display",
        "user",
        "repair-sync",
    ]
    assert entry.added_listeners


def test_setup_entry_rejects_missing_required_fields() -> None:
    _stub_homeassistant_http()
    hass = SimpleNamespace(data={})
    entry = _entry(data={})

    assert asyncio.run(integration.async_setup_entry(hass, entry)) is False


def test_remove_entry_clears_repair_issues_and_runtime_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import custom_components.bticino_c300x.repair_issues as repair_issues

    cleared: list[str] = []
    cancelled: list[str] = []
    callbacks: list[str] = []
    monkeypatch.setattr(
        repair_issues,
        "async_clear_entry_repair_issues",
        lambda _hass, entry_id: cleared.append(entry_id),
    )
    entry = _entry(data={})
    entry.runtime_data = SimpleNamespace(
        unregister_event_registration=lambda: callbacks.append("registration"),
        unregister_display_bridge_updates=lambda: callbacks.append("display"),
        unregister_event_webhook=lambda: callbacks.append("event-webhook"),
        unregister_webhook=lambda: callbacks.append("webhook"),
        connection_state=SimpleNamespace(expire_unavailable=lambda: callbacks.append("expire")),
        memos_refresh_task=SimpleNamespace(cancel=lambda: cancelled.append("memos")),
        answering_machine_messages_refresh_task=SimpleNamespace(
            cancel=lambda: cancelled.append("messages")
        ),
    )
    entry_locks.entry_lock(entry.entry_id, "ring_capture")
    hass = SimpleNamespace(
        data={DOMAIN: {DATA_RUNTIME_ENTRIES: {entry.entry_id: entry.runtime_data}}}
    )

    asyncio.run(integration.async_remove_entry(hass, entry))

    assert cleared == [entry.entry_id]
    assert callbacks == ["registration", "display", "expire", "event-webhook", "webhook"]
    assert cancelled == ["memos", "messages"]
    assert entry.runtime_data.memos_refresh_task is None
    assert entry.runtime_data.answering_machine_messages_refresh_task is None
    assert not any(key[0] == entry.entry_id for key in entry_locks._locks)
    assert hass.data[DOMAIN][DATA_RUNTIME_ENTRIES] == {}


def test_setup_recovery_retries_until_agent_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduled: list[Any] = []
    cancelled: list[int] = []
    sent: list[str] = []
    reloaded: list[str] = []

    import homeassistant.helpers.dispatcher as dispatcher
    import homeassistant.helpers.event as event_helper

    def call_later(_hass: Any, _delay: int, callback: Any) -> Any:
        scheduled.append(callback)
        return lambda: cancelled.append(len(scheduled))

    monkeypatch.setattr(event_helper, "async_call_later", call_later, raising=False)
    monkeypatch.setattr(
        dispatcher,
        "async_dispatcher_send",
        lambda _hass, _signal, entry_id: sent.append(entry_id),
        raising=False,
    )
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_reload=lambda entry_id: _async_value(reloaded.append(entry_id))
        )
    )
    entry = _entry()
    connection_state = C300XConnectionState()
    api = _RecoveringSetupApi()

    cancel = integration._async_start_setup_recovery(hass, entry, api, connection_state)
    asyncio.run(scheduled[0]())
    asyncio.run(scheduled[1]())
    cancel()

    assert sent == ["entry-1"]
    assert reloaded == ["entry-1"]
    assert cancelled == []


def test_setup_helpers_keep_existing_secrets_and_select_platforms() -> None:
    data = {CONF_WEBHOOK_ID: "existing", CONF_SHARED_SECRET: object()}

    integration._ensure_generated_setup_secret(data, CONF_WEBHOOK_ID, 24)
    integration._ensure_generated_setup_secret(data, CONF_SHARED_SECRET, 32)

    assert data[CONF_WEBHOOK_ID] == "existing"
    assert not isinstance(data[CONF_SHARED_SECRET], str)
    video_entry = _entry(options={CONF_VIDEO_ENABLED: True})
    no_video_entry = _entry(options={CONF_VIDEO_ENABLED: False})
    capabilities = {"doorbell_video": {"supported": True}}
    assert integration.CAMERA_PLATFORM in integration._entry_platforms(
        video_entry, capabilities
    )
    assert integration.CAMERA_PLATFORM not in integration._entry_platforms(
        no_video_entry, capabilities
    )
    assert integration._offline_setup_data(RuntimeError("offline"))["offline_error"]


def test_device_user_and_activation_config_helpers() -> None:
    entry = _entry(
        options={
            CONF_CREATE_HOMEASSISTANT_USER: False,
            CONF_DEVICE_ACTIVATION_MODE: DEVICE_ACTIVATION_MODE_MANUAL,
        }
    )

    assert integration._entry_activation_config(entry) == (
        True,
        False,
        [
            {
                "address": "10",
                "addressMode": "manual",
                "id": "stair_light",
                "name": "Stair light",
                "type": "stair_light",
            }
        ],
    )


def test_configure_device_activations_updates_only_when_needed() -> None:
    entry = _entry(
        options={
            CONF_DEVICE_ACTIVATION_MODE: DEVICE_ACTIVATION_MODE_MANUAL,
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P: "07",
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N: "07",
        }
    )
    api = _ActivationApi(
        {
            "activations_enabled": True,
            "activations_auto_discover": True,
        }
    )

    asyncio.run(integration._async_configure_device_activations(entry, api))

    assert api.configured == [
        (
            True,
            False,
            [
                {
                    "address": "77",
                    "addressMode": "manual",
                    "id": "stair_light",
                    "name": "Stair light",
                    "type": "stair_light",
                }
            ],
        )
    ]


def test_entry_activation_config_includes_additional_activation_items() -> None:
    entry = _entry(
        options={
            CONF_DEVICE_ACTIVATION_MODE: DEVICE_ACTIVATION_MODE_MANUAL,
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P: "07",
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N: "07",
            CONF_DEVICE_ACTIVATIONS: [
                {
                    "id": "front_lock",
                    "name": "Front lock",
                    "type": "lock",
                    "address": "10",
                }
            ],
        }
    )

    assert integration._entry_activation_config(entry) == (
        True,
        False,
        [
            {
                "address": "77",
                "addressMode": "manual",
                "id": "stair_light",
                "name": "Stair light",
                "type": "stair_light",
            },
            {
                "address": "10",
                "addressMode": "manual",
                "id": "front_lock",
                "name": "Front lock",
                "type": "lock",
            },
        ],
    )


def test_configure_device_activations_uses_p_n_address() -> None:
    entry = _entry(
        options={
            CONF_DEVICE_ACTIVATION_MODE: DEVICE_ACTIVATION_MODE_MANUAL,
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P: "02",
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N: "01",
        }
    )
    api = _ActivationApi(
        {
            "activations_enabled": True,
            "activations_auto_discover": False,
        },
        items=[
            {
                "address": "21",
                "addressMode": "manual",
                "id": "stair_light",
                "name": "Stair light",
                "type": "stair_light",
            }
        ],
    )

    asyncio.run(integration._async_configure_device_activations(entry, api))

    assert api.configured == []


def test_configure_device_activations_skips_unknown_manual_address() -> None:
    entry = _entry(
        options={
            CONF_DEVICE_ACTIVATION_MODE: DEVICE_ACTIVATION_MODE_MANUAL,
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P: "02",
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N: "01",
        }
    )
    api = _ActivationApi(
        {
            "activations_enabled": True,
            "activations_auto_discover": False,
        },
        items=[
            {
                "address": "21",
                "addressMode": "manual",
                "id": "stair_light",
                "name": "Stair light",
                "type": "stair_light",
            }
        ],
    )

    asyncio.run(integration._async_configure_device_activations(entry, api))

    assert api.configured == []


def test_configure_device_activations_ignores_agent_errors() -> None:
    entry = _entry(
        options={
            CONF_DEVICE_ACTIVATION_MODE: DEVICE_ACTIVATION_MODE_MANUAL,
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P: "07",
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N: "07",
        }
    )
    api = _ActivationApi({}, error=integration.C300XAgentApiError)

    asyncio.run(integration._async_configure_device_activations(entry, api))

    assert api.configured == []


def test_configure_display_bridge_registers_and_clears_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import custom_components.bticino_c300x.callback_url as callback_url

    async def generate_callback_url(_hass: Any, _entry: Any, webhook_id: str) -> str:
        return f"https://ha.local/{webhook_id}"

    monkeypatch.setattr(callback_url, "async_generate_agent_callback_url", generate_callback_url)
    entry = _entry(
        data={
            CONF_WEBHOOK_ID: "webhook-id",
            CONF_SHARED_SECRET: "secret",
        },
        options={CONF_DEVICE_UI_ENABLED: True},
    )
    entry.runtime_data = SimpleNamespace(
        display_bridge_diagnostics=C300XCallbackDiagnostics()
    )
    api = _DisplayBridgeApi({"configured": False})

    asyncio.run(integration._async_configure_display_bridge("hass", entry, api))

    assert api.configured == [(True, "https://ha.local/webhook-id", "secret")]
    assert entry.runtime_data.display_bridge_diagnostics.last_error is None

    entry.options[CONF_DEVICE_UI_ENABLED] = False
    api = _DisplayBridgeApi({"configured": True})
    asyncio.run(integration._async_configure_display_bridge("hass", entry, api))
    assert api.configured == [(False, "", "")]


def test_configure_display_bridge_skips_matching_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import custom_components.bticino_c300x.callback_url as callback_url
    from custom_components.bticino_c300x.api import (
        display_bridge_callback_fingerprint,
    )

    async def generate_callback_url(_hass: Any, _entry: Any, webhook_id: str) -> str:
        return f"https://ha.local/{webhook_id}"

    monkeypatch.setattr(callback_url, "async_generate_agent_callback_url", generate_callback_url)
    entry = _entry(
        data={
            CONF_WEBHOOK_ID: "webhook-id",
            CONF_SHARED_SECRET: "secret",
        },
        options={CONF_DEVICE_UI_ENABLED: True},
    )
    expected_hash = display_bridge_callback_fingerprint(
        True,
        "https://ha.local/webhook-id",
        "secret",
    )
    entry.runtime_data = SimpleNamespace(
        display_bridge_diagnostics=C300XCallbackDiagnostics()
    )
    api = _DisplayBridgeApi(
        {"configured": True, "callback_hash": expected_hash}
    )

    asyncio.run(integration._async_configure_display_bridge("hass", entry, api))

    assert api.configured == []
    assert entry.runtime_data.display_bridge_diagnostics.last_error is None


def test_configure_display_bridge_records_agent_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import custom_components.bticino_c300x.callback_url as callback_url

    async def generate_callback_url(_hass: Any, _entry: Any, webhook_id: str) -> str:
        return f"https://ha.local/{webhook_id}"

    monkeypatch.setattr(callback_url, "async_generate_agent_callback_url", generate_callback_url)
    for error in (
        integration.C300XAgentApiUnsupportedError("unsupported"),
        integration.C300XAgentApiError("failed"),
    ):
        entry = _entry(
            data={
                CONF_WEBHOOK_ID: "webhook-id",
                CONF_SHARED_SECRET: "secret",
            },
            options={CONF_DEVICE_UI_ENABLED: True},
        )
        entry.runtime_data = SimpleNamespace(
            display_bridge_diagnostics=C300XCallbackDiagnostics()
        )
        api = _DisplayBridgeApi({}, error=error)

        asyncio.run(integration._async_configure_display_bridge("hass", entry, api))

        assert api.configured == []
        assert entry.runtime_data.display_bridge_diagnostics.last_error is not None


def test_sync_device_user_bootstraps_missing_media_user_once() -> None:
    entry = _entry(
        options={
            CONF_VIDEO_ENABLED: True,
            CONF_CREATE_HOMEASSISTANT_USER: True,
        }
    )
    entry.runtime_data = SimpleNamespace(
        capabilities={"device_user": {"supported": True}},
        api=_DeviceUserApi({"homeassistant_user_present": False}),
        device_user_status={},
        device_user_status_updated_at=None,
    )
    hass, updates = _hass_with_config_updates()

    asyncio.run(integration._async_sync_device_user(hass, entry))

    assert entry.runtime_data.api.ensure_labels == ["Home Assistant HA Test"]
    assert entry.runtime_data.device_user_status == {
        "homeassistant_user_present": True,
        "media_identity_available": True,
        "routes_consistent": True,
        "device_routing_applied": True,
        "media_user_label_applied": True,
    }
    assert entry.runtime_data.device_user_status_updated_at is not None
    assert updates == [
        {"data": {CONF_HOMEASSISTANT_MEDIA_USER_BOOTSTRAPPED: True}}
    ]


def test_sync_device_user_does_not_rebootstrap_missing_media_user() -> None:
    entry = _entry(
        data={CONF_HOMEASSISTANT_MEDIA_USER_BOOTSTRAPPED: True},
        options={
            CONF_VIDEO_ENABLED: True,
            CONF_CREATE_HOMEASSISTANT_USER: True,
        },
    )
    entry.runtime_data = SimpleNamespace(
        capabilities={"device_user": {"supported": True}},
        api=_DeviceUserApi({"homeassistant_user_present": False}),
        device_user_status={},
        device_user_status_updated_at=None,
    )
    hass, updates = _hass_with_config_updates()

    asyncio.run(integration._async_sync_device_user(hass, entry))

    assert entry.runtime_data.api.ensure_labels == []
    assert entry.runtime_data.device_user_status == {"homeassistant_user_present": False}
    assert updates == []


def test_sync_device_user_does_not_mark_failed_bootstrap() -> None:
    entry = _entry(
        options={
            CONF_VIDEO_ENABLED: True,
            CONF_CREATE_HOMEASSISTANT_USER: True,
        }
    )
    api = _DeviceUserApi({"homeassistant_user_present": False})
    api._ensure_status = {
        "homeassistant_user_present": False,
        "media_identity_available": False,
        "routes_consistent": False,
    }
    entry.runtime_data = SimpleNamespace(
        capabilities={"device_user": {"supported": True}},
        api=api,
        device_user_status={},
        device_user_status_updated_at=None,
    )
    hass, updates = _hass_with_config_updates()

    asyncio.run(integration._async_sync_device_user(hass, entry))

    assert api.ensure_labels == ["Home Assistant HA Test"]
    assert entry.runtime_data.device_user_status == api._ensure_status
    assert updates == []


def test_sync_device_user_skips_when_disabled_or_unsupported() -> None:
    for entry in (
        _entry(options={CONF_VIDEO_ENABLED: False}),
        _entry(options={CONF_VIDEO_ENABLED: True}),
    ):
        entry.runtime_data = SimpleNamespace(
            capabilities={}
            if entry.options.get(CONF_VIDEO_ENABLED)
            else {"device_user": {"supported": True}},
            api=_DeviceUserApi({"homeassistant_user_present": False}),
            device_user_status={},
            device_user_status_updated_at=None,
        )
        hass, updates = _hass_with_config_updates()

        asyncio.run(integration._async_sync_device_user(hass, entry))

        assert entry.runtime_data.api.ensure_labels == []
        assert entry.runtime_data.device_user_status == {}
        assert updates == []


def test_sync_device_user_refreshes_existing_status_without_repair() -> None:
    entry = _entry(
        options={
            CONF_VIDEO_ENABLED: True,
            CONF_CREATE_HOMEASSISTANT_USER: True,
        }
    )
    status = {
        "homeassistant_user_present": True,
        "media_identity_available": True,
        "routes_consistent": True,
        "device_routing_applied": True,
        "media_user_label_applied": True,
    }
    entry.runtime_data = SimpleNamespace(
        capabilities={"device_user": {"supported": True}},
        api=_DeviceUserApi(status),
        device_user_status={},
        device_user_status_updated_at=None,
    )
    hass, updates = _hass_with_config_updates()

    asyncio.run(integration._async_sync_device_user(hass, entry))

    assert entry.runtime_data.api.ensure_labels == []
    assert entry.runtime_data.device_user_status == status
    assert entry.runtime_data.device_user_status_updated_at is not None
    assert updates == [
        {"data": {CONF_HOMEASSISTANT_MEDIA_USER_BOOTSTRAPPED: True}}
    ]


def test_sync_device_user_ignores_agent_failures() -> None:
    for error in (
        integration.C300XAgentApiUnsupportedError("unsupported"),
        integration.C300XAgentApiError("failed"),
    ):
        entry = _entry(
            options={
                CONF_VIDEO_ENABLED: True,
                CONF_CREATE_HOMEASSISTANT_USER: True,
            }
        )
        entry.runtime_data = SimpleNamespace(
            capabilities={"device_user": {"supported": True}},
            api=_DeviceUserApi({"homeassistant_user_present": False}, error=error),
            device_user_status={},
            device_user_status_updated_at=None,
        )
        hass, updates = _hass_with_config_updates()

        asyncio.run(integration._async_sync_device_user(hass, entry))

        assert entry.runtime_data.device_user_status == {}
        assert updates == []


def test_sync_device_user_does_not_repair_unavailable_status() -> None:
    entry = _entry(
        options={
            CONF_VIDEO_ENABLED: True,
            CONF_CREATE_HOMEASSISTANT_USER: True,
        }
    )
    status = {
        "available": False,
        "supported": True,
        "homeassistant_user_present": None,
        "routes_consistent": None,
        "device_routing_applied": None,
        "media_user_label_applied": None,
        "error": "status_failed",
    }
    entry.runtime_data = SimpleNamespace(
        capabilities={"device_user": {"supported": True}},
        api=_DeviceUserApi(status),
        device_user_status={},
        device_user_status_updated_at=None,
    )
    hass, updates = _hass_with_config_updates()

    asyncio.run(integration._async_sync_device_user(hass, entry))

    assert entry.runtime_data.device_user_status == status
    assert entry.runtime_data.api.ensure_labels == []
    assert updates == []


def test_refresh_self_test_updates_or_clears_status() -> None:
    async def _run() -> None:
        entry = _entry()
        entry.runtime_data = SimpleNamespace(
            api=_SelfTestApi({"ok": True, "checks": {"firewall": {"ok": True}}}),
            self_test_status={},
            self_test_status_updated_at=None,
        )

        await integration._async_refresh_self_test(entry)

        assert entry.runtime_data.self_test_status == {
            "ok": True,
            "checks": {"firewall": {"ok": True}},
        }
        assert entry.runtime_data.self_test_status_updated_at is not None

        entry.runtime_data.api = _SelfTestApi(
            {},
            error=integration.C300XAgentApiUnsupportedError("unsupported"),
        )
        await integration._async_refresh_self_test(entry)

        assert entry.runtime_data.self_test_status == {}
        assert entry.runtime_data.self_test_status_updated_at is None

        entry.runtime_data.api = _SelfTestApi(
            {},
            error=integration.C300XAgentApiError("failed"),
        )
        await integration._async_refresh_self_test(entry)

        assert entry.runtime_data.self_test_status == {}
        assert entry.runtime_data.self_test_status_updated_at is None

    asyncio.run(_run())


def test_sync_device_ui_patch_refreshes_status(monkeypatch: pytest.MonkeyPatch) -> None:
    import custom_components.bticino_c300x.qml_patch as qml_patch

    async def refresh_qml_patch_status(_entry: Any) -> dict[str, bool]:
        return {"applied": True}

    monkeypatch.setattr(qml_patch, "async_refresh_qml_patch_status", refresh_qml_patch_status)
    entry = _entry()
    entry.runtime_data = SimpleNamespace(
        capabilities={"maintenance": {"supported": True, "qml_status": True}},
        qml_patch_diagnostics=C300XOperationDiagnostics(),
        qml_patch_status={},
    )

    asyncio.run(integration._async_sync_device_ui_patch(entry))

    assert entry.runtime_data.qml_patch_status == {"applied": True}
    assert entry.runtime_data.qml_patch_diagnostics.last_error is None


def test_sync_device_ui_patch_skips_unsupported_or_failed_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import custom_components.bticino_c300x.qml_patch as qml_patch

    async def refresh_qml_patch_status(_entry: Any) -> dict[str, bool]:
        raise integration.C300XAgentApiError("failed")

    monkeypatch.setattr(qml_patch, "async_refresh_qml_patch_status", refresh_qml_patch_status)

    unsupported_entry = _entry()
    unsupported_entry.runtime_data = SimpleNamespace(
        capabilities={},
        qml_patch_diagnostics=C300XOperationDiagnostics(),
        qml_patch_status={"old": True},
    )
    asyncio.run(integration._async_sync_device_ui_patch(unsupported_entry))
    assert unsupported_entry.runtime_data.qml_patch_status == {}

    failed_entry = _entry()
    failed_entry.runtime_data = SimpleNamespace(
        capabilities={"maintenance": {"supported": True, "qml_status": True}},
        qml_patch_diagnostics=C300XOperationDiagnostics(),
        qml_patch_status={"old": True},
    )
    asyncio.run(integration._async_sync_device_ui_patch(failed_entry))
    assert failed_entry.runtime_data.qml_patch_status == {"old": True}
    assert (
        failed_entry.runtime_data.qml_patch_diagnostics.last_error
        == "C300XAgentApiError: failed"
    )


def test_display_bridge_tracking_and_notify_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    dispatch_unsubs: list[str] = []
    state_unsubs: list[str] = []
    dispatcher_callbacks: list[Any] = []
    state_callbacks: list[Any] = []
    listened_events: list[str] = []

    monkeypatch.setattr(
        runtime_manager,
        "_async_schedule_display_bridge_notify",
        lambda *_args: calls.append("notify"),
    )

    import homeassistant.helpers.dispatcher as dispatcher

    class FakeBus:
        def async_listen(self, event_type: str, callback: Any) -> Any:
            listened_events.append(event_type)
            state_callbacks.append(callback)
            return lambda: state_unsubs.append("state")

    def connect_dispatcher(_hass: Any, _signal: str, callback: Any) -> Any:
        dispatcher_callbacks.append(callback)
        return lambda: dispatch_unsubs.append("dispatch")

    monkeypatch.setattr(
        dispatcher,
        "async_dispatcher_connect",
        connect_dispatcher,
        raising=False,
    )

    entry = _entry(
        options={
            CONF_DEVICE_UI_ENABLED: True,
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.home",
        }
    )
    hass = SimpleNamespace(
        data={
            "alarmo": {
                "sensor_handler": SimpleNamespace(
                    _config={
                        "binary_sensor.front_door": {"type": "door"},
                        "binary_sensor.window": {"type": "window"},
                    }
                )
            }
        },
        bus=FakeBus(),
    )
    unsubscribe = integration._async_track_display_bridge_updates(hass, entry)

    assert callable(unsubscribe)
    assert listened_events == ["state_changed"]
    assert calls == []

    state_callbacks[0](SimpleNamespace(data={"entity_id": "sensor.temperature"}))
    assert calls == []

    state_callbacks[0](SimpleNamespace(data={"entity_id": "binary_sensor.unlisted"}))
    assert calls == []

    state_callbacks[0](SimpleNamespace(data={"entity_id": "binary_sensor.front_door"}))
    assert calls == ["notify"]

    state_callbacks[0](
        SimpleNamespace(data={"entity_id": "alarm_control_panel.home"})
    )
    assert calls == ["notify", "notify"]

    dispatcher_callbacks[0]()
    assert calls == ["notify", "notify", "notify"]
    unsubscribe()
    assert state_unsubs == ["state"]
    assert dispatch_unsubs == ["dispatch"]


def test_display_bridge_tracking_skips_when_disabled_or_unconfigured() -> None:
    assert (
        integration._async_track_display_bridge_updates(
            "hass",
            _entry(options={CONF_DEVICE_UI_ENABLED: False}),
        )
        is None
    )
    assert (
        integration._async_track_display_bridge_updates(
            "hass",
            _entry(options={CONF_DEVICE_UI_ENABLED: True}),
        )
        is None
    )


def test_display_bridge_notify_skips_offline_entries() -> None:
    jobs: list[Any] = []
    entry = _entry()
    entry.runtime_data = SimpleNamespace(
        connection_state=SimpleNamespace(available=False),
    )
    hass = SimpleNamespace(add_job=lambda *args: jobs.append(args))

    integration._async_schedule_display_bridge_notify(hass, entry)

    assert jobs == []


def test_display_bridge_notify_requires_active_ui_waiter() -> None:
    calls: list[str] = []

    class FakeApi:
        def __init__(self, waiters: int | None) -> None:
            self.waiters = waiters

        async def async_diagnostics(self) -> dict[str, Any]:
            calls.append(f"diagnostics:{self.waiters}")
            return {"ui_event_waiters": self.waiters}

        async def async_notify_display_bridge_event(self, topic: str) -> dict[str, Any]:
            calls.append(f"event:{topic}")
            return {"ok": True}

    entry = _entry()
    entry.runtime_data = SimpleNamespace(api=FakeApi(0))
    asyncio.run(integration._async_notify_display_bridge_alarm_if_listening(entry))

    entry.runtime_data.api = FakeApi(1)
    asyncio.run(integration._async_notify_display_bridge_alarm_if_listening(entry))

    assert calls == ["diagnostics:0", "diagnostics:1", "event:alarm"]


def test_display_bridge_notify_coalesces_inflight_jobs() -> None:
    calls: list[str] = []
    jobs: list[tuple[Any, ...]] = []

    class FakeApi:
        async def async_diagnostics(self) -> dict[str, Any]:
            calls.append("diagnostics")
            return {"ui_event_waiters": 0}

    runtime_data = SimpleNamespace(
        api=FakeApi(),
        connection_state=SimpleNamespace(available=True),
        display_bridge_alarm_notify_pending=False,
    )
    entry = _entry()
    entry.runtime_data = runtime_data
    hass = SimpleNamespace(add_job=lambda *args: jobs.append(args))

    integration._async_schedule_display_bridge_notify(hass, entry)
    integration._async_schedule_display_bridge_notify(hass, entry)

    assert len(jobs) == 1
    assert runtime_data.display_bridge_alarm_notify_pending is True

    asyncio.run(jobs[0][0](*jobs[0][1:]))

    assert calls == ["diagnostics"]
    assert runtime_data.display_bridge_alarm_notify_pending is False


def test_display_bridge_notify_ignores_stale_runtime() -> None:
    calls: list[str] = []

    class FakeApi:
        async def async_diagnostics(self) -> dict[str, Any]:
            calls.append("diagnostics")
            return {"ui_event_waiters": 1}

        async def async_notify_display_bridge_event(self, topic: str) -> dict[str, Any]:
            calls.append(f"event:{topic}")
            return {"ok": True}

    old_runtime = SimpleNamespace(
        api=FakeApi(),
        display_bridge_alarm_notify_pending=True,
    )
    entry = _entry()
    entry.runtime_data = SimpleNamespace(api=FakeApi())

    asyncio.run(
        integration._async_notify_display_bridge_alarm_if_listening(
            entry,
            old_runtime,  # type: ignore[arg-type]
        )
    )

    assert calls == []
    assert old_runtime.display_bridge_alarm_notify_pending is False


def test_remove_stale_gui_entities_removes_registry_and_state(monkeypatch) -> None:  # noqa: ANN001
    import homeassistant.helpers.entity_registry as entity_registry

    class FakeRegistry:
        def __init__(self) -> None:
            self.removed: list[str] = []

        def async_get_entity_id(
            self,
            platform: str,
            domain: str,
            unique_id: str,
        ) -> str | None:
            assert domain == DOMAIN
            if unique_id.endswith("delete_latest_text_memo"):
                return f"{platform}.delete_latest_text_memo"
            return None

        def async_remove(self, entity_id: str) -> None:
            self.removed.append(entity_id)

    registry = FakeRegistry()
    state_removed: list[str] = []
    monkeypatch.setattr(entity_registry, "async_get", lambda _hass: registry)
    hass = SimpleNamespace(
        states=SimpleNamespace(async_remove=lambda entity_id: state_removed.append(entity_id))
    )
    entry = _entry(options={CONF_DEVICE_UI_ENABLED: False})

    integration._async_remove_stale_gui_dependent_entities(hass, entry)

    assert registry.removed == ["button.delete_latest_text_memo"]
    assert state_removed == ["button.delete_latest_text_memo"]


def test_unload_entry_cleans_runtime_callbacks_and_tasks() -> None:
    cancelled: list[str] = []
    callbacks: list[str] = []
    entry = _entry()
    entry.runtime_data = SimpleNamespace(
        loaded_platforms=("sensor", "camera"),
        unregister_event_registration=lambda: callbacks.append("registration"),
        unregister_display_bridge_updates=lambda: callbacks.append("display"),
        unregister_event_webhook=lambda: callbacks.append("event-webhook"),
        unregister_webhook=lambda: callbacks.append("webhook"),
        connection_state=SimpleNamespace(
            expire_unavailable=lambda: callbacks.append("expire")
        ),
        memos_refresh_task=SimpleNamespace(cancel=lambda: cancelled.append("memos")),
        answering_machine_messages_refresh_task=SimpleNamespace(
            cancel=lambda: cancelled.append("messages")
        ),
    )
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_unload_platforms=lambda _entry, platforms: _async_value(
                platforms == ("sensor", "camera")
            )
        ),
        data={
            DOMAIN: {
                DATA_RUNTIME_ENTRIES: {
                    entry.entry_id: entry.runtime_data,
                }
            }
        },
    )

    assert asyncio.run(integration.async_unload_entry(hass, entry)) is True

    assert callbacks == ["registration", "display", "expire", "event-webhook", "webhook"]
    assert cancelled == ["memos", "messages"]
    assert entry.runtime_data.memos_refresh_task is None
    assert entry.runtime_data.answering_machine_messages_refresh_task is None
    assert hass.data[DOMAIN][DATA_RUNTIME_ENTRIES] == {}


def test_unload_entry_preserves_runtime_state_when_platform_unload_fails() -> None:
    cancelled: list[str] = []
    callbacks: list[str] = []
    entry = _entry()
    entry.runtime_data = SimpleNamespace(
        loaded_platforms=("sensor", "camera"),
        unregister_event_registration=lambda: callbacks.append("registration"),
        unregister_display_bridge_updates=lambda: callbacks.append("display"),
        unregister_event_webhook=lambda: callbacks.append("event-webhook"),
        unregister_webhook=lambda: callbacks.append("webhook"),
        connection_state=SimpleNamespace(
            expire_unavailable=lambda: callbacks.append("expire")
        ),
        memos_refresh_task=SimpleNamespace(cancel=lambda: cancelled.append("memos")),
        answering_machine_messages_refresh_task=SimpleNamespace(
            cancel=lambda: cancelled.append("messages")
        ),
    )
    entry_locks.entry_lock(entry.entry_id, "message_refresh:memos")
    entry_locks.entry_lock(entry.entry_id, "ring_capture")
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_unload_platforms=lambda _entry, _platforms: _async_value(False)
        ),
        data={
            DOMAIN: {
                DATA_RUNTIME_ENTRIES: {
                    entry.entry_id: entry.runtime_data,
                }
            }
        },
    )

    assert asyncio.run(integration.async_unload_entry(hass, entry)) is False

    assert callbacks == []
    assert cancelled == []
    assert entry.runtime_data.memos_refresh_task is not None
    assert entry.runtime_data.answering_machine_messages_refresh_task is not None
    assert any(key[0] == entry.entry_id for key in entry_locks._locks)
    assert hass.data[DOMAIN][DATA_RUNTIME_ENTRIES] == {entry.entry_id: entry.runtime_data}


def test_startup_sync_stale_task_does_not_clear_new_runtime_task() -> None:
    async def _run() -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        repairs: list[str] = []
        dispatches: list[tuple[Any, ...]] = []

        async def _sync_device_state(self: runtime_manager.C300XRuntimeManager) -> None:
            started.set()
            await release.wait()

        def _repair(_hass: Any, entry: Any) -> None:
            repairs.append(entry.entry_id)

        def _dispatch(*args: Any) -> None:
            dispatches.append(args)

        _stub_homeassistant_http()
        dispatcher_module = sys.modules["homeassistant.helpers.dispatcher"]
        previous_dispatch = dispatcher_module.async_dispatcher_send
        dispatcher_module.async_dispatcher_send = _dispatch
        repair_module_name = "custom_components.bticino_c300x.repair_issues"
        previous_repair_module = sys.modules.get(repair_module_name)
        repair_module = types.ModuleType("custom_components.bticino_c300x.repair_issues")
        repair_module.async_sync_entry_repair_issues = _repair
        sys.modules[repair_module_name] = repair_module

        old_runtime = SimpleNamespace(startup_sync_task=None)
        new_task = SimpleNamespace(cancel=lambda: None)
        entry = _entry()
        entry.runtime_data = old_runtime
        hass = SimpleNamespace(async_create_task=asyncio.create_task)
        manager = runtime_manager.C300XRuntimeManager(hass, entry)
        original_sync = runtime_manager.C300XRuntimeManager.async_sync_device_state
        runtime_manager.C300XRuntimeManager.async_sync_device_state = _sync_device_state
        try:
            manager.async_schedule_startup_sync()
            old_task = old_runtime.startup_sync_task
            assert old_task is not None
            await started.wait()

            entry.runtime_data = SimpleNamespace(startup_sync_task=new_task)
            release.set()
            await old_task
        finally:
            runtime_manager.C300XRuntimeManager.async_sync_device_state = original_sync
            dispatcher_module.async_dispatcher_send = previous_dispatch
            if previous_repair_module is None:
                sys.modules.pop(repair_module_name, None)
            else:
                sys.modules[repair_module_name] = previous_repair_module

        assert old_runtime.startup_sync_task is None
        assert entry.runtime_data.startup_sync_task is new_task
        assert repairs == [entry.entry_id]
        assert dispatches

    asyncio.run(_run())


async def _async_value(value: Any) -> Any:
    return value


async def _async_empty(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    return {}


def _record_async(calls: list[str], value: str) -> Any:
    async def recorder(*_args: Any, **_kwargs: Any) -> None:
        calls.append(value)

    return recorder


def _entry(
    *,
    data: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        entry_id="entry-1",
        domain=DOMAIN,
        data=data or {},
        options=options or {},
    )


def _hass_with_config_updates() -> tuple[SimpleNamespace, list[dict[str, Any]]]:
    updates: list[dict[str, Any]] = []

    def _update_entry(entry: SimpleNamespace, **kwargs: Any) -> None:
        updates.append(kwargs)
        if "data" in kwargs:
            entry.data = kwargs["data"]
        if "options" in kwargs:
            entry.options = kwargs["options"]

    return (
        SimpleNamespace(
            config=SimpleNamespace(location_name="HA Test"),
            config_entries=SimpleNamespace(async_update_entry=_update_entry),
        ),
        updates,
    )


class _ActivationApi:
    def __init__(
        self,
        status: dict[str, Any],
        *,
        items: list[dict[str, Any]] | None = None,
        error: type[Exception] | None = None,
    ) -> None:
        self._status = status
        self._items = list(items or [])
        self._error = error
        self.configured: list[tuple[bool, bool, list[dict[str, Any]]]] = []

    async def async_auth_config_status(self) -> dict[str, Any]:
        if self._error is not None:
            raise self._error("unsupported")
        return self._status

    async def async_activations(self) -> dict[str, Any]:
        if self._error is not None:
            raise self._error("unsupported")
        return {"items": [{"source": "config", **item} for item in self._items]}

    async def async_configure_device_activations(
        self,
        *,
        enabled: bool,
        auto_discover: bool,
        items: list[dict[str, Any]],
    ) -> None:
        self.configured.append((enabled, auto_discover, items))
        self._status.update(
            {
                "activations_enabled": enabled,
                "activations_auto_discover": auto_discover,
            }
        )
        self._items = list(items)


class _DisplayBridgeApi:
    def __init__(self, status: dict[str, Any], *, error: Exception | None = None) -> None:
        self._status = status
        self._error = error
        self.configured: list[tuple[bool, str, str]] = []

    async def async_display_bridge_status(self) -> dict[str, Any]:
        if self._error is not None:
            raise self._error
        return self._status

    async def async_configure_display_bridge(
        self,
        *,
        enabled: bool,
        webhook_url: str,
        shared_secret: str,
    ) -> None:
        self.configured.append((enabled, webhook_url, shared_secret))


class _DeviceUserApi:
    def __init__(self, status: dict[str, Any], *, error: Exception | None = None) -> None:
        self._status = status
        self._error = error
        self._ensure_status: dict[str, Any] | None = None
        self.ensure_labels: list[str] = []

    async def async_device_user_status(self) -> dict[str, Any]:
        if self._error is not None:
            raise self._error
        return self._status

    async def async_ensure_homeassistant_user(self, *, account_label: str) -> dict[str, Any]:
        self.ensure_labels.append(account_label)
        if self._ensure_status is not None:
            return self._ensure_status
        return {
            "homeassistant_user_present": True,
            "media_identity_available": True,
            "routes_consistent": True,
            "device_routing_applied": True,
            "media_user_label_applied": True,
        }


class _SelfTestApi:
    def __init__(
        self,
        status: dict[str, Any],
        *,
        error: Exception | None = None,
    ) -> None:
        self._status = status
        self._error = error

    async def async_self_test(self) -> dict[str, Any]:
        if self._error is not None:
            raise self._error
        return self._status


class _SetupApi:
    def __init__(
        self,
        session: Any,
        base_url: str,
        token: str,
        maintenance_token: str,
    ) -> None:
        self.session = session
        self.base_url = base_url
        self.token = token
        self.maintenance_token = maintenance_token

    async def async_validate_setup(self) -> dict[str, Any]:
        return {
            "version": "1.2.0",
            "capabilities": {"doorbell_video": {"supported": True}},
        }

    async def async_self_test(self) -> dict[str, Any]:
        return {"ok": True, "checks": {}}


class _RecoveringSetupApi:
    def __init__(self) -> None:
        self.calls = 0

    async def async_validate_setup(self) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            raise integration.C300XAgentApiError("offline")
        return {"version": "1.2.0"}
