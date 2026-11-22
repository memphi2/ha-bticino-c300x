"""C100X first setup needs explicit consent before enabling media or SIP writes."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.bticino_c300x import config_flow
from custom_components.bticino_c300x.config_flow import BticinoC300XConfigFlow
from custom_components.bticino_c300x.const import (
    CONF_CREATE_HOMEASSISTANT_USER,
    CONF_VIDEO_ENABLED,
)
from custom_components.bticino_c300x.runtime_manager import _async_sync_device_user


def setup_flow(monkeypatch):
    flow = BticinoC300XConfigFlow()
    flow._setup_connection = {"agent_host": "c100x.invalid"}
    monkeypatch.setattr(flow, "async_show_form", lambda **values: values)
    monkeypatch.setattr(flow, "async_step_user_device_activations", AsyncMock())
    monkeypatch.setattr(flow, "async_step_user_visitor_snapshot", AsyncMock())
    return flow


def test_initial_form_defaults_do_not_enable_media(monkeypatch):
    flow = setup_flow(monkeypatch)
    form = asyncio.run(flow.async_step_user_features())
    defaults = form["data_schema"]({})
    assert defaults[CONF_VIDEO_ENABLED] is False
    assert CONF_CREATE_HOMEASSISTANT_USER not in defaults


@pytest.mark.parametrize("values", [{}, {CONF_VIDEO_ENABLED: False}])
def test_default_setup_cannot_provision_device_user(monkeypatch, values):
    flow = setup_flow(monkeypatch)
    asyncio.run(flow.async_step_user_features(values))
    assert flow._setup_feature_data[CONF_VIDEO_ENABLED] is False
    assert flow._setup_feature_data[CONF_CREATE_HOMEASSISTANT_USER] is False
    flow.async_step_user_device_activations.assert_awaited_once()
    flow.async_step_user_visitor_snapshot.assert_not_awaited()

    api = AsyncMock()
    entry = SimpleNamespace(
        data=flow._setup_feature_data,
        options={},
        runtime_data=SimpleNamespace(api=api),
    )
    asyncio.run(_async_sync_device_user(SimpleNamespace(), entry))
    assert api.mock_calls == []


@pytest.mark.parametrize("create_user", [None, False, True])
def test_video_enable_does_not_implicitly_allow_sip_writes(monkeypatch, create_user):
    flow = setup_flow(monkeypatch)
    values = {CONF_VIDEO_ENABLED: True}
    if create_user is not None:
        values[CONF_CREATE_HOMEASSISTANT_USER] = create_user
    asyncio.run(flow.async_step_user_features(values))
    assert flow._setup_feature_data[CONF_VIDEO_ENABLED] is True
    assert flow._setup_feature_data[CONF_CREATE_HOMEASSISTANT_USER] is (create_user is True)
    flow.async_step_user_visitor_snapshot.assert_awaited_once()


def test_error_form_keeps_media_user_opt_in(monkeypatch):
    flow = setup_flow(monkeypatch)
    form = asyncio.run(flow.async_step_user_features({
        CONF_VIDEO_ENABLED: True,
        "doorstation_audio_gain_db": "invalid",
    }))
    assert form["errors"]
    assert form["data_schema"]({})[CONF_CREATE_HOMEASSISTANT_USER] is False


@pytest.mark.parametrize("kind", ["options", "reconfigure"])
@pytest.mark.parametrize("previous_consent", [None, False, True])
def test_enabling_video_preserves_existing_consent(monkeypatch, kind, previous_consent):
    data = {"agent_host": "c100x.invalid", CONF_VIDEO_ENABLED: False}
    if previous_consent is not None:
        data[CONF_CREATE_HOMEASSISTANT_USER] = previous_consent
    entry = SimpleNamespace(data=data, options={})
    monkeypatch.setattr(config_flow, "_async_qml_patch_description_placeholders", AsyncMock(return_value={}))
    if kind == "options":
        flow = config_flow.BticinoC300XOptionsFlow(entry)
        monkeypatch.setattr(flow, "_async_store_options", AsyncMock())
        step = flow.async_step_features
    else:
        flow = BticinoC300XConfigFlow()
        monkeypatch.setattr(flow, "_get_reconfigure_entry", lambda: entry)
        monkeypatch.setattr(flow, "async_step_reconfigure_visitor_snapshot", AsyncMock())
        step = flow.async_step_reconfigure_features
    monkeypatch.setattr(flow, "async_show_form", lambda **values: values)
    form = asyncio.run(step())
    values = form["data_schema"]({CONF_VIDEO_ENABLED: True})
    assert CONF_CREATE_HOMEASSISTANT_USER not in values
    asyncio.run(step(values))
    saved = (flow._async_store_options.await_args.args[0] if kind == "options"
             else flow._reconfigure_feature_data)
    assert saved[CONF_CREATE_HOMEASSISTANT_USER] is (previous_consent is True)
    api = AsyncMock()
    api.async_device_user_status.return_value = {"homeassistant_user_present": False}
    api.async_ensure_homeassistant_user.return_value = {"homeassistant_user_present": False}
    entry.options = saved
    entry.runtime_data = SimpleNamespace(api=api, capabilities={"device_user": {"supported": True}})
    asyncio.run(_async_sync_device_user(SimpleNamespace(), entry))
    assert api.async_ensure_homeassistant_user.await_count == int(previous_consent is True)
