"""C100X first setup needs explicit consent before enabling media or SIP writes."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

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
