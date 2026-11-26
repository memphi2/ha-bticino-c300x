"""Native HA microphone opt-in across setup, options and reconfigure flows."""

import asyncio
from types import SimpleNamespace

import pytest
import voluptuous as vol
from test_display_settings import _OptionsAreas

from custom_components.bticino_c300x.camera_media.ha_compat import (
    HA_SUPPORTS_NATIVE_CAMERA_TWO_WAY_AUDIO,
)
from custom_components.bticino_c300x.config_flow import (
    BticinoC300XConfigFlow,
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
    CONF_AUDIO_FINE_GAIN_DB,
    CONF_DOOR_AUDIO_LEVEL_DB,
    CONF_NATIVE_TWO_WAY_AUDIO,
    CONF_VIDEO_ENABLED,
    RETIRED_AUDIO_OPTION_KEYS,
)


def test_native_audio_defaults_off_and_requires_enabled_media():
    entry = SimpleNamespace(data={CONF_VIDEO_ENABLED: True}, options={})
    _assert_form_audio(setup_features_schema(True), False)
    _assert_form_audio(options_features_schema(entry), False)
    assert current_feature_options(entry)[CONF_NATIVE_TWO_WAY_AUDIO] is False
    assert _feature_input({CONF_VIDEO_ENABLED: True})[0][CONF_NATIVE_TWO_WAY_AUDIO] is False
    assert _feature_input({
        CONF_VIDEO_ENABLED: False, CONF_NATIVE_TWO_WAY_AUDIO: True,
    })[0][CONF_NATIVE_TWO_WAY_AUDIO] is False
    assert CONF_NATIVE_TWO_WAY_AUDIO not in setup_features_schema(False)({})


def _assert_form_audio(schema, expected):
    if HA_SUPPORTS_NATIVE_CAMERA_TWO_WAY_AUDIO:
        assert schema({})[CONF_NATIVE_TWO_WAY_AUDIO] is expected
    else:
        assert CONF_NATIVE_TWO_WAY_AUDIO not in schema({})
        with pytest.raises(vol.Invalid):
            schema({CONF_NATIVE_TWO_WAY_AUDIO: True})


@pytest.mark.parametrize("enabled", [False, True])
def test_native_audio_option_survives_forms_and_unrelated_edits(enabled):
    entry = SimpleNamespace(
        data={CONF_VIDEO_ENABLED: True, CONF_NATIVE_TWO_WAY_AUDIO: not enabled},
        options={CONF_NATIVE_TWO_WAY_AUDIO: enabled},
    )
    defaults = current_feature_options(entry)
    assert defaults[CONF_NATIVE_TWO_WAY_AUDIO] is enabled
    _assert_form_audio(options_features_schema(entry), enabled)
    _assert_form_audio(reconfigure_features_schema_from_current(entry), enabled)
    for value in (None, False, True):
        submitted = {CONF_VIDEO_ENABLED: True}
        if value is not None:
            submitted[CONF_NATIVE_TWO_WAY_AUDIO] = value
        result, errors = _feature_input(feature_input_defaults(submitted, defaults))
        assert not errors
        assert result[CONF_NATIVE_TWO_WAY_AUDIO] is (
            HA_SUPPORTS_NATIVE_CAMERA_TWO_WAY_AUDIO and (enabled if value is None else value)
        )


@pytest.mark.parametrize("kind", ["setup", "options", "reconfigure"])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("invalid", [False, True])
def test_native_audio_choice_is_retained_on_success_and_validation_error(kind, enabled, invalid):
    entry = SimpleNamespace(
        data={CONF_VIDEO_ENABLED: True},
        options={CONF_NATIVE_TWO_WAY_AUDIO: not enabled}, runtime_data=None,
    )
    if kind == "options":
        areas = _OptionsAreas(entry)
        flow = areas._flow()
        step = flow.async_step_features
        pending = ""
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
        # A changed level: the options flow writes nothing for an unchanged area.
        CONF_DOOR_AUDIO_LEVEL_DB: 99 if invalid else "3",
    }))
    if invalid:
        assert result["errors"] == {CONF_DOOR_AUDIO_LEVEL_DB: "invalid_audio_level"}
        _assert_form_audio(result["data_schema"], enabled)
        if kind == "options":
            areas.hass.config_entries.async_update_entry.assert_not_called()
            areas.hass.config_entries.async_schedule_reload.assert_not_called()
    else:
        # The options flow saves the area at once; the other flows keep it pending.
        kept = getattr(flow, pending) if pending else entry.options
        assert kept[CONF_NATIVE_TWO_WAY_AUDIO] is (
            enabled and HA_SUPPORTS_NATIVE_CAMERA_TWO_WAY_AUDIO
        )
        if kind == "options":
            areas.hass.config_entries.async_update_entry.assert_called_once()
            areas.hass.config_entries.async_schedule_reload.assert_called_once_with(entry.entry_id)


def test_reconfigure_removes_stale_native_audio_override():
    updates = []
    hass = SimpleNamespace(config_entries=SimpleNamespace(
        async_update_entry=lambda _entry, **kwargs: updates.append(kwargs["options"]),
    ))
    entry = SimpleNamespace(options={CONF_NATIVE_TWO_WAY_AUDIO: True, "unrelated": "keep"})
    _clear_reconfigured_option_overrides(hass, entry, {CONF_NATIVE_TWO_WAY_AUDIO: False})
    assert updates == [{"unrelated": "keep"}]


def test_an_entry_with_the_retired_audio_keys_loads_and_saving_drops_them():
    entry = SimpleNamespace(
        data={CONF_VIDEO_ENABLED: True},
        options={"doorstation_audio_gain_db": 15.5, "ring_capture_audio_gain_db": -20.0},
        runtime_data=None,
    )
    current = current_feature_options(entry)
    assert (current[CONF_DOOR_AUDIO_LEVEL_DB], current[CONF_AUDIO_FINE_GAIN_DB]) == (6, 0)
    assert options_features_schema(entry)({})[CONF_DOOR_AUDIO_LEVEL_DB] == "6"
    areas = _OptionsAreas(entry)
    flow = areas._flow()
    flow.async_show_form = lambda **kwargs: kwargs
    asyncio.run(flow.async_step_features({CONF_VIDEO_ENABLED: True, CONF_DOOR_AUDIO_LEVEL_DB: "9"}))
    saved = areas.hass.config_entries.async_update_entry.call_args.kwargs["options"]
    assert saved[CONF_DOOR_AUDIO_LEVEL_DB] == 9
    assert saved[CONF_AUDIO_FINE_GAIN_DB] == 0
    assert not set(RETIRED_AUDIO_OPTION_KEYS) & set(saved)
