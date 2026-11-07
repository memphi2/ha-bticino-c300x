"""Native HA microphone opt-in across setup, options and reconfigure flows."""

import asyncio
from types import SimpleNamespace

import pytest

from custom_components.bticino_c300x.config_flow import (
    BticinoC300XConfigFlow,
    BticinoC300XOptionsFlow,
    _clear_reconfigured_option_overrides,
)
from custom_components.bticino_c300x.config_flow_features import (
    current_feature_options,
    feature_input_defaults,
    options_features_schema,
    reconfigure_features_schema_from_current,
)
from custom_components.bticino_c300x.config_flow_input import _feature_input
from custom_components.bticino_c300x.config_schemas import setup_features_schema
from custom_components.bticino_c300x.const import (
    CONF_DOORSTATION_AUDIO_GAIN_DB,
    CONF_NATIVE_TWO_WAY_AUDIO,
    CONF_VIDEO_ENABLED,
)


def test_native_audio_defaults_off_and_requires_enabled_media():
    entry = SimpleNamespace(data={CONF_VIDEO_ENABLED: True}, options={})
    assert setup_features_schema(True)({})[CONF_NATIVE_TWO_WAY_AUDIO] is False
    assert options_features_schema(entry)({})[CONF_NATIVE_TWO_WAY_AUDIO] is False
    assert current_feature_options(entry)[CONF_NATIVE_TWO_WAY_AUDIO] is False
    assert _feature_input({CONF_VIDEO_ENABLED: True})[0][CONF_NATIVE_TWO_WAY_AUDIO] is False
    assert _feature_input({
        CONF_VIDEO_ENABLED: False, CONF_NATIVE_TWO_WAY_AUDIO: True,
    })[0][CONF_NATIVE_TWO_WAY_AUDIO] is False
    assert CONF_NATIVE_TWO_WAY_AUDIO not in setup_features_schema(False)({})


@pytest.mark.parametrize("enabled", [False, True])
def test_native_audio_option_survives_forms_and_unrelated_edits(enabled):
    entry = SimpleNamespace(
        data={CONF_VIDEO_ENABLED: True, CONF_NATIVE_TWO_WAY_AUDIO: not enabled},
        options={CONF_NATIVE_TWO_WAY_AUDIO: enabled},
    )
    defaults = current_feature_options(entry)
    assert defaults[CONF_NATIVE_TWO_WAY_AUDIO] is enabled
    assert options_features_schema(entry)({})[CONF_NATIVE_TWO_WAY_AUDIO] is enabled
    assert reconfigure_features_schema_from_current(entry)({})[CONF_NATIVE_TWO_WAY_AUDIO] is enabled
    for value in (None, False, True):
        submitted = {CONF_VIDEO_ENABLED: True}
        if value is not None:
            submitted[CONF_NATIVE_TWO_WAY_AUDIO] = value
        result, errors = _feature_input(feature_input_defaults(submitted, defaults))
        assert not errors
        assert result[CONF_NATIVE_TWO_WAY_AUDIO] is (enabled if value is None else value)


@pytest.mark.parametrize("kind", ["setup", "options", "reconfigure"])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("invalid", [False, True])
def test_native_audio_choice_is_retained_on_success_and_validation_error(kind, enabled, invalid):
    entry = SimpleNamespace(
        data={CONF_VIDEO_ENABLED: True},
        options={CONF_NATIVE_TWO_WAY_AUDIO: not enabled}, runtime_data=None,
    )
    if kind == "options":
        flow = BticinoC300XOptionsFlow(entry)
        step = flow.async_step_features
        pending = "_feature_options"
    else:
        flow = BticinoC300XConfigFlow()
        flow._get_reconfigure_entry = lambda: entry
        flow._setup_connection = {"agent_host": "agent.example"}
        step = (flow.async_step_user_features if kind == "setup"
                else flow.async_step_reconfigure_features)
        pending = "_setup_feature_data" if kind == "setup" else "_reconfigure_feature_data"
    flow.async_show_form = lambda **kwargs: kwargs
    result = asyncio.run(step({
        CONF_VIDEO_ENABLED: True,
        CONF_NATIVE_TWO_WAY_AUDIO: enabled,
        CONF_DOORSTATION_AUDIO_GAIN_DB: 99 if invalid else 0,
    }))
    if invalid:
        assert result["errors"] == {CONF_DOORSTATION_AUDIO_GAIN_DB: "invalid_audio_gain"}
        assert result["data_schema"]({})[CONF_NATIVE_TWO_WAY_AUDIO] is enabled
    else:
        assert getattr(flow, pending)[CONF_NATIVE_TWO_WAY_AUDIO] is enabled


def test_reconfigure_removes_stale_native_audio_override():
    updates = []
    hass = SimpleNamespace(config_entries=SimpleNamespace(
        async_update_entry=lambda _entry, **kwargs: updates.append(kwargs["options"]),
    ))
    entry = SimpleNamespace(options={CONF_NATIVE_TWO_WAY_AUDIO: True, "unrelated": "keep"})
    _clear_reconfigured_option_overrides(hass, entry, {CONF_NATIVE_TWO_WAY_AUDIO: False})
    assert updates == [{"unrelated": "keep"}]
