from __future__ import annotations

# ruff: noqa: E402, I001

import asyncio
import sys
import types
from collections.abc import Callable
from types import SimpleNamespace

import pytest
import voluptuous as vol
import voluptuous_serialize

homeassistant = sys.modules.setdefault(
    "homeassistant",
    types.ModuleType("homeassistant"),
)
homeassistant.__path__ = []
config_entries = sys.modules.setdefault(
    "homeassistant.config_entries",
    types.ModuleType("homeassistant.config_entries"),
)
const = sys.modules.setdefault("homeassistant.const", types.ModuleType("homeassistant.const"))
core = sys.modules.setdefault("homeassistant.core", types.ModuleType("homeassistant.core"))
helpers = sys.modules.setdefault(
    "homeassistant.helpers",
    types.ModuleType("homeassistant.helpers"),
)
helpers.__path__ = []
config_validation = sys.modules.setdefault(
    "homeassistant.helpers.config_validation",
    types.ModuleType("homeassistant.helpers.config_validation"),
)
dispatcher = sys.modules.setdefault(
    "homeassistant.helpers.dispatcher",
    types.ModuleType("homeassistant.helpers.dispatcher"),
)
event = sys.modules.setdefault(
    "homeassistant.helpers.event",
    types.ModuleType("homeassistant.helpers.event"),
)


class ConfigFlow:  # pragma: no cover - import-time stub only
    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs


class OptionsFlow:  # pragma: no cover - import-time stub only
    pass


class ConfigEntry:  # pragma: no cover - import-time stub only
    pass


class HomeAssistant:  # pragma: no cover - import-time stub only
    pass


if not hasattr(config_entries, "ConfigFlow"):
    config_entries.ConfigFlow = ConfigFlow
if not hasattr(config_entries, "ConfigEntry"):
    config_entries.ConfigEntry = ConfigEntry
if not hasattr(config_entries, "OptionsFlow"):
    config_entries.OptionsFlow = OptionsFlow
if not hasattr(config_entries, "FlowResult"):
    config_entries.FlowResult = dict
const.CONF_NAME = "name"
if not hasattr(core, "callback"):
    core.callback = lambda func: func
if not hasattr(core, "CALLBACK_TYPE"):
    core.CALLBACK_TYPE = object
if not hasattr(core, "HomeAssistant"):
    core.HomeAssistant = HomeAssistant
if not hasattr(config_validation, "config_entry_only_config_schema"):
    config_validation.config_entry_only_config_schema = lambda _domain: dict
if not hasattr(dispatcher, "async_dispatcher_send"):
    dispatcher.async_dispatcher_send = lambda *_args, **_kwargs: None
if not hasattr(event, "async_call_later"):
    event.async_call_later = lambda *_args, **_kwargs: (lambda: None)
homeassistant.config_entries = config_entries
homeassistant.const = const
homeassistant.core = core
homeassistant.helpers = helpers
helpers.config_validation = config_validation
helpers.dispatcher = dispatcher
helpers.event = event
helpers.selector = None
sys.modules.pop("homeassistant.helpers.selector", None)

from custom_components.bticino_c300x.config_flow import (  # noqa: E402
    BticinoC300XOptionsFlow,
    BticinoC300XConfigFlow,
    _agent_host,
    _alarm_entity_id,
    _actions_json,
    _agent_auth_input,
    _agent_auth_schema,
    _async_qml_patch_description_placeholders,
    _async_probe_agent,
    _bootstrap_install_schema,
    _clear_reconfigured_option_overrides,
    _connection_input,
    _current_connection_options,
    _current_feature_options,
    _feature_input,
    _feature_input_defaults,
    _non_empty_string,
    _initial_connection_input,
    _options_connection_schema,
    _options_features_schema,
    _qml_patch_status_label,
    _reconfigure_connection_schema,
    _reconfigure_connection_schema_from_current,
    _reconfigure_features_schema,
    _reconfigure_features_schema_from_current,
    _reconfigure_unique_id,
    _setup_connection_schema,
    _setup_features_schema,
    _weather_entity_id,
)
from custom_components.bticino_c300x import config_flow as config_flow_module  # noqa: E402
from custom_components.bticino_c300x.api import C300XAgentApiConnectionError  # noqa: E402
from custom_components.bticino_c300x.config_flow_dashboard import (  # noqa: E402
    dashboard_entity_display_form_complete as _dashboard_entity_display_form_complete,
    dashboard_entity_display_overrides as _dashboard_entity_display_overrides,
    dashboard_entity_display_schema as _dashboard_entity_display_schema,
    dashboard_entity_ids as _dashboard_entity_ids,
    _dashboard_entity_name_display,
    _dashboard_entity_secondary_info,
    dashboard_input_defaults as _dashboard_input_defaults,
    dashboard_schema as _dashboard_schema,
)
from custom_components.bticino_c300x.config_schemas import (  # noqa: E402
    stair_light_n as _stair_light_n,
    stair_light_p as _stair_light_p,
)
from custom_components.bticino_c300x.const import (  # noqa: E402
    CONF_ACTIONS,
    CONF_ACTIONS_JSON,
    CONF_AGENT_TOKEN,
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_BOOTSTRAP_INSTALL_AGENT,
    CONF_ALARM_ENTITY_ID,
    CONF_ALARM_PAGE_ENTITY_ID,
    CONF_BOOTSTRAP_SSH_PASSWORD,
    CONF_BOOTSTRAP_SSH_USERNAME,
    CONF_CALLBACK_BASE_URL,
    CONF_CREATE_HOMEASSISTANT_USER,
    CONF_DASHBOARD_DYNAMIC_HOMEPAGE,
    CONF_DASHBOARD_ENTITIES,
    CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
    CONF_DASHBOARD_PREVENT_RETURN,
    CONF_DEVICE_ACTIVATION_FLOW_ACTION,
    CONF_DEVICE_ACTIVATION_ITEM_ADDRESS,
    CONF_DEVICE_ACTIVATION_ITEM_ID,
    CONF_DEVICE_ACTIVATION_ITEM_NAME,
    CONF_DEVICE_ACTIVATION_ITEM_TYPE,
    CONF_DEVICE_ACTIVATION_MODE,
    CONF_DEVICE_ACTIVATIONS,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P,
    CONF_DEVICE_UI_ENABLED,
    CONF_DOORSTATION_AUDIO_GAIN_DB,
    CONF_MAINTENANCE_TOKEN,
    CONF_EVENT_WEBHOOK_TOKEN,
    CONF_RING_CAPTURE_AUDIO_GAIN_DB,
    CONF_ROTATE_SHARED_SECRET,
    CONF_SHARED_SECRET,
    CONF_VIDEO_ENABLED,
    CONF_VIDEO_PORT,
    CONF_VIDEO_STREAM_PATH,
    CONF_WEATHER_ENTITY_ID,
    DEFAULT_DOORSTATION_AUDIO_GAIN_DB,
    DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB,
    DEFAULT_STAIR_LIGHT_N,
    DEFAULT_STAIR_LIGHT_P,
    DEFAULT_VIDEO_STREAM_PATH,
    DEVICE_ACTIVATION_FLOW_ACTION_ADD,
    DEVICE_ACTIVATION_FLOW_ACTION_DONE,
    DEVICE_ACTIVATION_MODE_AUTO,
    DEVICE_ACTIVATION_MODE_MANUAL,
)
from homeassistant.const import CONF_NAME  # noqa: E402


def test_probe_agent_requires_event_subscription_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    aiohttp_client = sys.modules.setdefault(
        "homeassistant.helpers.aiohttp_client",
        types.ModuleType("homeassistant.helpers.aiohttp_client"),
    )
    aiohttp_client.async_get_clientsession = lambda _hass: object()

    class FakeApi:
        def __init__(
            self,
            _session: object,
            base_url: str,
            token: str,
        ) -> None:
            calls.append(f"api:{base_url}:{token}")

        async def async_validate_setup(self) -> dict[str, object]:
            calls.append("capabilities")
            return {"device_id": "c300x-test"}

        async def async_self_test(self) -> dict[str, object]:
            calls.append("self_test")
            return {"ok": True, "checks": {}}

        async def async_list_event_subscriptions(self) -> dict[str, object]:
            calls.append("subscriptions")
            raise C300XAgentApiConnectionError("device agent returned HTTP 404")

    monkeypatch.setattr(config_flow_module, "C300XAgentApi", FakeApi)

    result = asyncio.run(
        _async_probe_agent(
            SimpleNamespace(),
            {
                CONF_AGENT_HOST: "c300x.local",
                CONF_AGENT_PORT: 8091,
            },
            api_token="agent-token",
        )
    )

    assert result == "missing"
    assert calls == [
        "api:http://c300x.local:8091:agent-token",
        "capabilities",
        "self_test",
        "subscriptions",
    ]


def test_stair_light_address_parts_match_firmware_default() -> None:
    result = _feature_input(
        {
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P: DEFAULT_STAIR_LIGHT_P,
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N: DEFAULT_STAIR_LIGHT_N,
        }
    )[0]

    assert result[CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P] == "01"
    assert result[CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N] == "00"


def test_stair_light_address_parts_preserve_parts() -> None:
    result = _feature_input(
        {
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P: "02",
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N: "01",
        }
    )[0]

    assert result[CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P] == "02"
    assert result[CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N] == "01"


@pytest.mark.parametrize(
    ("validator", "value"),
    [
        (_stair_light_p, "100"),
        (_stair_light_p, "A1"),
        (_stair_light_n, "100"),
        (_stair_light_n, "A1"),
    ],
)
def test_stair_light_address_parts_reject_invalid_values(
    validator: Callable[[object], str],
    value: str,
) -> None:
    with pytest.raises(vol.Invalid):
        validator(value)


def test_feature_schemas_are_serializable_for_home_assistant_forms() -> None:
    """Keep visible form schemas compatible with HA data-entry-flow JSON output."""

    voluptuous_serialize.convert(_setup_features_schema(False))
    voluptuous_serialize.convert(_reconfigure_features_schema(False))


def test_non_empty_string_strips_input() -> None:
    assert _non_empty_string(" token ") == "token"


def test_non_empty_string_rejects_blank_input() -> None:
    with pytest.raises(vol.Invalid):
        _non_empty_string(" ")


def test_agent_host_strips_input() -> None:
    assert _agent_host(" c300x-agent.local ") == "c300x-agent.local"


def test_agent_host_rejects_blank_input() -> None:
    with pytest.raises(vol.Invalid):
        _agent_host(" ")


def test_connection_input_rejects_blank_agent_host() -> None:
    data, errors = _connection_input(
        {
            CONF_NAME: "BTicino C300X",
            CONF_AGENT_HOST: "   ",
            CONF_AGENT_PORT: 8091,
            CONF_AGENT_TOKEN: "",
        },
        include_name=True,
    )

    assert errors == {CONF_AGENT_HOST: "invalid_agent_host"}
    assert data[CONF_AGENT_HOST] == ""


def test_connection_input_allows_blank_agent_token_for_no_auth_entries() -> None:
    data, errors = _connection_input(
        {
            CONF_AGENT_HOST: " c300x-agent.local ",
            CONF_AGENT_PORT: 8091,
            CONF_AGENT_TOKEN: "   ",
            CONF_MAINTENANCE_TOKEN: "",
        }
    )

    assert errors == {}
    assert data[CONF_AGENT_HOST] == "c300x-agent.local"
    assert data[CONF_AGENT_TOKEN] == ""
    assert data[CONF_CALLBACK_BASE_URL] == ""


def test_connection_input_accepts_callback_base_url_override() -> None:
    data, errors = _connection_input(
        {
            CONF_AGENT_HOST: "c300x-agent.local",
            CONF_AGENT_PORT: 8091,
            CONF_AGENT_TOKEN: "",
            CONF_MAINTENANCE_TOKEN: "",
            CONF_CALLBACK_BASE_URL: " http://192.0.2.10:8123/ ",
        }
    )

    assert errors == {}
    assert data[CONF_CALLBACK_BASE_URL] == "http://192.0.2.10:8123"


@pytest.mark.parametrize(
    "value",
    [
        "https://192.0.2.10:8123",
        "http://homeassistant.local:8123",
        "http://127.0.0.1:8123",
        "http://[fe80::1]:8123",
    ],
)
def test_connection_input_rejects_unsafe_callback_base_url(value: str) -> None:
    data, errors = _connection_input(
        {
            CONF_AGENT_HOST: "c300x-agent.local",
            CONF_AGENT_PORT: 8091,
            CONF_AGENT_TOKEN: "",
            CONF_MAINTENANCE_TOKEN: "",
            CONF_CALLBACK_BASE_URL: value,
        }
    )

    assert errors == {CONF_CALLBACK_BASE_URL: "invalid_callback_base_url"}
    assert data[CONF_CALLBACK_BASE_URL] == ""


def test_initial_connection_input_collects_no_tokens_or_feature_fields() -> None:
    data, errors = _initial_connection_input(
        {
            CONF_NAME: "BTicino C300X",
            CONF_AGENT_HOST: " c300x-agent.local ",
            CONF_AGENT_PORT: 8091,
        },
        include_name=True,
    )

    assert errors == {}
    assert data == {
        CONF_NAME: "BTicino C300X",
        CONF_AGENT_HOST: "c300x-agent.local",
        CONF_AGENT_PORT: 8091,
        CONF_CALLBACK_BASE_URL: "",
    }


def test_initial_connection_input_collects_callback_base_url() -> None:
    data, errors = _initial_connection_input(
        {
            CONF_NAME: "BTicino C300X",
            CONF_AGENT_HOST: "c300x-agent.local",
            CONF_AGENT_PORT: 8091,
            CONF_CALLBACK_BASE_URL: "http://192.0.2.10:8123",
        },
        include_name=True,
    )

    assert errors == {}
    assert data[CONF_CALLBACK_BASE_URL] == "http://192.0.2.10:8123"


def test_agent_auth_requires_token_only_after_auth_challenge() -> None:
    data, errors = _agent_auth_input(
        {
            CONF_AGENT_TOKEN: "",
        },
        require_agent_token=True,
    )
    optional_data, optional_errors = _agent_auth_input(
        {
            CONF_AGENT_TOKEN: "",
        },
        require_agent_token=False,
    )

    assert errors == {CONF_AGENT_TOKEN: "required"}
    assert data == {CONF_AGENT_TOKEN: "", CONF_MAINTENANCE_TOKEN: ""}
    assert optional_errors == {}
    assert optional_data[CONF_AGENT_TOKEN] == ""


def test_alarm_entity_id_accepts_alarm_control_panel_entity() -> None:
    assert (
        _alarm_entity_id(" alarm_control_panel.Home ")
        == "alarm_control_panel.home"
    )


@pytest.mark.parametrize("value", ["light.entry", "alarm_control_panel.", "bad"])
def test_alarm_entity_id_rejects_non_alarm_entities(value: str) -> None:
    with pytest.raises(vol.Invalid):
        _alarm_entity_id(value)


def test_alarm_entity_id_allows_empty_value() -> None:
    assert _alarm_entity_id("") == ""


def test_weather_entity_id_accepts_weather_entity() -> None:
    assert _weather_entity_id(" weather.Home ") == "weather.home"


@pytest.mark.parametrize("value", ["sensor.outdoor_temperature", "weather.", "bad"])
def test_weather_entity_id_rejects_non_weather_entities(value: str) -> None:
    with pytest.raises(vol.Invalid):
        _weather_entity_id(value)


def test_weather_entity_id_allows_empty_value() -> None:
    assert _weather_entity_id("") == ""


def test_dashboard_entity_ids_accept_supported_entities() -> None:
    assert _dashboard_entity_ids(
        [
            " Switch.Entry ",
            "sensor.temperature",
            "switch.entry",
            "select.forwarding",
            "input_select.scene",
        ]
    ) == [
        "switch.entry",
        "sensor.temperature",
        "select.forwarding",
        "input_select.scene",
    ]


@pytest.mark.parametrize("value", ["media_player.tv", "sensor.", "bad"])
def test_dashboard_entity_ids_reject_unsupported_entities(value: str) -> None:
    with pytest.raises(vol.Invalid):
        _dashboard_entity_ids(value)


def test_dashboard_entity_ids_allows_empty_value() -> None:
    assert _dashboard_entity_ids("") == []
    assert _dashboard_entity_ids([]) == []


def test_dashboard_entity_display_overrides_accepts_valid_mapping() -> None:
    assert _dashboard_entity_display_overrides(
        {
            "sensor.temperature": {
                "name": "custom",
                "custom_name": "Outside",
                "secondary": "none",
            }
        }
    ) == {
        "sensor.temperature": {
            "name": "custom",
            "custom_name": "Outside",
            "secondary": "none",
        }
    }


@pytest.mark.parametrize(
    "value",
    [
        {"media_player.tv": {"name": "entity_id"}},
        {"sensor.temperature": {"name": "bad"}},
        {"sensor.temperature": {"name": "custom"}},
        {"sensor.temperature": {"secondary": "bad"}},
        "not a mapping",
    ],
)
def test_dashboard_entity_display_overrides_rejects_invalid_mapping(value: object) -> None:
    with pytest.raises(vol.Invalid):
        _dashboard_entity_display_overrides(value)


def test_dashboard_entity_display_field_modes_fall_back_to_safe_defaults() -> None:
    assert _dashboard_entity_name_display("bad") == "friendly_name"
    assert _dashboard_entity_secondary_info("bad") == "state"


def test_actions_json_is_stable_for_options_form() -> None:
    assert _actions_json({}) == ""
    assert (
        _actions_json({"b": {"service": "turn_on", "domain": "script"}})
        == '{\n  "b": {\n    "domain": "script",\n    "service": "turn_on"\n  }\n}'
    )


def test_setup_schema_defers_agent_tokens_to_auth_page() -> None:
    schema = _setup_connection_schema(
        "BTicino C300X",
        "c300x-agent.local",
        8091,
    )

    result = schema(
        {
            CONF_NAME: "Door panel",
            CONF_AGENT_HOST: "c300x-agent.local",
            CONF_AGENT_PORT: 8091,
            CONF_CALLBACK_BASE_URL: "",
        }
    )

    assert CONF_AGENT_TOKEN not in result
    assert CONF_DEVICE_ACTIVATION_MODE not in result
    assert result[CONF_CALLBACK_BASE_URL] == ""


def test_agent_auth_schema_keeps_tokens_on_second_setup_page() -> None:
    schema = _agent_auth_schema(require_agent_token=False)

    result = schema(
        {
            CONF_AGENT_TOKEN: "",
            CONF_MAINTENANCE_TOKEN: "",
        }
    )

    assert result[CONF_AGENT_TOKEN] == ""
    assert result[CONF_MAINTENANCE_TOKEN] == ""


def test_bootstrap_install_schema_collects_only_ephemeral_ssh_fields() -> None:
    schema = _bootstrap_install_schema()

    result = schema(
        {
            CONF_BOOTSTRAP_SSH_USERNAME: "root",
            CONF_BOOTSTRAP_SSH_PASSWORD: "temporary",
        }
    )

    assert result[CONF_BOOTSTRAP_SSH_USERNAME] == "root"
    assert result[CONF_BOOTSTRAP_SSH_PASSWORD] == "temporary"
    assert CONF_AGENT_TOKEN not in result
    assert CONF_DEVICE_UI_ENABLED not in result


def test_reconfigure_schema_preserves_defaults() -> None:
    connection_schema = _reconfigure_connection_schema(
        "c300x-agent.local",
        8091,
        "token",
        "",
        "http://192.0.2.10:8123",
    )
    feature_schema = _reconfigure_features_schema(
        True,
    )

    connection = connection_schema(
        {
            CONF_AGENT_HOST: "c300x-agent.local",
            CONF_AGENT_PORT: 8091,
            CONF_AGENT_TOKEN: "token",
            CONF_CALLBACK_BASE_URL: "http://192.0.2.10:8123",
        }
    )
    features = feature_schema({})

    assert connection[CONF_CALLBACK_BASE_URL] == "http://192.0.2.10:8123"
    assert CONF_ALARM_ENTITY_ID not in features
    assert CONF_WEATHER_ENTITY_ID not in features
    assert features[CONF_VIDEO_ENABLED] is True
    assert features[CONF_CREATE_HOMEASSISTANT_USER] is True
    assert features[CONF_DOORSTATION_AUDIO_GAIN_DB] == DEFAULT_DOORSTATION_AUDIO_GAIN_DB
    assert features[CONF_RING_CAPTURE_AUDIO_GAIN_DB] == DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB
    assert CONF_DEVICE_UI_ENABLED not in features


def test_setup_features_schema_keeps_initial_video_defaults() -> None:
    schema = _setup_features_schema(
        True,
    )

    result = schema({})

    assert CONF_ALARM_ENTITY_ID not in result
    assert CONF_WEATHER_ENTITY_ID not in result
    assert result[CONF_VIDEO_ENABLED] is True
    assert result[CONF_CREATE_HOMEASSISTANT_USER] is True
    assert result[CONF_DOORSTATION_AUDIO_GAIN_DB] == DEFAULT_DOORSTATION_AUDIO_GAIN_DB
    assert result[CONF_RING_CAPTURE_AUDIO_GAIN_DB] == DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB
    assert CONF_VIDEO_PORT not in result
    assert CONF_VIDEO_STREAM_PATH not in result
    assert CONF_DEVICE_UI_ENABLED not in result
    assert CONF_DASHBOARD_PREVENT_RETURN not in result
    assert result[CONF_DEVICE_ACTIVATION_MODE] == DEVICE_ACTIVATION_MODE_AUTO
    assert result[CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P] == DEFAULT_STAIR_LIGHT_P
    assert result[CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N] == DEFAULT_STAIR_LIGHT_N


def test_feature_input_allows_clearing_gui_entities_and_actions() -> None:
    data, errors = _feature_input(
        {
            CONF_DEVICE_UI_ENABLED: True,
            CONF_ALARM_ENTITY_ID: "",
            CONF_WEATHER_ENTITY_ID: "",
            CONF_DASHBOARD_ENTITIES: [],
            CONF_ACTIONS_JSON: "",
            CONF_DASHBOARD_PREVENT_RETURN: True,
        }
    )

    assert errors == {}
    assert data[CONF_ALARM_ENTITY_ID] == ""
    assert data[CONF_ALARM_PAGE_ENTITY_ID] == ""
    assert data[CONF_WEATHER_ENTITY_ID] == ""
    assert data[CONF_DASHBOARD_ENTITIES] == []
    assert data[CONF_ACTIONS] == {}
    assert data[CONF_DASHBOARD_PREVENT_RETURN] is True


def test_dashboard_schema_serializes_gui_entity_selectors() -> None:
    schema = _setup_features_schema(
        True,
    )
    dashboard_schema = _dashboard_schema(
        "alarm_control_panel.home",
        "weather.home",
        default_device_ui_enabled=True,
    )

    result = schema({})
    dashboard_result = dashboard_schema({})

    assert CONF_DEVICE_UI_ENABLED not in result
    assert CONF_ALARM_ENTITY_ID not in result
    assert CONF_WEATHER_ENTITY_ID not in result
    assert CONF_DASHBOARD_ENTITIES not in result
    assert dashboard_result[CONF_DEVICE_UI_ENABLED] is True
    assert dashboard_result[CONF_DASHBOARD_PREVENT_RETURN] is False


def test_feature_input_allows_empty_gui_optional_fields() -> None:
    data, errors = _feature_input(
        {
            CONF_DEVICE_UI_ENABLED: True,
            CONF_VIDEO_ENABLED: True,
        }
    )

    assert errors == {}
    assert data[CONF_ALARM_ENTITY_ID] == ""
    assert data[CONF_WEATHER_ENTITY_ID] == ""
    assert data[CONF_DASHBOARD_ENTITIES] == []
    assert data[CONF_ACTIONS] == {}
    assert data[CONF_DASHBOARD_PREVENT_RETURN] is False
    assert data[CONF_DASHBOARD_DYNAMIC_HOMEPAGE] is True
    assert data[CONF_VIDEO_PORT] == 6554
    assert data[CONF_VIDEO_STREAM_PATH] == DEFAULT_VIDEO_STREAM_PATH
    assert data[CONF_DOORSTATION_AUDIO_GAIN_DB] == DEFAULT_DOORSTATION_AUDIO_GAIN_DB
    assert data[CONF_RING_CAPTURE_AUDIO_GAIN_DB] == DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB


def test_initial_feature_input_defaults_video_enabled() -> None:
    data, errors = _feature_input({}, default_video_enabled=True)

    assert errors == {}
    assert data[CONF_VIDEO_ENABLED] is True
    assert data[CONF_CREATE_HOMEASSISTANT_USER] is True
    assert data[CONF_DOORSTATION_AUDIO_GAIN_DB] == DEFAULT_DOORSTATION_AUDIO_GAIN_DB
    assert data[CONF_RING_CAPTURE_AUDIO_GAIN_DB] == DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB


def test_feature_input_can_disable_homeassistant_user_creation() -> None:
    data, errors = _feature_input(
        {
            CONF_VIDEO_ENABLED: True,
            CONF_CREATE_HOMEASSISTANT_USER: False,
            CONF_DOORSTATION_AUDIO_GAIN_DB: -20,
            CONF_RING_CAPTURE_AUDIO_GAIN_DB: 20,
        },
        default_video_enabled=True,
    )

    assert errors == {}
    assert data[CONF_VIDEO_ENABLED] is True
    assert data[CONF_CREATE_HOMEASSISTANT_USER] is False
    assert data[CONF_DOORSTATION_AUDIO_GAIN_DB] == -20
    assert data[CONF_RING_CAPTURE_AUDIO_GAIN_DB] == 20


def test_feature_input_rejects_audio_gain_outside_supported_range() -> None:
    data, errors = _feature_input(
        {
            CONF_VIDEO_ENABLED: True,
            CONF_DOORSTATION_AUDIO_GAIN_DB: -20.5,
            CONF_RING_CAPTURE_AUDIO_GAIN_DB: 20.5,
        },
        default_video_enabled=True,
    )

    assert errors == {
        CONF_DOORSTATION_AUDIO_GAIN_DB: "invalid_audio_gain",
        CONF_RING_CAPTURE_AUDIO_GAIN_DB: "invalid_audio_gain",
    }
    assert data[CONF_DOORSTATION_AUDIO_GAIN_DB] == DEFAULT_DOORSTATION_AUDIO_GAIN_DB
    assert data[CONF_RING_CAPTURE_AUDIO_GAIN_DB] == DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB


def test_feature_input_collects_activation_and_dashboard_errors() -> None:
    data, errors = _feature_input(
        {
            CONF_DEVICE_UI_ENABLED: True,
            CONF_DEVICE_ACTIVATION_MODE: "bad",
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P: "A1",
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N: "100",
            CONF_ACTIONS_JSON: "{bad-json",
            CONF_ALARM_ENTITY_ID: "light.entry",
            CONF_ALARM_PAGE_ENTITY_ID: "media_player.tv",
            CONF_WEATHER_ENTITY_ID: "sensor.outdoor",
            CONF_DASHBOARD_ENTITIES: ["media_player.tv"],
            CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: {
                "sensor.temperature": {"name": "bad"}
            },
        }
    )

    assert errors == {
        CONF_DEVICE_ACTIVATION_MODE: "invalid_device_activation_mode",
        CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P: "invalid_stair_light_part",
        CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N: "invalid_stair_light_part",
        CONF_ACTIONS_JSON: "invalid_action_map",
        CONF_ALARM_ENTITY_ID: "invalid_alarm_entity",
        CONF_ALARM_PAGE_ENTITY_ID: "invalid_alarm_page_entity",
        CONF_WEATHER_ENTITY_ID: "invalid_weather_entity",
        CONF_DASHBOARD_ENTITIES: "invalid_dashboard_entities",
        CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: (
            "invalid_dashboard_entity_display_overrides"
        ),
    }
    assert data[CONF_DEVICE_ACTIVATION_MODE] == DEVICE_ACTIVATION_MODE_AUTO
    assert data[CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P] == DEFAULT_STAIR_LIGHT_P
    assert data[CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N] == DEFAULT_STAIR_LIGHT_N
    assert data[CONF_ACTIONS] == {}
    assert data[CONF_ALARM_ENTITY_ID] == ""
    assert data[CONF_ALARM_PAGE_ENTITY_ID] == ""
    assert data[CONF_WEATHER_ENTITY_ID] == ""
    assert data[CONF_DASHBOARD_ENTITIES] == []
    assert data[CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES] == {}


def test_feature_input_disables_homeassistant_user_when_media_disabled() -> None:
    data, errors = _feature_input(
        {
            CONF_VIDEO_ENABLED: False,
            CONF_CREATE_HOMEASSISTANT_USER: True,
            CONF_DOORSTATION_AUDIO_GAIN_DB: 99,
            CONF_RING_CAPTURE_AUDIO_GAIN_DB: -99,
        },
        default_video_enabled=True,
    )

    assert errors == {}
    assert data[CONF_VIDEO_ENABLED] is False
    assert data[CONF_CREATE_HOMEASSISTANT_USER] is False
    assert data[CONF_DOORSTATION_AUDIO_GAIN_DB] == DEFAULT_DOORSTATION_AUDIO_GAIN_DB
    assert data[CONF_RING_CAPTURE_AUDIO_GAIN_DB] == DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB


def test_feature_input_keeps_selected_gui_features() -> None:
    data, errors = _feature_input(
        {
            CONF_DEVICE_UI_ENABLED: True,
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.home",
            CONF_ALARM_PAGE_ENTITY_ID: "input_button.entry",
            CONF_WEATHER_ENTITY_ID: "weather.home",
            CONF_DASHBOARD_ENTITIES: ["switch.entry", "sensor.temperature"],
            CONF_ACTIONS_JSON: '{"standby":{"domain":"button","service":"press"}}',
            CONF_DASHBOARD_PREVENT_RETURN: False,
            CONF_DASHBOARD_DYNAMIC_HOMEPAGE: False,
        }
    )

    assert errors == {}
    assert data[CONF_ALARM_ENTITY_ID] == "alarm_control_panel.home"
    assert data[CONF_ALARM_PAGE_ENTITY_ID] == "input_button.entry"
    assert data[CONF_WEATHER_ENTITY_ID] == "weather.home"
    assert data[CONF_DASHBOARD_ENTITIES] == ["switch.entry", "sensor.temperature"]
    assert data[CONF_ACTIONS] == {
        "standby": {
            "data": {},
            "domain": "button",
            "service": "press",
            "target": {},
        }
    }
    assert data[CONF_DASHBOARD_PREVENT_RETURN] is False
    assert data[CONF_DASHBOARD_DYNAMIC_HOMEPAGE] is False


def test_feature_input_rejects_unsupported_alarm_page_entity() -> None:
    _data, errors = _feature_input(
        {
            CONF_DEVICE_UI_ENABLED: True,
            CONF_ALARM_PAGE_ENTITY_ID: "media_player.tv",
        }
    )

    assert errors == {CONF_ALARM_PAGE_ENTITY_ID: "invalid_alarm_page_entity"}


def test_manual_setup_duplicate_aborts_before_agent_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    flow = BticinoC300XConfigFlow()
    flow.hass = SimpleNamespace()

    async def async_set_unique_id(unique_id: str, **_kwargs: object) -> None:
        calls.append(f"unique:{unique_id}")

    def abort_if_unique_id_configured(**_kwargs: object) -> None:
        calls.append("abort")
        raise RuntimeError("duplicate")

    async def probe_agent(*_args: object, **_kwargs: object) -> str:
        calls.append("probe")
        return "missing"

    flow.async_set_unique_id = async_set_unique_id  # type: ignore[method-assign]
    flow._abort_if_unique_id_configured = abort_if_unique_id_configured  # type: ignore[method-assign]
    monkeypatch.setattr(
        "custom_components.bticino_c300x.config_flow._async_probe_agent",
        probe_agent,
    )

    with pytest.raises(RuntimeError, match="duplicate"):
        asyncio.run(
            flow.async_step_user(
                {
                    CONF_NAME: "C300X",
                    CONF_AGENT_HOST: "c300x.local",
                    CONF_AGENT_PORT: 8091,
                }
            )
        )

    assert calls == ["unique:bticino_c300x:c300x.local:8091", "abort"]


def test_bootstrap_duplicate_aborts_before_device_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    flow = BticinoC300XConfigFlow()
    flow.hass = SimpleNamespace()
    flow._setup_connection = {
        CONF_NAME: "C300X",
        CONF_AGENT_HOST: "c300x.local",
        CONF_AGENT_PORT: 8091,
    }

    async def async_set_unique_id(unique_id: str, **_kwargs: object) -> None:
        calls.append(f"unique:{unique_id}")

    def abort_if_unique_id_configured(**_kwargs: object) -> None:
        calls.append("abort")
        raise RuntimeError("duplicate")

    async def install_agent(*_args: object, **_kwargs: object) -> None:
        calls.append("install")

    flow.async_set_unique_id = async_set_unique_id  # type: ignore[method-assign]
    flow._abort_if_unique_id_configured = abort_if_unique_id_configured  # type: ignore[method-assign]
    monkeypatch.setattr(
        "custom_components.bticino_c300x.config_flow.async_install_device_agent",
        install_agent,
    )

    with pytest.raises(RuntimeError, match="duplicate"):
        asyncio.run(
            flow.async_step_bootstrap_install(
                {
                    CONF_BOOTSTRAP_SSH_USERNAME: "user",
                    CONF_BOOTSTRAP_SSH_PASSWORD: "password",
                }
            )
        )

    assert calls == ["unique:bticino_c300x:c300x.local:8091", "abort"]


def test_manual_setup_reachable_agent_creates_entry_after_dashboard_display(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    flow = BticinoC300XConfigFlow()
    flow.context = {}  # type: ignore[attr-defined]
    flow.hass = SimpleNamespace()

    async def async_set_unique_id(unique_id: str, **_kwargs: object) -> None:
        calls.append(f"unique:{unique_id}")

    def abort_if_unique_id_configured(**_kwargs: object) -> None:
        calls.append("abort_check")

    async def probe_agent(_hass: object, connection: dict[str, object]) -> str:
        calls.append(f"probe:{connection[CONF_AGENT_HOST]}")
        return "reachable"

    def create_entry(**kwargs: object) -> dict[str, object]:
        calls.append("create_entry")
        return {"type": "create_entry", **kwargs}

    flow.async_set_unique_id = async_set_unique_id  # type: ignore[method-assign]
    flow._abort_if_unique_id_configured = abort_if_unique_id_configured  # type: ignore[method-assign]
    flow.async_create_entry = create_entry  # type: ignore[method-assign]
    flow.async_show_form = lambda **kwargs: kwargs  # type: ignore[method-assign]
    flow._async_in_progress = lambda **_kwargs: []  # type: ignore[method-assign]
    monkeypatch.setattr(
        "custom_components.bticino_c300x.config_flow._async_probe_agent",
        probe_agent,
    )
    async def agent_stable_unique_id(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        "custom_components.bticino_c300x.config_flow._async_agent_stable_unique_id",
        agent_stable_unique_id,
    )

    auth_form = asyncio.run(
        flow.async_step_user(
            {
                CONF_NAME: "Door",
                CONF_AGENT_HOST: "c300x.local",
                CONF_AGENT_PORT: 8091,
                CONF_CALLBACK_BASE_URL: "http://192.0.2.10:8123",
            }
        )
    )
    feature_form = asyncio.run(
        flow.async_step_agent_auth(
            {
                CONF_AGENT_TOKEN: "agent-token",
                CONF_MAINTENANCE_TOKEN: "maintenance-token",
            }
        )
    )
    activation_form = asyncio.run(
        flow.async_step_user_features(
            {
                CONF_VIDEO_ENABLED: True,
                CONF_CREATE_HOMEASSISTANT_USER: True,
                CONF_DEVICE_ACTIVATION_MODE: DEVICE_ACTIVATION_MODE_AUTO,
            }
        )
    )
    dashboard_form = asyncio.run(
        flow.async_step_user_device_activations(
            {CONF_DEVICE_ACTIVATION_FLOW_ACTION: DEVICE_ACTIVATION_FLOW_ACTION_DONE}
        )
    )
    entity_display_form = asyncio.run(
        flow.async_step_user_dashboard(
            {
                CONF_DEVICE_UI_ENABLED: True,
                CONF_DASHBOARD_DYNAMIC_HOMEPAGE: True,
                CONF_ALARM_ENTITY_ID: "alarm_control_panel.home",
                CONF_ALARM_PAGE_ENTITY_ID: "switch.stair_light",
                CONF_WEATHER_ENTITY_ID: "weather.home",
                CONF_DASHBOARD_ENTITIES: ["sensor.temperature"],
            }
        )
    )
    result = asyncio.run(
        flow.async_step_user_dashboard_entity_display(
            {
                "1. Temperature - Name": "custom",
                "1. Temperature - Custom name": "Outside",
                "1. Temperature - Secondary line": "none",
            }
        )
    )

    assert auth_form["step_id"] == "agent_auth"
    assert feature_form["step_id"] == "user_features"
    assert activation_form["step_id"] == "user_device_activations"
    assert dashboard_form["step_id"] == "user_dashboard"
    assert entity_display_form["step_id"] == "user_dashboard_entity_display"
    assert result["type"] == "create_entry"
    assert result["title"] == "Door"
    assert result["data"][CONF_AGENT_HOST] == "c300x.local"
    assert result["data"][CONF_AGENT_TOKEN] == "agent-token"
    assert result["data"][CONF_CALLBACK_BASE_URL] == "http://192.0.2.10:8123"
    assert result["data"][CONF_CREATE_HOMEASSISTANT_USER] is True
    assert result["data"][CONF_ALARM_PAGE_ENTITY_ID] == "switch.stair_light"
    assert result["options"][CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES] == {
        "sensor.temperature": {
            "name": "custom",
            "custom_name": "Outside",
            "secondary": "none",
        }
    }
    assert calls == [
        "unique:bticino_c300x:c300x.local:8091",
        "abort_check",
        "probe:c300x.local",
        "unique:bticino_c300x:c300x.local:8091",
        "abort_check",
        "create_entry",
    ]


def test_manual_setup_missing_agent_can_skip_installer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = BticinoC300XConfigFlow()
    flow.hass = SimpleNamespace()
    flow.async_set_unique_id = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: asyncio.sleep(0)
    )
    flow._abort_if_unique_id_configured = lambda **_kwargs: None  # type: ignore[method-assign]
    flow.async_show_form = lambda **kwargs: kwargs  # type: ignore[method-assign]

    async def probe_agent(_hass: object, _connection: dict[str, object]) -> str:
        return "missing"

    monkeypatch.setattr(
        "custom_components.bticino_c300x.config_flow._async_probe_agent",
        probe_agent,
    )

    missing_form = asyncio.run(
        flow.async_step_user(
            {
                CONF_NAME: "Door",
                CONF_AGENT_HOST: "c300x.local",
                CONF_AGENT_PORT: 8091,
            }
        )
    )
    auth_form = asyncio.run(
        flow.async_step_agent_missing({CONF_BOOTSTRAP_INSTALL_AGENT: False})
    )

    assert missing_form["step_id"] == "agent_missing"
    assert auth_form["step_id"] == "agent_auth"
    assert flow._setup_agent_needs_token is False


def test_bootstrap_install_success_continues_to_feature_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    flow = BticinoC300XConfigFlow()
    flow.context = {}  # type: ignore[attr-defined]
    flow.hass = SimpleNamespace()
    flow._setup_connection = {
        CONF_NAME: "Door",
        CONF_AGENT_HOST: "c300x.local",
        CONF_AGENT_PORT: 8091,
    }
    flow.async_show_form = lambda **kwargs: kwargs  # type: ignore[method-assign]
    flow.async_set_unique_id = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: asyncio.sleep(0)
    )
    flow._abort_if_unique_id_configured = lambda **_kwargs: calls.append(  # type: ignore[method-assign]
        "abort_check"
    )

    async def install_agent(request: object, **kwargs: object) -> None:
        calls.append(
            "install:"
            f"{request.host}:{kwargs['api_token']}:{kwargs['maintenance_token']}"
        )

    async def ensure_installer_dependencies(_hass: object) -> None:
        calls.append("ensure_deps")

    async def probe_agent(
        _hass: object,
        connection: dict[str, object],
        *,
        api_token: str = "",
    ) -> str:
        calls.append(f"probe:{connection[CONF_AGENT_HOST]}:{api_token}")
        return "reachable"

    async def migrate_legacy(*_args: object, **_kwargs: object) -> None:
        calls.append("migrate")

    monkeypatch.setattr(
        config_flow_module.secrets,
        "token_urlsafe",
        lambda length: f"token-{length}",
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.config_flow.async_ensure_installer_dependencies",
        ensure_installer_dependencies,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.config_flow.async_install_device_agent",
        install_agent,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.config_flow._async_probe_agent",
        probe_agent,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.config_flow.async_migrate_legacy_mqtt_for_connection",
        migrate_legacy,
    )
    async def agent_stable_unique_id(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        "custom_components.bticino_c300x.config_flow._async_agent_stable_unique_id",
        agent_stable_unique_id,
    )

    result = asyncio.run(
        flow.async_step_bootstrap_install(
            {
                CONF_BOOTSTRAP_SSH_USERNAME: "root",
                CONF_BOOTSTRAP_SSH_PASSWORD: "temporary",
            }
        )
    )

    assert result["step_id"] == "user_features"
    assert flow._setup_connection[CONF_AGENT_TOKEN] == "token-32"
    assert flow._setup_connection[CONF_MAINTENANCE_TOKEN] == "token-32"
    assert calls == [
        "abort_check",
        "ensure_deps",
        "install:c300x.local:token-32:token-32",
        "probe:c300x.local:token-32",
        "migrate",
    ]


def test_manual_setup_invalid_connection_stays_on_user_form() -> None:
    flow = BticinoC300XConfigFlow()
    flow.async_show_form = lambda **kwargs: kwargs  # type: ignore[method-assign]

    result = asyncio.run(
        flow.async_step_user(
            {
                CONF_NAME: "Door",
                CONF_AGENT_HOST: "",
                CONF_AGENT_PORT: 8091,
                CONF_CALLBACK_BASE_URL: "",
            }
        )
    )

    assert result["step_id"] == "user"
    assert result["errors"] == {CONF_AGENT_HOST: "invalid_agent_host"}


def test_agent_missing_without_connection_returns_user_form() -> None:
    flow = BticinoC300XConfigFlow()
    flow.async_show_form = lambda **kwargs: kwargs  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_agent_missing({}))

    assert result["step_id"] == "user"


def test_agent_missing_choose_install_returns_bootstrap_form() -> None:
    flow = BticinoC300XConfigFlow()
    flow._setup_connection = {
        CONF_NAME: "Door",
        CONF_AGENT_HOST: "c300x.local",
        CONF_AGENT_PORT: 8091,
    }
    flow.async_show_form = lambda **kwargs: kwargs  # type: ignore[method-assign]

    result = asyncio.run(
        flow.async_step_agent_missing({CONF_BOOTSTRAP_INSTALL_AGENT: True})
    )

    assert result["step_id"] == "bootstrap_install"


def test_bootstrap_install_reports_install_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = BticinoC300XConfigFlow()
    flow.hass = SimpleNamespace()
    flow._setup_connection = {
        CONF_NAME: "Door",
        CONF_AGENT_HOST: "c300x.local",
        CONF_AGENT_PORT: 8091,
    }
    flow.async_show_form = lambda **kwargs: kwargs  # type: ignore[method-assign]
    flow.async_set_unique_id = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: asyncio.sleep(0)
    )
    flow._abort_if_unique_id_configured = lambda **_kwargs: None  # type: ignore[method-assign]

    async def install_agent(*_args: object, **_kwargs: object) -> None:
        raise config_flow_module.C300XDeviceInstallError("ssh_auth_failed")

    async def ensure_installer_dependencies(_hass: object) -> None:
        return None

    monkeypatch.setattr(
        "custom_components.bticino_c300x.config_flow.async_ensure_installer_dependencies",
        ensure_installer_dependencies,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.config_flow.async_install_device_agent",
        install_agent,
    )

    result = asyncio.run(
        flow.async_step_bootstrap_install(
            {
                CONF_BOOTSTRAP_SSH_USERNAME: "root",
                CONF_BOOTSTRAP_SSH_PASSWORD: "bad",
            }
        )
    )

    assert result["step_id"] == "bootstrap_install"
    assert result["errors"] == {"base": "ssh_auth_failed"}


def test_bootstrap_install_reports_verify_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = BticinoC300XConfigFlow()
    flow.hass = SimpleNamespace()
    flow._setup_connection = {
        CONF_NAME: "Door",
        CONF_AGENT_HOST: "c300x.local",
        CONF_AGENT_PORT: 8091,
    }
    flow.async_show_form = lambda **kwargs: kwargs  # type: ignore[method-assign]
    flow.async_set_unique_id = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: asyncio.sleep(0)
    )
    flow._abort_if_unique_id_configured = lambda **_kwargs: None  # type: ignore[method-assign]

    async def install_agent(*_args: object, **_kwargs: object) -> None:
        return None

    async def ensure_installer_dependencies(_hass: object) -> None:
        return None

    async def probe_agent(*_args: object, **_kwargs: object) -> str:
        return "missing"

    monkeypatch.setattr(
        config_flow_module.secrets,
        "token_urlsafe",
        lambda length: f"token-{length}",
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.config_flow.async_ensure_installer_dependencies",
        ensure_installer_dependencies,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.config_flow.async_install_device_agent",
        install_agent,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.config_flow._async_probe_agent",
        probe_agent,
    )

    result = asyncio.run(
        flow.async_step_bootstrap_install(
            {
                CONF_BOOTSTRAP_SSH_USERNAME: "root",
                CONF_BOOTSTRAP_SSH_PASSWORD: "temporary",
            }
        )
    )

    assert result["step_id"] == "bootstrap_install"
    assert result["errors"] == {"base": "device_install_verify_failed"}


def test_agent_auth_missing_connection_returns_user_form() -> None:
    flow = BticinoC300XConfigFlow()
    flow.async_show_form = lambda **kwargs: kwargs  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_agent_auth({CONF_AGENT_TOKEN: ""}))

    assert result["step_id"] == "user"


def test_agent_auth_requires_token_when_agent_challenged() -> None:
    flow = BticinoC300XConfigFlow()
    flow._setup_connection = {
        CONF_NAME: "Door",
        CONF_AGENT_HOST: "c300x.local",
        CONF_AGENT_PORT: 8091,
    }
    flow._setup_agent_needs_token = True
    flow.async_show_form = lambda **kwargs: kwargs  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_agent_auth({CONF_AGENT_TOKEN: ""}))

    assert result["step_id"] == "agent_auth"
    assert result["errors"] == {CONF_AGENT_TOKEN: "required"}


def test_user_features_without_connection_returns_user_form() -> None:
    flow = BticinoC300XConfigFlow()
    flow.async_show_form = lambda **kwargs: kwargs  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_user_features({}))

    assert result["step_id"] == "user"


def test_user_features_invalid_input_stays_on_features_form() -> None:
    flow = BticinoC300XConfigFlow()
    flow._setup_connection = {
        CONF_NAME: "Door",
        CONF_AGENT_HOST: "c300x.local",
        CONF_AGENT_PORT: 8091,
    }
    flow.async_show_form = lambda **kwargs: kwargs  # type: ignore[method-assign]

    result = asyncio.run(
        flow.async_step_user_features(
            {
                CONF_VIDEO_ENABLED: True,
                CONF_DOORSTATION_AUDIO_GAIN_DB: 42,
            }
        )
    )

    assert result["step_id"] == "user_features"
    assert result["errors"] == {CONF_DOORSTATION_AUDIO_GAIN_DB: "invalid_audio_gain"}


def test_user_dashboard_without_features_returns_features_form() -> None:
    flow = BticinoC300XConfigFlow()
    flow._setup_connection = {
        CONF_NAME: "Door",
        CONF_AGENT_HOST: "c300x.local",
        CONF_AGENT_PORT: 8091,
    }
    flow.async_show_form = lambda **kwargs: kwargs  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_user_dashboard({}))

    assert result["step_id"] == "user_features"


def test_user_dashboard_entity_display_requires_all_rendered_fields() -> None:
    flow = BticinoC300XConfigFlow()
    flow._setup_dashboard_input = {
        CONF_DEVICE_UI_ENABLED: True,
        CONF_DASHBOARD_ENTITIES: ["sensor.temperature"],
        CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: {},
    }
    flow.async_show_form = lambda **kwargs: kwargs  # type: ignore[method-assign]

    result = asyncio.run(
        flow.async_step_user_dashboard_entity_display(
            {
                "1. Temperature - Name": "custom",
            }
        )
    )

    assert result["step_id"] == "user_dashboard_entity_display"


def test_zeroconf_probes_agent_before_auth_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    flow = BticinoC300XConfigFlow()
    flow.hass = SimpleNamespace()
    flow.context = {}  # type: ignore[attr-defined]

    async def async_set_unique_id(unique_id: str, **_kwargs: object) -> None:
        calls.append(f"unique:{unique_id}")

    def abort_if_unique_id_configured(**_kwargs: object) -> None:
        calls.append("abort_check")

    async def probe_agent(_hass: object, connection: dict[str, object]) -> str:
        calls.append(f"probe:{connection[CONF_AGENT_HOST]}")
        return "auth_required"

    async def step_agent_auth() -> dict[str, object]:
        calls.append("agent_auth")
        return {
            "type": "form",
            "needs_token": flow._setup_agent_needs_token,
        }

    flow.async_set_unique_id = async_set_unique_id  # type: ignore[method-assign]
    flow._abort_if_unique_id_configured = abort_if_unique_id_configured  # type: ignore[method-assign]
    flow.async_step_agent_auth = step_agent_auth  # type: ignore[method-assign]
    flow._async_current_entries = lambda: []  # type: ignore[method-assign]
    monkeypatch.setattr(
        "custom_components.bticino_c300x.config_flow._async_probe_agent",
        probe_agent,
    )

    result = asyncio.run(
        flow.async_step_zeroconf(
            SimpleNamespace(
                host="c300x-agent.local.",
                port=8091,
                properties={"serial": "ABCDEF", "name": "Door Station"},
                name="BTicino C300X Agent._bticino-c300x-agent._tcp.local.",
            )
        )
    )

    assert result == {"type": "form", "needs_token": True}
    assert calls == [
        "unique:abcdef",
        "abort_check",
        "probe:c300x-agent.local.",
        "agent_auth",
    ]


def test_zeroconf_preserves_stable_unique_id_at_entry_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    flow = BticinoC300XConfigFlow()
    flow.hass = SimpleNamespace()
    flow.context = {}  # type: ignore[attr-defined]

    async def async_set_unique_id(unique_id: str, **_kwargs: object) -> None:
        calls.append(f"unique:{unique_id}")

    def abort_if_unique_id_configured(**_kwargs: object) -> None:
        calls.append("abort_check")

    async def probe_agent(_hass: object, connection: dict[str, object]) -> str:
        calls.append(f"probe:{connection[CONF_AGENT_HOST]}")
        return "reachable"

    async def step_agent_auth() -> dict[str, object]:
        calls.append("agent_auth")
        return {"type": "form"}

    def create_entry(**kwargs: object) -> dict[str, object]:
        calls.append("create_entry")
        return kwargs

    flow.async_set_unique_id = async_set_unique_id  # type: ignore[method-assign]
    flow._abort_if_unique_id_configured = abort_if_unique_id_configured  # type: ignore[method-assign]
    flow.async_step_agent_auth = step_agent_auth  # type: ignore[method-assign]
    flow.async_create_entry = create_entry  # type: ignore[method-assign]
    flow.async_show_form = lambda **kwargs: kwargs  # type: ignore[method-assign]
    flow._async_current_entries = lambda: []  # type: ignore[method-assign]
    monkeypatch.setattr(
        "custom_components.bticino_c300x.config_flow._async_probe_agent",
        probe_agent,
    )

    asyncio.run(
        flow.async_step_zeroconf(
            SimpleNamespace(
                host="c300x-agent.local.",
                port=8091,
                properties={"serialno": "ABCDEF", "name": "Door Station"},
                name="BTicino C300X Agent._bticino-c300x-agent._tcp.local.",
            )
        )
    )
    activation_form = asyncio.run(
        flow.async_step_user_features(
            {
                CONF_DEVICE_UI_ENABLED: False,
                CONF_VIDEO_ENABLED: True,
            }
        )
    )
    feature_form = asyncio.run(
        flow.async_step_user_device_activations(
            {CONF_DEVICE_ACTIVATION_FLOW_ACTION: DEVICE_ACTIVATION_FLOW_ACTION_DONE}
        )
    )
    result = asyncio.run(
        flow.async_step_user_dashboard({CONF_DEVICE_UI_ENABLED: False})
    )

    assert activation_form["step_id"] == "user_device_activations"
    assert feature_form["step_id"] == "user_dashboard"
    assert result["title"] == "Door Station"
    assert calls == [
        "unique:abcdef",
        "abort_check",
        "probe:c300x-agent.local.",
        "agent_auth",
        "unique:abcdef",
        "abort_check",
        "create_entry",
    ]


def test_zeroconf_merges_existing_manual_entry_when_token_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    entry = SimpleNamespace(
        unique_id="bticino_c300x:192.0.2.60:8091",
        data={
            CONF_AGENT_HOST: "192.0.2.60",
            CONF_AGENT_PORT: 8091,
            CONF_AGENT_TOKEN: "known-token",
        },
        options={},
    )
    flow = BticinoC300XConfigFlow()
    flow.context = {}  # type: ignore[attr-defined]
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_update_entry=lambda target, **kwargs: calls.append(
                f"update:{target.unique_id}:{kwargs['unique_id']}"
            )
        )
    )

    async def async_set_unique_id(unique_id: str, **_kwargs: object) -> None:
        calls.append(f"unique:{unique_id}")

    def abort_if_unique_id_configured(**_kwargs: object) -> None:
        calls.append("abort_check")

    def async_abort(**kwargs: object) -> dict[str, object]:
        calls.append(f"abort:{kwargs['reason']}")
        return {"type": "abort", **kwargs}

    async def probe_agent(
        _hass: object,
        connection: dict[str, object],
        *,
        api_token: str = "",
    ) -> str:
        calls.append(f"probe:{connection[CONF_AGENT_HOST]}:{api_token}")
        return "reachable" if api_token == "known-token" else "missing"

    flow.async_set_unique_id = async_set_unique_id  # type: ignore[method-assign]
    flow._abort_if_unique_id_configured = abort_if_unique_id_configured  # type: ignore[method-assign]
    flow.async_abort = async_abort  # type: ignore[method-assign]
    flow._async_current_entries = lambda: [entry]  # type: ignore[method-assign]
    monkeypatch.setattr(
        "custom_components.bticino_c300x.config_flow._async_probe_agent",
        probe_agent,
    )

    result = asyncio.run(
        flow.async_step_zeroconf(
            SimpleNamespace(
                host="c300x-agent.local.",
                port=8091,
                properties={"id": "c300x-aabbcc001122", "name": "Door Station"},
                name="BTicino C300X Agent._bticino-c300x-agent._tcp.local.",
            )
        )
    )

    assert result == {"type": "abort", "reason": "already_configured"}
    assert calls == [
        "unique:c300xaabbcc001122",
        "abort_check",
        "probe:c300x-agent.local.:known-token",
        "update:bticino_c300x:192.0.2.60:8091:c300xaabbcc001122",
        "abort:already_configured",
    ]


def test_zeroconf_rediscovery_requests_runtime_event_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    entry = SimpleNamespace(
        unique_id="c300xaabbcc001122",
        data={
            CONF_AGENT_HOST: "c300x-agent.local",
            CONF_AGENT_PORT: 8091,
        },
        options={},
        runtime_data=SimpleNamespace(),
    )
    flow = BticinoC300XConfigFlow()
    flow.hass = SimpleNamespace()
    flow._async_current_entries = lambda: [entry]  # type: ignore[method-assign]

    def request_registration(hass: object, target: object) -> bool:
        assert hass is flow.hass
        assert target is entry
        calls.append("register")
        return True

    monkeypatch.setattr(
        "custom_components.bticino_c300x.events.async_request_agent_event_registration",
        request_registration,
    )

    flow._async_request_existing_entry_event_registration(
        "C300X-AA-BB-CC-00-11-22",
        {
            CONF_AGENT_HOST: "c300x-agent.local.",
            CONF_AGENT_PORT: 8091,
        },
        discovery_matches_entry=lambda left, right: (
            str(left).replace("-", "").lower() == str(right).replace("-", "").lower()
        ),
    )

    assert calls == ["register"]


def test_installer_adopts_agent_mdns_id_and_aborts_parallel_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    pending_flows = [{"flow_id": "zeroconf-flow"}]
    flow = BticinoC300XConfigFlow()
    flow.context = {}  # type: ignore[attr-defined]
    flow._setup_connection = {
        CONF_NAME: "BTicino C300X",
        CONF_AGENT_HOST: "c300x.local",
        CONF_AGENT_PORT: 8091,
        CONF_AGENT_TOKEN: "known-token",
    }
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            flow=SimpleNamespace(
                async_abort=lambda flow_id: (
                    calls.append(f"abort_flow:{flow_id}"),
                    pending_flows.clear(),
                )
            )
        )
    )

    async def agent_stable_unique_id(
        _hass: object,
        connection: dict[str, object],
        *,
        api_token: str = "",
    ) -> str:
        calls.append(f"agent_id:{connection[CONF_AGENT_HOST]}:{api_token}")
        return "c300xaabbcc001122"

    async def async_set_unique_id(unique_id: str, **kwargs: object) -> None:
        calls.append(f"unique:{unique_id}:{kwargs.get('raise_on_progress')}")

    def abort_if_unique_id_configured(**_kwargs: object) -> None:
        calls.append("abort_check")

    def create_entry(**kwargs: object) -> dict[str, object]:
        calls.append("create_entry")
        return kwargs

    flow._async_in_progress = (  # type: ignore[method-assign]
        lambda **_kwargs: list(pending_flows)
    )
    flow.async_set_unique_id = async_set_unique_id  # type: ignore[method-assign]
    flow._abort_if_unique_id_configured = abort_if_unique_id_configured  # type: ignore[method-assign]
    flow.async_create_entry = create_entry  # type: ignore[method-assign]
    flow.async_show_form = lambda **kwargs: kwargs  # type: ignore[method-assign]
    monkeypatch.setattr(
        "custom_components.bticino_c300x.config_flow._async_agent_stable_unique_id",
        agent_stable_unique_id,
    )

    asyncio.run(flow._async_adopt_agent_unique_id(api_token="known-token"))
    activation_form = asyncio.run(
        flow.async_step_user_features(
            {
                CONF_DEVICE_UI_ENABLED: False,
                CONF_VIDEO_ENABLED: True,
            }
        )
    )
    feature_form = asyncio.run(
        flow.async_step_user_device_activations(
            {CONF_DEVICE_ACTIVATION_FLOW_ACTION: DEVICE_ACTIVATION_FLOW_ACTION_DONE}
        )
    )
    result = asyncio.run(
        flow.async_step_user_dashboard({CONF_DEVICE_UI_ENABLED: False})
    )

    assert activation_form["step_id"] == "user_device_activations"
    assert feature_form["step_id"] == "user_dashboard"
    assert result["title"] == "BTicino C300X"
    assert calls == [
        "agent_id:c300x.local:known-token",
        "abort_flow:zeroconf-flow",
        "unique:c300xaabbcc001122:False",
        "abort_check",
        "create_entry",
    ]


def test_feature_schemas_keep_gui_patch_on_dashboard_page() -> None:
    setup_schema = _setup_features_schema(
        True,
    )
    reconfigure_schema = _reconfigure_features_schema(
        True,
    )

    assert _schema_key_names(setup_schema)[0] == CONF_VIDEO_ENABLED
    assert CONF_DEVICE_UI_ENABLED not in _schema_key_names(setup_schema)
    assert CONF_ALARM_ENTITY_ID not in _schema_key_names(setup_schema)
    assert CONF_WEATHER_ENTITY_ID not in _schema_key_names(setup_schema)
    assert CONF_DASHBOARD_ENTITIES not in _schema_key_names(setup_schema)
    assert _schema_key_names(reconfigure_schema)[0] == CONF_VIDEO_ENABLED
    assert CONF_DEVICE_UI_ENABLED not in _schema_key_names(reconfigure_schema)
    assert CONF_ALARM_ENTITY_ID not in _schema_key_names(reconfigure_schema)
    assert CONF_WEATHER_ENTITY_ID not in _schema_key_names(reconfigure_schema)
    assert CONF_DASHBOARD_ENTITIES not in _schema_key_names(reconfigure_schema)

    dashboard_schema = _dashboard_schema(
        "alarm_control_panel.home",
        "weather.home",
        default_device_ui_enabled=True,
    )

    assert _schema_key_names(dashboard_schema)[:3] == [
        CONF_DEVICE_UI_ENABLED,
        CONF_DASHBOARD_PREVENT_RETURN,
        CONF_DASHBOARD_DYNAMIC_HOMEPAGE,
    ]
    assert CONF_ALARM_ENTITY_ID in _schema_key_names(dashboard_schema)
    assert CONF_ALARM_PAGE_ENTITY_ID in _schema_key_names(dashboard_schema)
    assert CONF_WEATHER_ENTITY_ID in _schema_key_names(dashboard_schema)
    assert CONF_DASHBOARD_ENTITIES in _schema_key_names(dashboard_schema)
    assert CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES not in _schema_key_names(
        dashboard_schema
    )
    assert CONF_VIDEO_PORT not in _schema_key_names(dashboard_schema)
    assert CONF_VIDEO_STREAM_PATH not in _schema_key_names(dashboard_schema)


def test_initial_flow_defaults_gui_patch_disabled() -> None:
    flow = BticinoC300XConfigFlow()

    assert flow._setup_device_ui_default is False


def test_options_connection_schema_keeps_connection_on_first_page() -> None:
    entry = SimpleNamespace(
        data={
            CONF_AGENT_HOST: "old-agent.local",
            CONF_AGENT_PORT: 8091,
            CONF_AGENT_TOKEN: "agent-token",
            CONF_CALLBACK_BASE_URL: "http://192.0.2.10:8123",
        },
        options={
            CONF_AGENT_HOST: "agent.local",
            CONF_AGENT_PORT: 8092,
            CONF_MAINTENANCE_TOKEN: "maintenance-token",
            CONF_CALLBACK_BASE_URL: "http://192.0.2.11:8123",
        },
    )

    result = _options_connection_schema(entry)(
        {
            CONF_AGENT_HOST: "agent.local",
            CONF_AGENT_PORT: 8092,
            CONF_AGENT_TOKEN: "agent-token",
            CONF_MAINTENANCE_TOKEN: "maintenance-token",
            CONF_CALLBACK_BASE_URL: "http://192.0.2.11:8123",
        }
    )

    assert result[CONF_AGENT_HOST] == "agent.local"
    assert result[CONF_MAINTENANCE_TOKEN] == "maintenance-token"
    assert result[CONF_CALLBACK_BASE_URL] == "http://192.0.2.11:8123"
    assert _current_connection_options(entry)[CONF_CALLBACK_BASE_URL] == (
        "http://192.0.2.11:8123"
    )


def test_reconfigure_schema_uses_effective_option_overrides() -> None:
    entry = SimpleNamespace(
        data={
            CONF_AGENT_HOST: "old-agent.local",
            CONF_AGENT_PORT: 8091,
            CONF_AGENT_TOKEN: "old-token",
            CONF_MAINTENANCE_TOKEN: "old-maintenance",
            CONF_CALLBACK_BASE_URL: "http://192.0.2.10:8123",
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.old",
            CONF_WEATHER_ENTITY_ID: "weather.old",
            CONF_DASHBOARD_ENTITIES: ["switch.old"],
            CONF_VIDEO_ENABLED: False,
            CONF_VIDEO_PORT: 6554,
            CONF_VIDEO_STREAM_PATH: "/doorbell-video",
            CONF_DEVICE_UI_ENABLED: False,
        },
        options={
            CONF_AGENT_HOST: "agent.local",
            CONF_AGENT_PORT: 8092,
            CONF_AGENT_TOKEN: "option-token",
            CONF_MAINTENANCE_TOKEN: "",
            CONF_CALLBACK_BASE_URL: "http://192.0.2.11:8123",
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.home",
            CONF_WEATHER_ENTITY_ID: "weather.home",
            CONF_DASHBOARD_ENTITIES: ["switch.entry"],
            CONF_VIDEO_ENABLED: True,
            CONF_CREATE_HOMEASSISTANT_USER: False,
            CONF_DOORSTATION_AUDIO_GAIN_DB: -3.5,
            CONF_RING_CAPTURE_AUDIO_GAIN_DB: 4.5,
            CONF_VIDEO_PORT: 6555,
            CONF_VIDEO_STREAM_PATH: "/custom-video",
            CONF_DEVICE_UI_ENABLED: True,
            CONF_ACTIONS: {
                "standby": {"domain": "button", "service": "press"},
            },
            CONF_DASHBOARD_PREVENT_RETURN: False,
            CONF_DEVICE_ACTIVATION_MODE: DEVICE_ACTIVATION_MODE_MANUAL,
        },
    )

    connection_schema = _reconfigure_connection_schema_from_current(entry)
    connection = connection_schema({})
    connection_with_callback = connection_schema(
        {CONF_CALLBACK_BASE_URL: "http://192.0.2.11:8123"}
    )
    features = _reconfigure_features_schema_from_current(entry)({})

    assert connection[CONF_AGENT_HOST] == "agent.local"
    assert connection[CONF_AGENT_PORT] == 8092
    assert connection[CONF_AGENT_TOKEN] == "option-token"
    assert connection[CONF_MAINTENANCE_TOKEN] == ""
    assert connection_with_callback[CONF_CALLBACK_BASE_URL] == (
        "http://192.0.2.11:8123"
    )
    assert CONF_ALARM_ENTITY_ID not in features
    assert CONF_WEATHER_ENTITY_ID not in features
    assert features[CONF_VIDEO_ENABLED] is True
    assert features[CONF_CREATE_HOMEASSISTANT_USER] is False
    assert features[CONF_DOORSTATION_AUDIO_GAIN_DB] == -3.5
    assert features[CONF_RING_CAPTURE_AUDIO_GAIN_DB] == 4.5
    assert CONF_VIDEO_PORT not in features
    assert CONF_VIDEO_STREAM_PATH not in features
    assert CONF_DEVICE_UI_ENABLED not in features
    assert CONF_DASHBOARD_PREVENT_RETURN not in features
    assert features[CONF_DEVICE_ACTIVATION_MODE] == DEVICE_ACTIVATION_MODE_MANUAL
    assert features[CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P] == DEFAULT_STAIR_LIGHT_P
    assert features[CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N] == DEFAULT_STAIR_LIGHT_N
    assert _current_feature_options(entry)[CONF_ALARM_ENTITY_ID] == "alarm_control_panel.home"
    assert _current_feature_options(entry)[CONF_WEATHER_ENTITY_ID] == "weather.home"
    assert _current_feature_options(entry)[CONF_DASHBOARD_ENTITIES] == ["switch.entry"]
    assert _current_feature_options(entry)[CONF_VIDEO_PORT] == 6555
    assert _current_feature_options(entry)[CONF_VIDEO_STREAM_PATH] == "/custom-video"
    assert _current_feature_options(entry)[CONF_DEVICE_UI_ENABLED] is True
    assert _current_feature_options(entry)[CONF_CREATE_HOMEASSISTANT_USER] is False
    assert _current_feature_options(entry)[CONF_DOORSTATION_AUDIO_GAIN_DB] == -3.5
    assert _current_feature_options(entry)[CONF_RING_CAPTURE_AUDIO_GAIN_DB] == 4.5
    assert _current_feature_options(entry)[CONF_ACTIONS] == {
        "standby": {"domain": "button", "service": "press"}
    }
    assert _current_feature_options(entry)[CONF_DASHBOARD_PREVENT_RETURN] is False


def test_reconfigure_hidden_gui_fields_keep_existing_actions() -> None:
    defaults = {
        CONF_ALARM_ENTITY_ID: "alarm_control_panel.home",
        CONF_WEATHER_ENTITY_ID: "weather.home",
        CONF_DASHBOARD_ENTITIES: ["switch.entry"],
        CONF_ACTIONS: {
            "scene:leave": {
                "data": {},
                "domain": "scene",
                "service": "turn_on",
                "target": {"entity_id": "scene.leave_home"},
            }
        },
        CONF_DASHBOARD_PREVENT_RETURN: False,
        CONF_VIDEO_PORT: 6555,
        CONF_VIDEO_STREAM_PATH: "/custom-video",
        CONF_DOORSTATION_AUDIO_GAIN_DB: -2.5,
        CONF_RING_CAPTURE_AUDIO_GAIN_DB: 5.5,
    }

    prepared = _feature_input_defaults(
        {
            CONF_DEVICE_UI_ENABLED: True,
            CONF_VIDEO_ENABLED: True,
            CONF_CREATE_HOMEASSISTANT_USER: True,
        },
        defaults,
    )
    feature_data, errors = _feature_input(prepared)

    assert errors == {}
    assert feature_data[CONF_ALARM_ENTITY_ID] == "alarm_control_panel.home"
    assert feature_data[CONF_WEATHER_ENTITY_ID] == "weather.home"
    assert feature_data[CONF_DASHBOARD_ENTITIES] == ["switch.entry"]
    assert feature_data[CONF_VIDEO_PORT] == 6555
    assert feature_data[CONF_VIDEO_STREAM_PATH] == "/custom-video"
    assert feature_data[CONF_DOORSTATION_AUDIO_GAIN_DB] == -2.5
    assert feature_data[CONF_RING_CAPTURE_AUDIO_GAIN_DB] == 5.5
    assert feature_data[CONF_ACTIONS] == defaults[CONF_ACTIONS]
    assert feature_data[CONF_DASHBOARD_PREVENT_RETURN] is False


def test_options_features_schema_excludes_dashboard_fields() -> None:
    entry = SimpleNamespace(
        data={
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.home",
            CONF_WEATHER_ENTITY_ID: "weather.home",
            CONF_DASHBOARD_ENTITIES: ["sensor.temperature"],
        },
        options={
            CONF_VIDEO_ENABLED: True,
            CONF_CREATE_HOMEASSISTANT_USER: True,
            CONF_ACTIONS: {"standby": {"domain": "button", "service": "press"}},
            CONF_DEVICE_UI_ENABLED: True,
            CONF_DASHBOARD_PREVENT_RETURN: False,
        },
    )

    result = _options_features_schema(entry)(
        {
            CONF_VIDEO_ENABLED: True,
        }
    )

    assert result[CONF_VIDEO_ENABLED] is True
    assert result[CONF_CREATE_HOMEASSISTANT_USER] is True
    assert result[CONF_DOORSTATION_AUDIO_GAIN_DB] == DEFAULT_DOORSTATION_AUDIO_GAIN_DB
    assert result[CONF_RING_CAPTURE_AUDIO_GAIN_DB] == DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB
    assert CONF_DEVICE_UI_ENABLED not in result
    assert CONF_DASHBOARD_PREVENT_RETURN not in result
    assert CONF_ACTIONS_JSON not in result


def test_dashboard_schema_keeps_dashboard_fields_on_own_page() -> None:
    schema = _dashboard_schema(
        "alarm_control_panel.home",
        "weather.home",
        _actions_json({"standby": {"domain": "button", "service": "press"}}),
        default_dashboard_entities=["sensor.temperature"],
        default_device_ui_enabled=True,
    )

    result = schema(
        {
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.home",
            CONF_WEATHER_ENTITY_ID: "weather.home",
            CONF_DASHBOARD_ENTITIES: ["switch.entry"],
            CONF_ACTIONS_JSON: '{"standby":{"domain":"button","service":"press"}}',
        }
    )

    assert result[CONF_ALARM_ENTITY_ID] == "alarm_control_panel.home"
    assert result[CONF_WEATHER_ENTITY_ID] == "weather.home"
    assert result[CONF_DASHBOARD_ENTITIES] == ["switch.entry"]
    assert result[CONF_ACTIONS_JSON] == '{"standby":{"domain":"button","service":"press"}}'
    assert result[CONF_DEVICE_UI_ENABLED] is True
    assert result[CONF_DASHBOARD_PREVENT_RETURN] is False


def test_dashboard_schema_orders_checkbox_options_first() -> None:
    schema = _dashboard_schema("", "")

    keys = [getattr(key, "schema", key) for key in schema.schema]

    assert keys[:3] == [
        CONF_DEVICE_UI_ENABLED,
        CONF_DASHBOARD_PREVENT_RETURN,
        CONF_DASHBOARD_DYNAMIC_HOMEPAGE,
    ]


def test_dashboard_schema_keeps_entity_display_controls_on_separate_page() -> None:
    schema = _dashboard_schema(
        "",
        "",
        default_dashboard_entities=["sensor.temperature"],
        default_dashboard_entity_display_overrides={
            "sensor.temperature": {
                "name": "entity_id",
                "secondary": "none",
            }
        },
    )

    result = schema({})

    assert "1. Temperature - Name" not in result
    assert "1. Temperature - Custom name" not in result
    assert "1. Temperature - Secondary line" not in result


def test_dashboard_entity_display_schema_adds_controls_for_selected_entities() -> None:
    schema = _dashboard_entity_display_schema(
        default_dashboard_entities=["sensor.temperature"],
        default_dashboard_entity_display_overrides={
            "sensor.temperature": {
                "name": "custom",
                "custom_name": "Outside",
                "secondary": "none",
            }
        },
    )

    result = schema({})

    assert result["1. Temperature - Name"] == "custom"
    assert result["1. Temperature - Custom name"] == "Outside"
    assert result["1. Temperature - Secondary line"] == "none"


def test_dashboard_entity_display_form_complete_requires_rendered_entity_fields() -> None:
    assert not _dashboard_entity_display_form_complete(
        {CONF_DASHBOARD_ENTITIES: ["sensor.temperature"]},
        ["sensor.temperature"],
    )
    assert _dashboard_entity_display_form_complete(
        {
            CONF_DASHBOARD_ENTITIES: ["sensor.temperature"],
            "1. Temperature - Name": "friendly_name",
            "1. Temperature - Custom name": "",
            "1. Temperature - Secondary line": "state",
        },
        ["sensor.temperature"],
    )


def test_options_features_schema_never_contains_dashboard_fields() -> None:
    entry = SimpleNamespace(
        data={
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.home",
            CONF_WEATHER_ENTITY_ID: "weather.home",
            CONF_DASHBOARD_ENTITIES: ["switch.entry"],
        },
        options={
            CONF_VIDEO_ENABLED: True,
            CONF_ACTIONS: {"standby": {"domain": "button", "service": "press"}},
            CONF_DEVICE_UI_ENABLED: False,
            CONF_DASHBOARD_PREVENT_RETURN: False,
        },
    )

    disabled_keys = _schema_key_names(_options_features_schema(entry))
    enabled_keys = _schema_key_names(
        _options_features_schema(entry, video_enabled=True)
    )

    assert disabled_keys[0] == CONF_VIDEO_ENABLED
    assert CONF_DEVICE_UI_ENABLED not in disabled_keys
    assert CONF_ALARM_ENTITY_ID not in disabled_keys
    assert CONF_WEATHER_ENTITY_ID not in disabled_keys
    assert CONF_DASHBOARD_ENTITIES not in disabled_keys
    assert CONF_ACTIONS_JSON not in disabled_keys
    assert CONF_DASHBOARD_PREVENT_RETURN not in disabled_keys
    assert enabled_keys[:4] == [
        CONF_VIDEO_ENABLED,
        CONF_CREATE_HOMEASSISTANT_USER,
        CONF_DOORSTATION_AUDIO_GAIN_DB,
        CONF_RING_CAPTURE_AUDIO_GAIN_DB,
    ]
    assert enabled_keys[4] == CONF_DEVICE_ACTIVATION_MODE
    assert CONF_DEVICE_UI_ENABLED not in enabled_keys
    assert CONF_ALARM_ENTITY_ID not in enabled_keys
    assert CONF_WEATHER_ENTITY_ID not in enabled_keys
    assert CONF_DASHBOARD_ENTITIES not in enabled_keys
    assert CONF_ACTIONS_JSON not in enabled_keys
    assert CONF_DASHBOARD_PREVENT_RETURN not in enabled_keys


def test_reconfigure_clears_stale_option_overrides() -> None:
    updates: list[dict[str, object]] = []

    class _FakeConfigEntries:
        def async_update_entry(self, entry: object, *, options: dict[str, object]) -> None:
            updates.append(options)

    hass = SimpleNamespace(config_entries=_FakeConfigEntries())
    entry = SimpleNamespace(
        options={
            CONF_AGENT_HOST: "old-option.local",
            CONF_VIDEO_ENABLED: False,
            CONF_DASHBOARD_PREVENT_RETURN: False,
            "unrelated": "keep",
        }
    )

    _clear_reconfigured_option_overrides(
        hass,
        entry,
        {
            CONF_AGENT_HOST: "new-data.local",
            CONF_VIDEO_ENABLED: True,
        },
    )

    assert updates == [
        {
            CONF_DASHBOARD_PREVENT_RETURN: False,
            "unrelated": "keep",
        }
    ]


def test_reconfigure_preserves_existing_unique_id() -> None:
    assert _reconfigure_unique_id(SimpleNamespace(unique_id="c300x-serial")) == "c300x-serial"
    assert _reconfigure_unique_id(SimpleNamespace(unique_id=None)) == "bticino_c300x"


def test_dashboard_schema_defaults_keep_page_open_disabled() -> None:
    result = _dashboard_schema("", "")({})

    assert result[CONF_DASHBOARD_PREVENT_RETURN] is False


def test_dashboard_input_defaults_preserve_existing_keep_page_open() -> None:
    defaults = {
        CONF_ALARM_ENTITY_ID: "",
        CONF_WEATHER_ENTITY_ID: "",
        CONF_DASHBOARD_ENTITIES: [],
        CONF_ACTIONS: {},
        CONF_DASHBOARD_PREVENT_RETURN: True,
    }

    result = _dashboard_input_defaults({}, defaults)

    assert result[CONF_DASHBOARD_PREVENT_RETURN] is True


@pytest.mark.parametrize(
    ("status", "label"),
    [
        ({}, "unknown"),
        ({"available": False, "state": "patched", "patched": True}, "unavailable"),
        ({"available": True, "patched": True}, "patched"),
        ({"available": True, "patched": False}, "original"),
        ({"available": True, "state": "partial", "patched": None}, "partial"),
        ({"available": True, "state": "restore_needed"}, "restore_needed"),
    ],
)
def test_qml_patch_status_label_is_concise(
    status: dict[str, object],
    label: str,
) -> None:
    assert _qml_patch_status_label(status) == label


def test_qml_patch_status_placeholder_refreshes_agent_once() -> None:
    api = _FakeQmlPatchApi(
        {"available": True, "patched": False, "state": "original"}
    )
    entry = SimpleNamespace(
        runtime_data=SimpleNamespace(
            api=api,
            qml_patch_status={},
            qml_patch_status_updated_at=None,
        )
    )

    placeholders = asyncio.run(_async_qml_patch_description_placeholders(entry))
    cached_placeholders = asyncio.run(_async_qml_patch_description_placeholders(entry))

    assert placeholders == {"qml_patch_status": "original"}
    assert cached_placeholders == {"qml_patch_status": "original"}
    assert api.calls == 1
    assert entry.runtime_data.qml_patch_status["state"] == "original"
    assert entry.runtime_data.qml_patch_status_updated_at is not None


def test_options_flow_runs_connection_features_and_dashboard_pages() -> None:
    entry = SimpleNamespace(
        data={
            CONF_AGENT_HOST: "old-agent.local",
            CONF_AGENT_PORT: 8091,
            CONF_AGENT_TOKEN: "old-token",
            CONF_MAINTENANCE_TOKEN: "",
            CONF_CALLBACK_BASE_URL: "",
            CONF_VIDEO_ENABLED: False,
            CONF_CREATE_HOMEASSISTANT_USER: False,
            CONF_DEVICE_ACTIVATION_MODE: DEVICE_ACTIVATION_MODE_AUTO,
            CONF_ALARM_ENTITY_ID: "",
            CONF_WEATHER_ENTITY_ID: "",
            CONF_DASHBOARD_ENTITIES: [],
            CONF_ACTIONS: {},
            CONF_DASHBOARD_PREVENT_RETURN: False,
            CONF_VIDEO_PORT: 6554,
            CONF_VIDEO_STREAM_PATH: DEFAULT_VIDEO_STREAM_PATH,
            CONF_DEVICE_UI_ENABLED: False,
        },
        options={},
        runtime_data=None,
    )
    flow = BticinoC300XOptionsFlow(entry)
    flow.async_show_form = lambda **kwargs: kwargs  # type: ignore[method-assign]
    flow.async_create_entry = lambda **kwargs: {  # type: ignore[method-assign]
        "type": "create_entry",
        **kwargs,
    }

    connection_form = asyncio.run(
        flow.async_step_connection(
            {
                CONF_AGENT_HOST: "agent.local",
                CONF_AGENT_PORT: 8092,
                CONF_AGENT_TOKEN: "agent-token",
                CONF_MAINTENANCE_TOKEN: "maintenance-token",
                CONF_CALLBACK_BASE_URL: "http://192.0.2.10:8123",
            }
        )
    )
    activation_form = asyncio.run(
        flow.async_step_features(
            {
                CONF_VIDEO_ENABLED: True,
                CONF_CREATE_HOMEASSISTANT_USER: False,
                CONF_RING_CAPTURE_AUDIO_GAIN_DB: 2.5,
                CONF_DEVICE_ACTIVATION_MODE: DEVICE_ACTIVATION_MODE_MANUAL,
                CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P: "02",
                CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N: "01",
            }
        )
    )
    activation_item_form = asyncio.run(
        flow.async_step_device_activations(
            {CONF_DEVICE_ACTIVATION_FLOW_ACTION: DEVICE_ACTIVATION_FLOW_ACTION_ADD}
        )
    )
    activation_manage_form = asyncio.run(
        flow.async_step_device_activation_item(
            {
                CONF_DEVICE_ACTIVATION_ITEM_ID: "front_lock",
                CONF_DEVICE_ACTIVATION_ITEM_NAME: "Front lock",
                CONF_DEVICE_ACTIVATION_ITEM_TYPE: "lock",
                CONF_DEVICE_ACTIVATION_ITEM_ADDRESS: "10",
            }
        )
    )
    dashboard_form = asyncio.run(
        flow.async_step_device_activations(
            {CONF_DEVICE_ACTIVATION_FLOW_ACTION: DEVICE_ACTIVATION_FLOW_ACTION_DONE}
        )
    )
    entity_options_form = asyncio.run(
        flow.async_step_dashboard(
            {
                CONF_DEVICE_UI_ENABLED: True,
                CONF_ALARM_ENTITY_ID: "alarm_control_panel.home",
                CONF_WEATHER_ENTITY_ID: "weather.home",
                CONF_DASHBOARD_ENTITIES: ["switch.entry"],
                CONF_ACTIONS_JSON: '{"standby":{"domain":"button","service":"press"}}',
                CONF_DASHBOARD_PREVENT_RETURN: True,
            }
        )
    )
    result = asyncio.run(
        flow.async_step_dashboard_entity_display(
            {
                "1. Entry - Name": "custom",
                "1. Entry - Custom name": "Entry",
                "1. Entry - Secondary line": "state",
            }
        )
    )

    assert connection_form["step_id"] == "features"
    assert activation_form["step_id"] == "device_activations"
    assert activation_item_form["step_id"] == "device_activation_item"
    assert activation_manage_form["step_id"] == "device_activations"
    assert dashboard_form["step_id"] == "dashboard"
    assert entity_options_form["step_id"] == "dashboard_entity_display"
    assert result["type"] == "create_entry"
    assert result["data"][CONF_AGENT_HOST] == "agent.local"
    assert result["data"][CONF_AGENT_PORT] == 8092
    assert result["data"][CONF_VIDEO_ENABLED] is True
    assert result["data"][CONF_CREATE_HOMEASSISTANT_USER] is False
    assert result["data"][CONF_DOORSTATION_AUDIO_GAIN_DB] == DEFAULT_DOORSTATION_AUDIO_GAIN_DB
    assert result["data"][CONF_RING_CAPTURE_AUDIO_GAIN_DB] == 2.5
    assert result["data"][CONF_DEVICE_ACTIVATION_MODE] == DEVICE_ACTIVATION_MODE_MANUAL
    assert result["data"][CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P] == "02"
    assert result["data"][CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N] == "01"
    assert result["data"][CONF_DEVICE_ACTIVATIONS] == [
        {
            "address": "10",
            "addressMode": "manual",
            "id": "front_lock",
            "name": "Front lock",
            "type": "lock",
        }
    ]
    assert result["data"][CONF_DEVICE_UI_ENABLED] is True
    assert result["data"][CONF_ALARM_ENTITY_ID] == "alarm_control_panel.home"
    assert result["data"][CONF_WEATHER_ENTITY_ID] == "weather.home"
    assert result["data"][CONF_DASHBOARD_ENTITIES] == ["switch.entry"]
    assert result["data"][CONF_DASHBOARD_PREVENT_RETURN] is True
    assert result["data"][CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES] == {
        "switch.entry": {"name": "custom", "custom_name": "Entry"}
    }
    assert result["data"][CONF_ACTIONS] == {
        "standby": {
            "data": {},
            "domain": "button",
            "service": "press",
            "target": {},
        }
    }


def test_reconfigure_flow_runs_connection_features_and_dashboard_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    entry = SimpleNamespace(
        unique_id="c300x-stable-id",
        data={
            CONF_AGENT_HOST: "old-agent.local",
            CONF_AGENT_PORT: 8091,
            CONF_AGENT_TOKEN: "old-token",
            CONF_MAINTENANCE_TOKEN: "",
            CONF_CALLBACK_BASE_URL: "",
            CONF_VIDEO_ENABLED: False,
            CONF_CREATE_HOMEASSISTANT_USER: False,
            CONF_DEVICE_ACTIVATION_MODE: DEVICE_ACTIVATION_MODE_AUTO,
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P: DEFAULT_STAIR_LIGHT_P,
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N: DEFAULT_STAIR_LIGHT_N,
            CONF_ALARM_ENTITY_ID: "",
            CONF_ALARM_PAGE_ENTITY_ID: "",
            CONF_WEATHER_ENTITY_ID: "",
            CONF_DASHBOARD_ENTITIES: [],
            CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: {},
            CONF_ACTIONS: {},
            CONF_DASHBOARD_PREVENT_RETURN: False,
            CONF_DASHBOARD_DYNAMIC_HOMEPAGE: True,
            CONF_VIDEO_PORT: 6554,
            CONF_VIDEO_STREAM_PATH: DEFAULT_VIDEO_STREAM_PATH,
            CONF_DEVICE_UI_ENABLED: False,
        },
        options={},
        runtime_data=SimpleNamespace(qml_patch_status={"available": True, "patched": True}),
    )
    flow = BticinoC300XConfigFlow()
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_update_entry=lambda *_args, **_kwargs: None,
        )
    )
    flow._get_reconfigure_entry = lambda: entry  # type: ignore[method-assign]
    flow.async_show_form = lambda **kwargs: kwargs  # type: ignore[method-assign]

    async def async_set_unique_id(unique_id: str, **_kwargs: object) -> None:
        calls.append(f"unique:{unique_id}")

    def abort_if_unique_id_mismatch() -> None:
        calls.append("mismatch_check")

    def update_and_abort(target: object, *, data_updates: dict[str, object]) -> dict[str, object]:
        calls.append("update")
        assert target is entry
        return {"type": "abort", "data_updates": data_updates}

    async def qml_patch_description_placeholders(_entry: object) -> dict[str, str]:
        return {"qml_patch_status": "patched"}

    monkeypatch.setattr(
        "custom_components.bticino_c300x.config_flow._async_qml_patch_description_placeholders",
        qml_patch_description_placeholders,
    )
    flow.async_set_unique_id = async_set_unique_id  # type: ignore[method-assign]
    flow._abort_if_unique_id_mismatch = abort_if_unique_id_mismatch  # type: ignore[method-assign]
    flow.async_update_and_abort = update_and_abort  # type: ignore[method-assign]

    features_form = asyncio.run(
        flow.async_step_reconfigure(
            {
                CONF_AGENT_HOST: "agent.local",
                CONF_AGENT_PORT: 8092,
                CONF_AGENT_TOKEN: "agent-token",
                CONF_MAINTENANCE_TOKEN: "maintenance-token",
                CONF_CALLBACK_BASE_URL: "http://192.0.2.20:8123",
                CONF_ROTATE_SHARED_SECRET: False,
            }
        )
    )
    activation_form = asyncio.run(
        flow.async_step_reconfigure_features(
            {
                CONF_VIDEO_ENABLED: True,
                CONF_CREATE_HOMEASSISTANT_USER: True,
                CONF_DEVICE_ACTIVATION_MODE: DEVICE_ACTIVATION_MODE_MANUAL,
                CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P: "02",
                CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N: "03",
            }
        )
    )
    activation_item_form = asyncio.run(
        flow.async_step_reconfigure_device_activations(
            {CONF_DEVICE_ACTIVATION_FLOW_ACTION: DEVICE_ACTIVATION_FLOW_ACTION_ADD}
        )
    )
    activation_manage_form = asyncio.run(
        flow.async_step_reconfigure_device_activation_item(
            {
                CONF_DEVICE_ACTIVATION_ITEM_ID: "front_lock",
                CONF_DEVICE_ACTIVATION_ITEM_NAME: "Front lock",
                CONF_DEVICE_ACTIVATION_ITEM_TYPE: "lock",
                CONF_DEVICE_ACTIVATION_ITEM_ADDRESS: "10",
            }
        )
    )
    dashboard_form = asyncio.run(
        flow.async_step_reconfigure_device_activations(
            {CONF_DEVICE_ACTIVATION_FLOW_ACTION: DEVICE_ACTIVATION_FLOW_ACTION_DONE}
        )
    )
    entity_display_form = asyncio.run(
        flow.async_step_reconfigure_dashboard(
            {
                CONF_DEVICE_UI_ENABLED: True,
                CONF_DASHBOARD_DYNAMIC_HOMEPAGE: False,
                CONF_ALARM_ENTITY_ID: "alarm_control_panel.home",
                CONF_ALARM_PAGE_ENTITY_ID: "button.stair_light",
                CONF_WEATHER_ENTITY_ID: "weather.home",
                CONF_DASHBOARD_ENTITIES: ["select.forwarding"],
                CONF_ACTIONS_JSON: "",
                CONF_DASHBOARD_PREVENT_RETURN: True,
            }
        )
    )
    result = asyncio.run(
        flow.async_step_reconfigure_dashboard_entity_display(
            {
                "1. Forwarding - Name": "friendly_name",
                "1. Forwarding - Custom name": "",
                "1. Forwarding - Secondary line": "last_changed",
            }
        )
    )

    assert features_form["step_id"] == "reconfigure_features"
    assert activation_form["step_id"] == "reconfigure_device_activations"
    assert activation_item_form["step_id"] == "reconfigure_device_activation_item"
    assert activation_manage_form["step_id"] == "reconfigure_device_activations"
    assert dashboard_form["step_id"] == "reconfigure_dashboard"
    assert entity_display_form["step_id"] == "reconfigure_dashboard_entity_display"
    assert result["type"] == "abort"
    assert result["data_updates"][CONF_AGENT_HOST] == "agent.local"
    assert result["data_updates"][CONF_AGENT_PORT] == 8092
    assert result["data_updates"][CONF_CALLBACK_BASE_URL] == "http://192.0.2.20:8123"
    assert result["data_updates"][CONF_CREATE_HOMEASSISTANT_USER] is True
    assert result["data_updates"][CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P] == "02"
    assert result["data_updates"][CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N] == "03"
    assert result["data_updates"][CONF_DEVICE_ACTIVATIONS] == [
        {
            "address": "10",
            "addressMode": "manual",
            "id": "front_lock",
            "name": "Front lock",
            "type": "lock",
        }
    ]
    assert result["data_updates"][CONF_ALARM_PAGE_ENTITY_ID] == "button.stair_light"
    assert result["data_updates"][CONF_DASHBOARD_DYNAMIC_HOMEPAGE] is False
    assert result["data_updates"][CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES] == {
        "select.forwarding": {
            "secondary": "last_changed",
        }
    }
    assert calls == ["unique:c300x-stable-id", "mismatch_check", "update"]


def test_options_flow_invalid_connection_stays_on_connection_page() -> None:
    entry = SimpleNamespace(data={}, options={}, runtime_data=None)
    flow = BticinoC300XOptionsFlow(entry)
    flow.async_show_form = lambda **kwargs: kwargs  # type: ignore[method-assign]

    result = asyncio.run(
        flow.async_step_connection(
            {
                CONF_AGENT_HOST: "",
                CONF_AGENT_PORT: 8091,
                CONF_AGENT_TOKEN: "",
                CONF_MAINTENANCE_TOKEN: "",
                CONF_CALLBACK_BASE_URL: "",
            }
        )
    )

    assert result["step_id"] == "connection"
    assert result["errors"] == {CONF_AGENT_HOST: "invalid_agent_host"}


def test_reconfigure_finish_rotates_secrets_and_clears_stale_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    option_updates: list[dict[str, object]] = []
    calls: list[str] = []
    entry = SimpleNamespace(
        unique_id="c300x-stable-id",
        options={
            CONF_AGENT_HOST: "old-option.local",
            CONF_VIDEO_ENABLED: False,
            CONF_DASHBOARD_PREVENT_RETURN: False,
            "keep": "value",
        },
    )
    flow = BticinoC300XConfigFlow()
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_update_entry=lambda target, **kwargs: option_updates.append(
                kwargs["options"]
            )
        )
    )
    flow._reconfigure_connection = {
        CONF_AGENT_HOST: "agent.local",
        CONF_AGENT_PORT: 8091,
        CONF_AGENT_TOKEN: "agent-token",
        CONF_MAINTENANCE_TOKEN: "maintenance-token",
        CONF_CALLBACK_BASE_URL: "http://192.0.2.10:8123",
        CONF_ROTATE_SHARED_SECRET: True,
    }
    flow._get_reconfigure_entry = lambda: entry  # type: ignore[method-assign]

    async def async_set_unique_id(unique_id: str, **_kwargs: object) -> None:
        calls.append(f"unique:{unique_id}")

    def abort_if_unique_id_mismatch() -> None:
        calls.append("mismatch_check")

    def update_and_abort(target: object, *, data_updates: dict[str, object]) -> dict[str, object]:
        assert target is entry
        return {"type": "abort", "data_updates": data_updates}

    secret_values = iter(["shared-secret", "event-secret"])
    monkeypatch.setattr(
        config_flow_module.secrets,
        "token_urlsafe",
        lambda _length: next(secret_values),
    )
    flow.async_set_unique_id = async_set_unique_id  # type: ignore[method-assign]
    flow._abort_if_unique_id_mismatch = abort_if_unique_id_mismatch  # type: ignore[method-assign]
    flow.async_update_and_abort = update_and_abort  # type: ignore[method-assign]

    result = asyncio.run(
        flow._async_finish_reconfigure(
            {
                CONF_VIDEO_ENABLED: True,
                CONF_CREATE_HOMEASSISTANT_USER: True,
                CONF_DEVICE_UI_ENABLED: False,
            }
        )
    )

    assert calls == ["unique:c300x-stable-id", "mismatch_check"]
    assert option_updates == [
        {
            CONF_DASHBOARD_PREVENT_RETURN: False,
            "keep": "value",
        }
    ]
    assert result["data_updates"][CONF_AGENT_HOST] == "agent.local"
    assert result["data_updates"][CONF_VIDEO_ENABLED] is True
    assert result["data_updates"][CONF_SHARED_SECRET] == "shared-secret"
    assert result["data_updates"][CONF_EVENT_WEBHOOK_TOKEN] == "event-secret"
    assert CONF_ROTATE_SHARED_SECRET not in result["data_updates"]


def test_options_flow_init_and_missing_state_redirect_to_current_pages() -> None:
    entry = SimpleNamespace(
        data={
            CONF_AGENT_HOST: "agent.local",
            CONF_AGENT_PORT: 8091,
            CONF_AGENT_TOKEN: "",
            CONF_MAINTENANCE_TOKEN: "",
            CONF_CALLBACK_BASE_URL: "",
            CONF_VIDEO_ENABLED: False,
            CONF_CREATE_HOMEASSISTANT_USER: False,
            CONF_DEVICE_ACTIVATION_MODE: DEVICE_ACTIVATION_MODE_AUTO,
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P: DEFAULT_STAIR_LIGHT_P,
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N: DEFAULT_STAIR_LIGHT_N,
            CONF_ALARM_ENTITY_ID: "",
            CONF_ALARM_PAGE_ENTITY_ID: "",
            CONF_WEATHER_ENTITY_ID: "",
            CONF_DASHBOARD_ENTITIES: [],
            CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: {},
            CONF_ACTIONS: {},
            CONF_DASHBOARD_PREVENT_RETURN: False,
            CONF_DASHBOARD_DYNAMIC_HOMEPAGE: True,
            CONF_VIDEO_PORT: 6554,
            CONF_VIDEO_STREAM_PATH: DEFAULT_VIDEO_STREAM_PATH,
            CONF_DEVICE_UI_ENABLED: False,
        },
        options={},
        runtime_data=None,
    )
    flow = BticinoC300XOptionsFlow(entry)
    flow.async_show_form = lambda **kwargs: kwargs  # type: ignore[method-assign]

    init_form = asyncio.run(flow.async_step_init())
    dashboard_redirect = asyncio.run(flow.async_step_dashboard())
    entity_redirect = asyncio.run(flow.async_step_dashboard_entity_display())

    assert init_form["step_id"] == "connection"
    assert dashboard_redirect["step_id"] == "features"
    assert entity_redirect["step_id"] == "features"


def test_options_flow_invalid_feature_input_stays_on_features_page() -> None:
    entry = SimpleNamespace(data={}, options={}, runtime_data=None)
    flow = BticinoC300XOptionsFlow(entry)
    flow.async_show_form = lambda **kwargs: kwargs  # type: ignore[method-assign]

    result = asyncio.run(
        flow.async_step_features(
            {
                CONF_VIDEO_ENABLED: True,
                CONF_DOORSTATION_AUDIO_GAIN_DB: 21,
                CONF_RING_CAPTURE_AUDIO_GAIN_DB: -21,
            }
        )
    )

    assert result["step_id"] == "features"
    assert result["errors"] == {
        CONF_DOORSTATION_AUDIO_GAIN_DB: "invalid_audio_gain",
        CONF_RING_CAPTURE_AUDIO_GAIN_DB: "invalid_audio_gain",
    }


def test_reconfigure_invalid_connection_stays_on_reconfigure_page() -> None:
    entry = SimpleNamespace(
        data={
            CONF_AGENT_HOST: "agent.local",
            CONF_AGENT_PORT: 8091,
            CONF_AGENT_TOKEN: "",
            CONF_MAINTENANCE_TOKEN: "",
            CONF_CALLBACK_BASE_URL: "",
        },
        options={},
    )
    flow = BticinoC300XConfigFlow()
    flow._get_reconfigure_entry = lambda: entry  # type: ignore[method-assign]
    flow.async_show_form = lambda **kwargs: kwargs  # type: ignore[method-assign]

    result = asyncio.run(
        flow.async_step_reconfigure(
            {
                CONF_AGENT_HOST: "",
                CONF_AGENT_PORT: 8091,
                CONF_AGENT_TOKEN: "",
                CONF_MAINTENANCE_TOKEN: "",
                CONF_CALLBACK_BASE_URL: "",
                CONF_ROTATE_SHARED_SECRET: False,
            }
        )
    )

    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {CONF_AGENT_HOST: "invalid_agent_host"}


def test_reconfigure_missing_state_redirects_to_current_pages() -> None:
    entry = SimpleNamespace(
        data={
            CONF_AGENT_HOST: "agent.local",
            CONF_AGENT_PORT: 8091,
            CONF_AGENT_TOKEN: "",
            CONF_MAINTENANCE_TOKEN: "",
            CONF_CALLBACK_BASE_URL: "",
            CONF_VIDEO_ENABLED: False,
            CONF_CREATE_HOMEASSISTANT_USER: False,
            CONF_DEVICE_ACTIVATION_MODE: DEVICE_ACTIVATION_MODE_AUTO,
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P: DEFAULT_STAIR_LIGHT_P,
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N: DEFAULT_STAIR_LIGHT_N,
            CONF_ALARM_ENTITY_ID: "",
            CONF_ALARM_PAGE_ENTITY_ID: "",
            CONF_WEATHER_ENTITY_ID: "",
            CONF_DASHBOARD_ENTITIES: [],
            CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: {},
            CONF_ACTIONS: {},
            CONF_DASHBOARD_PREVENT_RETURN: False,
            CONF_DASHBOARD_DYNAMIC_HOMEPAGE: True,
            CONF_VIDEO_PORT: 6554,
            CONF_VIDEO_STREAM_PATH: DEFAULT_VIDEO_STREAM_PATH,
            CONF_DEVICE_UI_ENABLED: False,
        },
        options={},
        runtime_data=None,
    )
    flow = BticinoC300XConfigFlow()
    flow._get_reconfigure_entry = lambda: entry  # type: ignore[method-assign]
    flow.async_show_form = lambda **kwargs: kwargs  # type: ignore[method-assign]

    dashboard_redirect = asyncio.run(flow.async_step_reconfigure_dashboard())
    entity_redirect = asyncio.run(flow.async_step_reconfigure_dashboard_entity_display())

    assert dashboard_redirect["step_id"] == "reconfigure_features"
    assert entity_redirect["step_id"] == "reconfigure_features"


class _FakeQmlPatchApi:
    def __init__(self, status: dict[str, object]) -> None:
        self._status = status
        self.calls = 0

    async def async_qml_patch_status(self) -> dict[str, object]:
        self.calls += 1
        return self._status


def _schema_key_names(schema: vol.Schema) -> list[str]:
    return [getattr(key, "schema", key) for key in schema.schema]
