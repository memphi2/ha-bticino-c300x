from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace
from typing import Any

import pytest

import custom_components.bticino_c300x as integration
from custom_components.bticino_c300x.const import (
    CONF_AGENT_HOST,
    CONF_AGENT_TOKEN,
    CONF_ALARM_ENTITY_ID,
    CONF_CREATE_HOMEASSISTANT_USER,
    CONF_DEVICE_ACTIVATION_MODE,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_ADDRESS,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P,
    CONF_DEVICE_UI_ENABLED,
    CONF_EVENT_WEBHOOK_ID,
    CONF_EVENT_WEBHOOK_TOKEN,
    CONF_MAINTENANCE_TOKEN,
    CONF_SHARED_SECRET,
    CONF_VIDEO_ENABLED,
    CONF_WEBHOOK_ID,
    DATA_RUNTIME_ENTRIES,
    DEFAULT_STAIR_LIGHT_ADDRESS,
    DEVICE_ACTIVATION_MODE_MANUAL,
    DOMAIN,
)
from custom_components.bticino_c300x.data import (
    C300XCallbackDiagnostics,
    C300XConnectionState,
    C300XOperationDiagnostics,
)


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
    monkeypatch.setitem(sys.modules, "custom_components.bticino_c300x.camera", camera)
    hass = SimpleNamespace(data={})

    assert asyncio.run(integration.async_setup(hass, {})) is True

    assert hass.data[DOMAIN] == {}
    assert calls == ["blueprints", "frontend", "services", "ws"]


def test_setup_entry_builds_runtime_and_forwards_platforms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
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
    monkeypatch.setattr(integration, "_async_configure_device_activations", _record_async(calls, "activations"))
    monkeypatch.setattr(integration, "_async_configure_display_bridge", _record_async(calls, "display"))
    monkeypatch.setattr(integration, "_async_sync_device_ui_patch", _record_async(calls, "qml"))
    monkeypatch.setattr(integration, "_async_sync_device_user", _record_async(calls, "user"))
    monkeypatch.setattr(
        integration,
        "_async_track_display_bridge_updates",
        lambda _hass, _entry: lambda: calls.append("display-unregister"),
    )
    monkeypatch.setattr(
        integration,
        "_async_remove_stale_gui_dependent_entities",
        lambda _hass, _entry: calls.append("remove-stale"),
    )
    monkeypatch.setattr(integration, "C300XAgentApi", _SetupApi)

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
        "activations",
        "display",
        "qml",
        "user",
        "remove-stale",
        "repair-sync",
        "services",
        "media-view",
        "forward:binary_sensor,button,event,sensor,select,switch,camera",
    ]
    assert entry.added_listeners


def test_setup_entry_rejects_missing_required_fields() -> None:
    hass = SimpleNamespace(data={})
    entry = _entry(data={})

    assert asyncio.run(integration.async_setup_entry(hass, entry)) is False


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
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_ADDRESS: "",
        }
    )

    assert integration._entry_activation_config(entry) == (
        True,
        False,
        DEFAULT_STAIR_LIGHT_ADDRESS,
    )


def test_configure_device_activations_updates_only_when_needed() -> None:
    entry = _entry(
        options={
            CONF_DEVICE_ACTIVATION_MODE: DEVICE_ACTIVATION_MODE_MANUAL,
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_ADDRESS: "77",
        }
    )
    api = _ActivationApi(
        {
            "activations_enabled": True,
            "activations_auto_discover": True,
            "activation_stair_light_address": "77",
        }
    )

    asyncio.run(integration._async_configure_device_activations(entry, api))

    assert api.configured == [(True, False, "77")]


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
            "activation_stair_light_address": "21",
        }
    )

    asyncio.run(integration._async_configure_device_activations(entry, api))

    assert api.configured == []


def test_configure_device_activations_ignores_agent_errors() -> None:
    entry = _entry(
        options={
            CONF_DEVICE_ACTIVATION_MODE: DEVICE_ACTIVATION_MODE_MANUAL,
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_ADDRESS: "77",
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


def test_sync_device_user_refreshes_missing_media_user_without_repair() -> None:
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
    hass = SimpleNamespace(config=SimpleNamespace(location_name="HA Test"))

    asyncio.run(integration._async_sync_device_user(hass, entry))

    assert entry.runtime_data.api.ensure_labels == []
    assert entry.runtime_data.device_user_status == {"homeassistant_user_present": False}
    assert entry.runtime_data.device_user_status_updated_at is not None


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
        hass = SimpleNamespace(config=SimpleNamespace(location_name="HA Test"))

        asyncio.run(integration._async_sync_device_user(hass, entry))

        assert entry.runtime_data.api.ensure_labels == []
        assert entry.runtime_data.device_user_status == {}


def test_sync_device_user_refreshes_existing_status_without_repair() -> None:
    entry = _entry(
        options={
            CONF_VIDEO_ENABLED: True,
            CONF_CREATE_HOMEASSISTANT_USER: True,
        }
    )
    status = {
        "homeassistant_user_present": True,
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
    hass = SimpleNamespace(config=SimpleNamespace(location_name="HA Test"))

    asyncio.run(integration._async_sync_device_user(hass, entry))

    assert entry.runtime_data.api.ensure_labels == []
    assert entry.runtime_data.device_user_status == status
    assert entry.runtime_data.device_user_status_updated_at is not None


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
        hass = SimpleNamespace(config=SimpleNamespace(location_name="HA Test"))

        asyncio.run(integration._async_sync_device_user(hass, entry))

        assert entry.runtime_data.device_user_status == {}


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
    hass = SimpleNamespace(config=SimpleNamespace(location_name="HA Test"))

    asyncio.run(integration._async_sync_device_user(hass, entry))

    assert entry.runtime_data.device_user_status == status
    assert entry.runtime_data.api.ensure_labels == []


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

    monkeypatch.setattr(
        integration,
        "_async_schedule_display_bridge_notify",
        lambda *_args: calls.append("notify"),
    )

    import homeassistant.helpers.dispatcher as dispatcher
    import homeassistant.helpers.event as event_helper

    def track_state_change(_hass: Any, _entities: Any, callback: Any) -> Any:
        callback(None)
        return lambda: state_unsubs.append("state")

    def connect_dispatcher(_hass: Any, _signal: str, callback: Any) -> Any:
        callback()
        return lambda: dispatch_unsubs.append("dispatch")

    monkeypatch.setattr(
        event_helper,
        "async_track_state_change_event",
        track_state_change,
        raising=False,
    )
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
    unsubscribe = integration._async_track_display_bridge_updates("hass", entry)

    assert callable(unsubscribe)
    assert calls == ["notify", "notify"]
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


class _ActivationApi:
    def __init__(
        self,
        status: dict[str, Any],
        *,
        error: type[Exception] | None = None,
    ) -> None:
        self._status = status
        self._error = error
        self.configured: list[tuple[bool, bool, str]] = []

    async def async_auth_config_status(self) -> dict[str, Any]:
        if self._error is not None:
            raise self._error("unsupported")
        return self._status

    async def async_configure_device_activations(
        self,
        *,
        enabled: bool,
        auto_discover: bool,
        stair_light_address: str,
    ) -> None:
        self.configured.append((enabled, auto_discover, stair_light_address))


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
        self.ensure_labels: list[str] = []

    async def async_device_user_status(self) -> dict[str, Any]:
        if self._error is not None:
            raise self._error
        return self._status

    async def async_ensure_homeassistant_user(self, *, account_label: str) -> dict[str, Any]:
        self.ensure_labels.append(account_label)
        return {
            "homeassistant_user_present": True,
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
