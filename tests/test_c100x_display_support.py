"""Unsupported display settings stay inert, including across offline restarts."""

import asyncio
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.bticino_c300x import config_flow, notify, runtime_manager
from custom_components.bticino_c300x.capabilities import (
    entry_device_ui_configured,
    entry_device_ui_enabled,
    entry_device_ui_enabled_or_patch_active,
)
from custom_components.bticino_c300x.config_flow_display_menu import display_menu
from custom_components.bticino_c300x.config_flow_features import options_menu
from custom_components.bticino_c300x.const import CONF_DEVICE_UI_ENABLED
from custom_components.bticino_c300x.display_alerts import async_send_display_alert
from custom_components.bticino_c300x.display_patch_sync import (
    async_apply_display_setting,
)
from custom_components.bticino_c300x.display_support import (
    DISPLAY_SUPPORTED,
    device_display_support,
    entry_display_supported,
    remember_display_support,
)

CAPABILITIES = {
    "display_bridge": {"supported": False}, "display_alerts": False,
    "maintenance": {"supported": True, "qml_patch": False, "qml_restore": False},
}
INFO = {"model": "C100X", "display_kind": "qt5_ondisk", "capabilities": CAPABILITIES}


def entry():
    return SimpleNamespace(
        entry_id="c100x", data={}, update_listeners=[],
        options=MappingProxyType({CONF_DEVICE_UI_ENABLED: True, "dashboard_pages": [
            {"name": "Lights", "order": 0},
        ]}),
        runtime_data=SimpleNamespace(
            agent_info=INFO, capabilities=CAPABILITIES,
            qml_patch_status={"patched": True}, resources=SimpleNamespace(),
        ),
    )


def test_saved_preferences_and_stale_patch_status_do_not_enable_display():
    device = entry()
    assert entry_device_ui_configured(device) is True
    assert not entry_device_ui_enabled(device)
    assert not entry_device_ui_enabled_or_patch_active(device)
    assert "display" not in options_menu(device)
    assert "dashboard_alarm" in options_menu(device)
    assert display_menu(device) == ["dashboard_alarm"]


def test_no_notify_registration_bridge_or_patch_io_for_unsupported_display(monkeypatch):
    device = entry()
    setup = AsyncMock(side_effect=AssertionError("unexpected notify setup"))
    monkeypatch.setattr(notify, "async_setup_component", setup)
    asyncio.run(notify.async_setup_notify(None, device))
    asyncio.run(runtime_manager._async_configure_display_bridge(None, device, object()))
    assert asyncio.run(async_apply_display_setting(None, device)) is False
    assert runtime_manager._async_track_display_bridge_updates(None, device) is None
    assert device.runtime_data.resources.display_bridge_registration_pending is False
    with pytest.raises(ServiceValidationError, match="disabled"):
        asyncio.run(async_send_display_alert(None, device, "test"))
    setup.assert_not_called()


def test_remembered_exclusion_survives_offline_without_erasing_preferences():
    device = entry()
    before = dict(device.options)
    updates = []

    def update(target, *, data):
        updates.append(data)
        target.data = data

    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update))
    remember_display_support(hass, device, INFO)
    remember_display_support(hass, device, INFO)
    remember_display_support(hass, device, {"offline_error": "unreachable"})
    assert updates == [{DISPLAY_SUPPORTED: False}]
    device.runtime_data = None
    assert not entry_display_supported(device)
    assert not entry_device_ui_enabled_or_patch_active(device)
    assert dict(device.options) == before
    remember_display_support(hass, device, {"capabilities": {"display_bridge": {"supported": True}}})
    assert entry_display_supported(device)


@pytest.mark.parametrize("setup", [
    INFO, {"model": "C100X"}, {"capabilities": CAPABILITIES},
])
def test_setup_skips_display_and_never_accepts_an_enabled_submission(setup):
    flow = config_flow.BticinoC300XConfigFlow()
    flow._setup_feature_data = {"video_enabled": True}
    flow._setup_agent_info = setup

    async def create(_errors):
        return flow._setup_dashboard_input

    flow._async_create_setup_entry_from_dashboard = create
    result = asyncio.run(flow.async_step_user_dashboard({CONF_DEVICE_UI_ENABLED: True}))
    assert result[CONF_DEVICE_UI_ENABLED] is False


def test_setup_identity_read_caches_capabilities(monkeypatch):
    monkeypatch.setattr(config_flow, "_async_agent_setup_data", AsyncMock(return_value={
        **INFO, "device_id": "c300x-synthetic",
    }))
    captured = {}
    assert asyncio.run(config_flow._async_agent_stable_unique_id(
        None, {}, setup_data_target=captured,
    )) == "c300xsynthetic"
    assert device_display_support(captured) is False


@pytest.mark.parametrize("step", [
    "dashboard", "dashboard_pages", "dashboard_entity_display", "dashboard_page_list", "page_new",
])
def test_direct_options_steps_cannot_enable_or_edit_unsupported_display(step):
    from test_display_settings import _OptionsAreas
    from test_executor import run

    device = entry()
    before = dict(device.options)
    flow = _OptionsAreas(device)._flow()
    result = run(getattr(flow, "async_step_" + step)({CONF_DEVICE_UI_ENABLED: True}))
    assert result["type"] == "abort"
    assert result["reason"] == "unsupported_display"
    assert dict(device.options) == before


def test_reconfigure_skips_unsupported_display_without_erasing_saved_layouts():
    device = entry()
    flow = config_flow.BticinoC300XConfigFlow()
    flow._get_reconfigure_entry = lambda: device
    flow._reconfigure_feature_data = {"video_enabled": True}

    async def finish(_defaults, _errors):
        return flow._reconfigure_dashboard_input

    flow._async_finish_reconfigure_from_dashboard = finish
    result = asyncio.run(flow.async_step_reconfigure_dashboard())
    assert result["dashboard_pages"] == device.options["dashboard_pages"]
    assert not entry_device_ui_enabled(device)


def test_unknown_older_agent_keeps_existing_behavior():
    device = entry()
    device.runtime_data = None
    assert entry_display_supported(device)
    assert entry_device_ui_enabled(device)
    assert device_display_support({}) is None


CONFIRMED = {
    **CAPABILITIES, "display_bridge": {"supported": True}, "display_alerts": True,
    "c100x_display": {"supported": True, "status_known": True, "phase": "installed", "confirmed": True},
}


@pytest.mark.parametrize("c100x_display,expected", [
    ({"supported": True, "status_known": True, "phase": "installed", "confirmed": True}, True),
    ({"supported": True, "status_known": True, "phase": "trial", "confirmed": False}, False),
    ({"supported": True, "status_known": False, "phase": "unknown", "confirmed": False}, None),
    (None, False),
])
def test_c100x_display_counts_once_its_adapter_is_confirmed(c100x_display, expected):
    capabilities = {**CONFIRMED, "c100x_display": c100x_display}
    if c100x_display is None:
        del capabilities["c100x_display"]
    assert device_display_support({**INFO, "capabilities": capabilities}) is expected
    # The bridge must agree: a confirmed status without it is not enough.
    capabilities["display_bridge"] = {"supported": False}
    assert device_display_support({**INFO, "capabilities": capabilities}) is (None if expected is None else False)


def test_first_confirmation_switches_the_device_ui_setting_on():
    device = entry()
    device.options = MappingProxyType({CONF_DEVICE_UI_ENABLED: False})
    updates = []

    def update(target, *, data, options=None):
        updates.append((data, options))
        target.data = data
        if options is not None:
            target.options = MappingProxyType(options)

    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update))
    remember_display_support(hass, device, INFO)
    assert updates == [({DISPLAY_SUPPORTED: False}, None)]
    confirmed = {**INFO, "capabilities": CONFIRMED}
    device.runtime_data.agent_info = confirmed
    device.runtime_data.capabilities = CONFIRMED
    remember_display_support(hass, device, confirmed)
    assert updates[-1] == ({DISPLAY_SUPPORTED: True}, {CONF_DEVICE_UI_ENABLED: True})
    assert entry_device_ui_enabled(device)
    # Only the change to confirmed does it; a later off stays off.
    device.options = MappingProxyType({CONF_DEVICE_UI_ENABLED: False})
    remember_display_support(hass, device, confirmed)
    assert len(updates) == 2
    assert not entry_device_ui_enabled(device)
    # An unknown status keeps the remembered fact.
    unknown = {**CONFIRMED, "c100x_display": {"supported": True, "status_known": False}}
    remember_display_support(hass, device, {**INFO, "capabilities": unknown})
    assert len(updates) == 2


@pytest.mark.parametrize("model,offered", [("C100X", False), ("C300X", True)])
def test_home_button_layout_is_offered_only_where_the_display_patch_uses_it(model, offered):
    from test_display_settings import _OptionsAreas
    from test_executor import run

    device = entry()
    device.runtime_data.agent_info = {"model": model, "capabilities": CONFIRMED}
    device.runtime_data.capabilities = CONFIRMED
    device.runtime_data.qml_patch_status = {}
    device.options = MappingProxyType({**device.options, "dashboard_dynamic_homepage": False})
    areas = _OptionsAreas(device)
    form = run(areas._flow().async_step_dashboard())
    assert form["type"] == "form"
    fields = {str(key) for key in form["data_schema"].schema}
    assert ("dashboard_dynamic_homepage" in fields) is offered
    assert "dashboard_navigation" in fields
    # Saving the C100X form keeps the hidden C300X value as it was.
    assert run(areas._flow().async_step_dashboard({CONF_DEVICE_UI_ENABLED: True}))["type"] == "menu"
    assert device.options["dashboard_dynamic_homepage"] is False



def test_a_failed_identity_read_after_install_skips_the_display_steps(monkeypatch):
    # The installer accepts only a C100X. When the identity read after it
    # fails, setup must not offer the display steps that C100X lacks.
    flow = config_flow.BticinoC300XConfigFlow()
    flow.hass = SimpleNamespace()
    flow.context = {"source": "user"}
    flow._setup_connection = {"name": "Door", "agent_host": "a.local", "agent_port": 8091}
    flow._async_abort_if_manual_setup_duplicate = AsyncMock()
    flow._async_adopt_agent_unique_id = AsyncMock()  # the read failed: nothing adopted
    flow.async_abort = lambda **kwargs: kwargs
    monkeypatch.setattr(config_flow, "async_ensure_installer_dependencies", AsyncMock())
    monkeypatch.setattr(config_flow, "async_install_device_agent", AsyncMock())
    monkeypatch.setattr(config_flow, "_async_probe_agent", AsyncMock(return_value="reachable"))
    migrate = AsyncMock()
    monkeypatch.setattr(config_flow, "async_migrate_legacy_mqtt_for_connection", migrate)
    result = asyncio.run(flow.async_step_bootstrap_install({}))
    assert result["step_id"] == "user_features"
    migrate.assert_not_awaited()
    flow._setup_feature_data = {"video_enabled": True}

    async def create(_errors):
        return flow._setup_dashboard_input

    flow._async_create_setup_entry_from_dashboard = create
    result = asyncio.run(flow.async_step_user_dashboard())
    assert result[CONF_DEVICE_UI_ENABLED] is False
    flow._setup_dashboard_input = {CONF_DEVICE_UI_ENABLED: True}
    assert asyncio.run(flow.async_step_user_dashboard_pages())["reason"] == "unsupported_display"
