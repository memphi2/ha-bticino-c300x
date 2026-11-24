"""A C100X has the same media and HA-user setup defaults as a C300X.

Owner decision: video/media and the HA SIP user are ticked by default on both
models; the user can untick them, and a saved choice stays as it is.
"""

import asyncio
from pathlib import Path
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

C100X_INFO = {"model": "C100X", "display_kind": "qt5_ondisk"}
C300X_INFO = {"model": "C300X", "display_kind": "qt4_ondisk"}
MODELS = pytest.mark.parametrize("info", [C100X_INFO, C300X_INFO], ids=["c100x", "c300x"])


def setup_flow(monkeypatch, info):
    flow = BticinoC300XConfigFlow()
    flow._setup_connection = {"agent_host": "station.invalid"}
    flow._setup_agent_info = dict(info)
    monkeypatch.setattr(flow, "async_show_form", lambda **values: values)
    monkeypatch.setattr(flow, "async_step_user_device_activations", AsyncMock())
    monkeypatch.setattr(flow, "async_step_user_visitor_snapshot", AsyncMock())
    return flow


@MODELS
def test_setup_presets_media_and_the_user(monkeypatch, info):
    flow = setup_flow(monkeypatch, info)
    form = asyncio.run(flow.async_step_user_features())
    defaults = form["data_schema"]({})
    assert defaults[CONF_VIDEO_ENABLED] is True
    assert defaults[CONF_CREATE_HOMEASSISTANT_USER] is True
    asyncio.run(flow.async_step_user_features({}))
    assert flow._setup_feature_data[CONF_VIDEO_ENABLED] is True
    assert flow._setup_feature_data[CONF_CREATE_HOMEASSISTANT_USER] is True
    flow.async_step_user_visitor_snapshot.assert_awaited_once()


@MODELS
def test_unticked_setup_provisions_nothing(monkeypatch, info):
    flow = setup_flow(monkeypatch, info)
    asyncio.run(flow.async_step_user_features(
        {CONF_VIDEO_ENABLED: False, CONF_CREATE_HOMEASSISTANT_USER: False}))
    assert flow._setup_feature_data[CONF_VIDEO_ENABLED] is False
    assert flow._setup_feature_data[CONF_CREATE_HOMEASSISTANT_USER] is False
    api = AsyncMock()
    entry = SimpleNamespace(data=flow._setup_feature_data, options={}, runtime_data=SimpleNamespace(api=api))
    asyncio.run(_async_sync_device_user(SimpleNamespace(), entry))
    assert api.mock_calls == []


def _feature_step(monkeypatch, kind, entry):
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

    def saved():
        return flow._async_store_options.await_args.args[0] if kind == "options" else flow._reconfigure_feature_data

    return step, saved


@MODELS
@pytest.mark.parametrize("kind", ["options", "reconfigure"])
def test_enabling_video_turns_the_user_on(monkeypatch, kind, info):
    entry = SimpleNamespace(
        data={"agent_host": "station.invalid", CONF_VIDEO_ENABLED: False, CONF_CREATE_HOMEASSISTANT_USER: False},
        options={}, runtime_data=SimpleNamespace(agent_info=info))
    step, saved = _feature_step(monkeypatch, kind, entry)
    asyncio.run(step({CONF_VIDEO_ENABLED: True}))
    assert saved()[CONF_CREATE_HOMEASSISTANT_USER] is True


@MODELS
@pytest.mark.parametrize("kind", ["options", "reconfigure"])
def test_a_saved_user_choice_stays(monkeypatch, kind, info):
    entry = SimpleNamespace(
        data={"agent_host": "station.invalid", CONF_VIDEO_ENABLED: True, CONF_CREATE_HOMEASSISTANT_USER: False},
        options={}, runtime_data=SimpleNamespace(agent_info=info))
    step, saved = _feature_step(monkeypatch, kind, entry)
    asyncio.run(step({CONF_VIDEO_ENABLED: True}))
    assert saved()[CONF_CREATE_HOMEASSISTANT_USER] is False


def test_no_model_specific_media_consent_is_left():
    root = Path(__file__).resolve().parents[1] / "custom_components" / "bticino_c300x"
    assert not (root / "media_consent.py").exists()
    assert not any("media_consent" in path.read_text(encoding="utf-8") for path in root.glob("*.py"))
