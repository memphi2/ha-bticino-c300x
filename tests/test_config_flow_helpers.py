from __future__ import annotations

# ruff: noqa: E402, I001

import asyncio
import sys
import types
from types import SimpleNamespace

import pytest
import voluptuous as vol

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
config_validation = sys.modules.setdefault(
    "homeassistant.helpers.config_validation",
    types.ModuleType("homeassistant.helpers.config_validation"),
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
if not hasattr(core, "HomeAssistant"):
    core.HomeAssistant = HomeAssistant
if not hasattr(config_validation, "config_entry_only_config_schema"):
    config_validation.config_entry_only_config_schema = lambda _domain: dict
homeassistant.config_entries = config_entries
homeassistant.const = const
homeassistant.core = core
homeassistant.helpers = helpers
helpers.config_validation = config_validation

from custom_components.bticino_c300x.config_flow import (  # noqa: E402
    BticinoC300XConfigFlow,
    _agent_host,
    _alarm_entity_id,
    _actions_json,
    _agent_auth_input,
    _agent_auth_schema,
    _async_qml_patch_description_placeholders,
    _bootstrap_install_schema,
    _clear_reconfigured_option_overrides,
    _connection_input,
    _current_connection_options,
    _current_feature_options,
    _feature_input,
    _feature_input_defaults,
    _non_empty_string,
    _initial_connection_input,
    _needs_gui_details,
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
    _stair_light_address,
    _weather_entity_id,
)
from custom_components.bticino_c300x.const import (  # noqa: E402
    CONF_ACTIONS,
    CONF_ACTIONS_JSON,
    CONF_AGENT_TOKEN,
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_USE_SSL,
    CONF_ALARM_ENTITY_ID,
    CONF_BOOTSTRAP_APPLY_GUI_PATCH,
    CONF_BOOTSTRAP_SSH_PASSWORD,
    CONF_BOOTSTRAP_SSH_USERNAME,
    CONF_DASHBOARD_PREVENT_RETURN,
    CONF_DEVICE_UI_ENABLED,
    CONF_MAINTENANCE_TOKEN,
    CONF_STAIR_LIGHT_ADDRESS,
    CONF_VIDEO_ENABLED,
    CONF_VIDEO_PORT,
    CONF_VIDEO_STREAM_PATH,
    CONF_WEATHER_ENTITY_ID,
    DEFAULT_STAIR_LIGHT_ADDRESS,
    DEFAULT_VIDEO_STREAM_PATH,
)
from homeassistant.const import CONF_NAME  # noqa: E402


def test_stair_light_address_accepts_firmware_default() -> None:
    assert _stair_light_address(DEFAULT_STAIR_LIGHT_ADDRESS) == DEFAULT_STAIR_LIGHT_ADDRESS


@pytest.mark.parametrize("value", ["", "../bad", "abc", "10;reboot"])
def test_stair_light_address_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(vol.Invalid):
        _stair_light_address(value)


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
            CONF_AGENT_USE_SSL: False,
            CONF_AGENT_TOKEN: "   ",
            CONF_MAINTENANCE_TOKEN: "",
            CONF_STAIR_LIGHT_ADDRESS: DEFAULT_STAIR_LIGHT_ADDRESS,
        }
    )

    assert errors == {}
    assert data[CONF_AGENT_HOST] == "c300x-agent.local"
    assert data[CONF_AGENT_TOKEN] == ""


def test_initial_connection_input_collects_no_tokens_or_feature_fields() -> None:
    data, errors = _initial_connection_input(
        {
            CONF_NAME: "BTicino C300X",
            CONF_AGENT_HOST: " c300x-agent.local ",
            CONF_AGENT_PORT: 8091,
            CONF_AGENT_USE_SSL: False,
        },
        include_name=True,
    )

    assert errors == {}
    assert data == {
        CONF_NAME: "BTicino C300X",
        CONF_AGENT_HOST: "c300x-agent.local",
        CONF_AGENT_PORT: 8091,
        CONF_AGENT_USE_SSL: False,
    }


def test_agent_auth_requires_token_only_after_auth_challenge() -> None:
    data, errors = _agent_auth_input(
        {
            CONF_AGENT_TOKEN: "",
            CONF_STAIR_LIGHT_ADDRESS: DEFAULT_STAIR_LIGHT_ADDRESS,
        },
        require_agent_token=True,
    )
    optional_data, optional_errors = _agent_auth_input(
        {
            CONF_AGENT_TOKEN: "",
            CONF_STAIR_LIGHT_ADDRESS: DEFAULT_STAIR_LIGHT_ADDRESS,
        },
        require_agent_token=False,
    )

    assert errors == {CONF_AGENT_TOKEN: "required"}
    assert data[CONF_STAIR_LIGHT_ADDRESS] == DEFAULT_STAIR_LIGHT_ADDRESS
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
        }
    )

    assert CONF_AGENT_TOKEN not in result
    assert CONF_AGENT_USE_SSL not in result
    assert CONF_STAIR_LIGHT_ADDRESS not in result


def test_agent_auth_schema_keeps_tokens_on_second_setup_page() -> None:
    schema = _agent_auth_schema(require_agent_token=False)

    result = schema(
        {
            CONF_AGENT_TOKEN: "",
            CONF_MAINTENANCE_TOKEN: "",
            CONF_STAIR_LIGHT_ADDRESS: DEFAULT_STAIR_LIGHT_ADDRESS,
        }
    )

    assert result[CONF_AGENT_TOKEN] == ""
    assert result[CONF_STAIR_LIGHT_ADDRESS] == DEFAULT_STAIR_LIGHT_ADDRESS


def test_bootstrap_install_schema_collects_only_ephemeral_ssh_fields() -> None:
    schema = _bootstrap_install_schema()

    result = schema(
        {
            CONF_BOOTSTRAP_SSH_USERNAME: "root",
            CONF_BOOTSTRAP_SSH_PASSWORD: "temporary",
            CONF_BOOTSTRAP_APPLY_GUI_PATCH: False,
        }
    )

    assert result[CONF_BOOTSTRAP_SSH_USERNAME] == "root"
    assert result[CONF_BOOTSTRAP_SSH_PASSWORD] == "temporary"
    assert schema(
        {
            CONF_BOOTSTRAP_SSH_USERNAME: "root",
            CONF_BOOTSTRAP_SSH_PASSWORD: "temporary",
        }
    )[CONF_BOOTSTRAP_APPLY_GUI_PATCH] is True
    assert CONF_AGENT_TOKEN not in result


def test_reconfigure_schema_preserves_defaults() -> None:
    connection_schema = _reconfigure_connection_schema(
        "c300x-agent.local",
        8091,
        False,
        "token",
        "",
        "20#1",
    )
    feature_schema = _reconfigure_features_schema(
        "alarm_control_panel.home",
        "weather.home",
        True,
        6554,
        "/doorbell-video",
        True,
    )

    connection = connection_schema(
        {
            CONF_AGENT_HOST: "c300x-agent.local",
            CONF_AGENT_PORT: 8091,
            CONF_AGENT_TOKEN: "token",
        }
    )
    features = feature_schema({})

    assert connection[CONF_STAIR_LIGHT_ADDRESS] == "20#1"
    assert CONF_ALARM_ENTITY_ID not in features
    assert CONF_WEATHER_ENTITY_ID not in features
    assert features[CONF_VIDEO_ENABLED] is True
    assert features[CONF_DEVICE_UI_ENABLED] is True


def test_setup_features_schema_keeps_initial_video_defaults() -> None:
    schema = _setup_features_schema(
        "alarm_control_panel.home",
        "weather.home",
        True,
        6554,
        "/doorbell-video",
        True,
    )

    result = schema({})

    assert CONF_ALARM_ENTITY_ID not in result
    assert CONF_WEATHER_ENTITY_ID not in result
    assert result[CONF_VIDEO_ENABLED] is True
    assert result[CONF_VIDEO_STREAM_PATH] == "/doorbell-video"
    assert result[CONF_DEVICE_UI_ENABLED] is True
    assert result[CONF_DASHBOARD_PREVENT_RETURN] is True


def test_feature_input_allows_clearing_gui_entities_and_actions() -> None:
    data, errors = _feature_input(
        {
            CONF_DEVICE_UI_ENABLED: True,
            CONF_ALARM_ENTITY_ID: "",
            CONF_WEATHER_ENTITY_ID: "",
            CONF_ACTIONS_JSON: "",
            CONF_DASHBOARD_PREVENT_RETURN: True,
        }
    )

    assert errors == {}
    assert data[CONF_ALARM_ENTITY_ID] == ""
    assert data[CONF_WEATHER_ENTITY_ID] == ""
    assert data[CONF_ACTIONS] == {}
    assert data[CONF_DASHBOARD_PREVENT_RETURN] is True


def test_feature_schema_serializes_gui_entity_selectors() -> None:
    schema = _setup_features_schema(
        "alarm_control_panel.home",
        "weather.home",
        True,
        6554,
        "/doorbell-video",
        True,
    )

    result = schema({})

    assert result[CONF_DEVICE_UI_ENABLED] is True
    assert CONF_ALARM_ENTITY_ID not in result
    assert CONF_WEATHER_ENTITY_ID not in result
    assert result[CONF_DASHBOARD_PREVENT_RETURN] is True


def test_feature_input_allows_empty_gui_optional_fields() -> None:
    data, errors = _feature_input(
        {
            CONF_DEVICE_UI_ENABLED: True,
            CONF_VIDEO_ENABLED: True,
            CONF_VIDEO_PORT: 6554,
            CONF_VIDEO_STREAM_PATH: DEFAULT_VIDEO_STREAM_PATH,
        }
    )

    assert errors == {}
    assert data[CONF_ALARM_ENTITY_ID] == ""
    assert data[CONF_WEATHER_ENTITY_ID] == ""
    assert data[CONF_ACTIONS] == {}
    assert data[CONF_DASHBOARD_PREVENT_RETURN] is True


def test_initial_feature_input_defaults_video_enabled() -> None:
    data, errors = _feature_input({}, default_video_enabled=True)

    assert errors == {}
    assert data[CONF_VIDEO_ENABLED] is True


def test_feature_input_keeps_selected_gui_features() -> None:
    data, errors = _feature_input(
        {
            CONF_DEVICE_UI_ENABLED: True,
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.home",
            CONF_WEATHER_ENTITY_ID: "weather.home",
            CONF_ACTIONS_JSON: '{"standby":{"domain":"button","service":"press"}}',
            CONF_DASHBOARD_PREVENT_RETURN: False,
        }
    )

    assert errors == {}
    assert data[CONF_ALARM_ENTITY_ID] == "alarm_control_panel.home"
    assert data[CONF_WEATHER_ENTITY_ID] == "weather.home"
    assert data[CONF_ACTIONS] == {
        "standby": {
            "data": {},
            "domain": "button",
            "service": "press",
            "target": {},
        }
    }
    assert data[CONF_DASHBOARD_PREVENT_RETURN] is False


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
                    CONF_AGENT_USE_SSL: False,
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
        CONF_AGENT_USE_SSL: False,
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
                    CONF_BOOTSTRAP_APPLY_GUI_PATCH: False,
                }
            )
        )

    assert calls == ["unique:bticino_c300x:c300x.local:8091", "abort"]


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
    result = asyncio.run(
        flow.async_step_user_features(
            {
                CONF_DEVICE_UI_ENABLED: False,
                CONF_VIDEO_ENABLED: True,
                CONF_VIDEO_PORT: 6554,
                CONF_VIDEO_STREAM_PATH: DEFAULT_VIDEO_STREAM_PATH,
            }
        )
    )

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
        CONF_AGENT_USE_SSL: False,
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
    monkeypatch.setattr(
        "custom_components.bticino_c300x.config_flow._async_agent_stable_unique_id",
        agent_stable_unique_id,
    )

    asyncio.run(flow._async_adopt_agent_unique_id(api_token="known-token"))
    result = asyncio.run(
        flow.async_step_user_features(
            {
                CONF_DEVICE_UI_ENABLED: False,
                CONF_VIDEO_ENABLED: True,
                CONF_VIDEO_PORT: 6554,
                CONF_VIDEO_STREAM_PATH: DEFAULT_VIDEO_STREAM_PATH,
            }
        )
    )

    assert result["title"] == "BTicino C300X"
    assert calls == [
        "agent_id:c300x.local:known-token",
        "abort_flow:zeroconf-flow",
        "unique:c300xaabbcc001122:False",
        "abort_check",
        "create_entry",
    ]


def test_feature_schemas_place_gui_patch_first_and_hide_gui_dependent_fields() -> None:
    setup_schema = _setup_features_schema(
        "alarm_control_panel.home",
        "weather.home",
        True,
        6554,
        "/doorbell-video",
        False,
    )
    reconfigure_schema = _reconfigure_features_schema(
        "alarm_control_panel.home",
        "weather.home",
        True,
        6554,
        "/doorbell-video",
        False,
    )

    assert _schema_key_names(setup_schema)[0] == CONF_DEVICE_UI_ENABLED
    assert CONF_ALARM_ENTITY_ID not in _schema_key_names(setup_schema)
    assert CONF_WEATHER_ENTITY_ID not in _schema_key_names(setup_schema)
    assert _schema_key_names(reconfigure_schema)[0] == CONF_DEVICE_UI_ENABLED
    assert CONF_ALARM_ENTITY_ID not in _schema_key_names(reconfigure_schema)
    assert CONF_WEATHER_ENTITY_ID not in _schema_key_names(reconfigure_schema)

    enabled_schema = _setup_features_schema(
        "alarm_control_panel.home",
        "weather.home",
        True,
        6554,
        "/doorbell-video",
        True,
    )

    assert _schema_key_names(enabled_schema)[:2] == [
        CONF_DEVICE_UI_ENABLED,
        CONF_ALARM_ENTITY_ID,
    ]
    assert CONF_WEATHER_ENTITY_ID in _schema_key_names(enabled_schema)


def test_initial_flow_defaults_gui_patch_enabled() -> None:
    flow = BticinoC300XConfigFlow()

    assert flow._setup_device_ui_default is True


def test_options_connection_schema_keeps_connection_on_first_page() -> None:
    entry = SimpleNamespace(
        data={
            CONF_AGENT_HOST: "old-agent.local",
            CONF_AGENT_PORT: 8091,
            CONF_AGENT_USE_SSL: False,
            CONF_AGENT_TOKEN: "agent-token",
            CONF_STAIR_LIGHT_ADDRESS: DEFAULT_STAIR_LIGHT_ADDRESS,
        },
        options={
            CONF_AGENT_HOST: "agent.local",
            CONF_AGENT_PORT: 8092,
            CONF_AGENT_USE_SSL: True,
            CONF_MAINTENANCE_TOKEN: "maintenance-token",
            CONF_STAIR_LIGHT_ADDRESS: "20#1",
        },
    )

    result = _options_connection_schema(entry)(
        {
            CONF_AGENT_HOST: "agent.local",
            CONF_AGENT_PORT: 8092,
            CONF_AGENT_USE_SSL: True,
            CONF_AGENT_TOKEN: "agent-token",
            CONF_MAINTENANCE_TOKEN: "maintenance-token",
            CONF_STAIR_LIGHT_ADDRESS: "20#1",
        }
    )

    assert result[CONF_AGENT_HOST] == "agent.local"
    assert result[CONF_MAINTENANCE_TOKEN] == "maintenance-token"
    assert _current_connection_options(entry)[CONF_STAIR_LIGHT_ADDRESS] == "20#1"


def test_reconfigure_schema_uses_effective_option_overrides() -> None:
    entry = SimpleNamespace(
        data={
            CONF_AGENT_HOST: "old-agent.local",
            CONF_AGENT_PORT: 8091,
            CONF_AGENT_USE_SSL: False,
            CONF_AGENT_TOKEN: "old-token",
            CONF_MAINTENANCE_TOKEN: "old-maintenance",
            CONF_STAIR_LIGHT_ADDRESS: DEFAULT_STAIR_LIGHT_ADDRESS,
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.old",
            CONF_WEATHER_ENTITY_ID: "weather.old",
            CONF_VIDEO_ENABLED: False,
            CONF_VIDEO_PORT: 6554,
            CONF_VIDEO_STREAM_PATH: "/doorbell-video",
            CONF_DEVICE_UI_ENABLED: False,
        },
        options={
            CONF_AGENT_HOST: "agent.local",
            CONF_AGENT_PORT: 8092,
            CONF_AGENT_USE_SSL: True,
            CONF_AGENT_TOKEN: "option-token",
            CONF_MAINTENANCE_TOKEN: "",
            CONF_STAIR_LIGHT_ADDRESS: "20#1",
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.home",
            CONF_WEATHER_ENTITY_ID: "weather.home",
            CONF_VIDEO_ENABLED: True,
            CONF_VIDEO_PORT: 6555,
            CONF_VIDEO_STREAM_PATH: "/custom-video",
            CONF_DEVICE_UI_ENABLED: True,
            CONF_ACTIONS: {
                "standby": {"domain": "button", "service": "press"},
            },
            CONF_DASHBOARD_PREVENT_RETURN: False,
        },
    )

    connection = _reconfigure_connection_schema_from_current(entry)({})
    features = _reconfigure_features_schema_from_current(entry)({})

    assert connection[CONF_AGENT_HOST] == "agent.local"
    assert connection[CONF_AGENT_PORT] == 8092
    assert connection[CONF_AGENT_USE_SSL] is True
    assert connection[CONF_AGENT_TOKEN] == "option-token"
    assert connection[CONF_MAINTENANCE_TOKEN] == ""
    assert connection[CONF_STAIR_LIGHT_ADDRESS] == "20#1"
    assert CONF_ALARM_ENTITY_ID not in features
    assert CONF_WEATHER_ENTITY_ID not in features
    assert features[CONF_VIDEO_ENABLED] is True
    assert features[CONF_VIDEO_PORT] == 6555
    assert features[CONF_VIDEO_STREAM_PATH] == "/custom-video"
    assert features[CONF_DEVICE_UI_ENABLED] is True
    assert features[CONF_DASHBOARD_PREVENT_RETURN] is False
    assert _current_feature_options(entry)[CONF_ALARM_ENTITY_ID] == "alarm_control_panel.home"
    assert _current_feature_options(entry)[CONF_WEATHER_ENTITY_ID] == "weather.home"
    assert _current_feature_options(entry)[CONF_DEVICE_UI_ENABLED] is True
    assert _current_feature_options(entry)[CONF_ACTIONS] == {
        "standby": {"domain": "button", "service": "press"}
    }
    assert _current_feature_options(entry)[CONF_DASHBOARD_PREVENT_RETURN] is False


def test_reconfigure_hidden_gui_fields_keep_existing_actions() -> None:
    defaults = {
        CONF_ALARM_ENTITY_ID: "alarm_control_panel.home",
        CONF_WEATHER_ENTITY_ID: "weather.home",
        CONF_ACTIONS: {
            "scene:leave": {
                "data": {},
                "domain": "scene",
                "service": "turn_on",
                "target": {"entity_id": "scene.leave_home"},
            }
        },
        CONF_DASHBOARD_PREVENT_RETURN: False,
    }

    prepared = _feature_input_defaults(
        {
            CONF_DEVICE_UI_ENABLED: True,
            CONF_VIDEO_ENABLED: True,
            CONF_VIDEO_PORT: 6554,
            CONF_VIDEO_STREAM_PATH: DEFAULT_VIDEO_STREAM_PATH,
        },
        defaults,
    )
    feature_data, errors = _feature_input(prepared)

    assert errors == {}
    assert feature_data[CONF_ALARM_ENTITY_ID] == "alarm_control_panel.home"
    assert feature_data[CONF_WEATHER_ENTITY_ID] == "weather.home"
    assert feature_data[CONF_ACTIONS] == defaults[CONF_ACTIONS]
    assert feature_data[CONF_DASHBOARD_PREVENT_RETURN] is False


def test_options_features_schema_keeps_dashboard_features_on_second_page() -> None:
    entry = SimpleNamespace(
        data={
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.home",
            CONF_WEATHER_ENTITY_ID: "weather.home",
        },
        options={
            CONF_VIDEO_ENABLED: True,
            CONF_VIDEO_PORT: 6554,
            CONF_VIDEO_STREAM_PATH: DEFAULT_VIDEO_STREAM_PATH,
            CONF_ACTIONS: {"standby": {"domain": "button", "service": "press"}},
            CONF_DEVICE_UI_ENABLED: True,
            CONF_DASHBOARD_PREVENT_RETURN: False,
        },
    )

    result = _options_features_schema(entry)(
        {
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.home",
            CONF_WEATHER_ENTITY_ID: "weather.home",
            CONF_VIDEO_ENABLED: True,
            CONF_VIDEO_PORT: 6554,
            CONF_VIDEO_STREAM_PATH: DEFAULT_VIDEO_STREAM_PATH,
            CONF_ACTIONS_JSON: _actions_json(entry.options[CONF_ACTIONS]),
            CONF_DEVICE_UI_ENABLED: True,
            CONF_DASHBOARD_PREVENT_RETURN: False,
        }
    )

    assert result[CONF_ALARM_ENTITY_ID] == "alarm_control_panel.home"
    assert result[CONF_WEATHER_ENTITY_ID] == "weather.home"
    assert result[CONF_VIDEO_ENABLED] is True
    assert result[CONF_DEVICE_UI_ENABLED] is True
    assert result[CONF_DASHBOARD_PREVENT_RETURN] is False


def test_options_features_schema_hides_gui_dependent_fields_until_enabled() -> None:
    entry = SimpleNamespace(
        data={
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.home",
            CONF_WEATHER_ENTITY_ID: "weather.home",
        },
        options={
            CONF_VIDEO_ENABLED: True,
            CONF_VIDEO_PORT: 6554,
            CONF_VIDEO_STREAM_PATH: DEFAULT_VIDEO_STREAM_PATH,
            CONF_ACTIONS: {"standby": {"domain": "button", "service": "press"}},
            CONF_DEVICE_UI_ENABLED: False,
            CONF_DASHBOARD_PREVENT_RETURN: False,
        },
    )

    disabled_keys = _schema_key_names(_options_features_schema(entry))
    enabled_keys = _schema_key_names(
        _options_features_schema(entry, device_ui_enabled=True)
    )

    assert disabled_keys[0] == CONF_DEVICE_UI_ENABLED
    assert CONF_ALARM_ENTITY_ID not in disabled_keys
    assert CONF_WEATHER_ENTITY_ID not in disabled_keys
    assert CONF_ACTIONS_JSON not in disabled_keys
    assert CONF_DASHBOARD_PREVENT_RETURN not in disabled_keys
    assert enabled_keys[:2] == [CONF_DEVICE_UI_ENABLED, CONF_ALARM_ENTITY_ID]
    assert CONF_WEATHER_ENTITY_ID in enabled_keys
    assert CONF_ACTIONS_JSON in enabled_keys
    assert CONF_DASHBOARD_PREVENT_RETURN in enabled_keys


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


def test_gui_detail_detection_redisplays_after_enabling_hidden_patch_fields() -> None:
    assert _needs_gui_details({CONF_DEVICE_UI_ENABLED: True})
    assert not _needs_gui_details(
        {CONF_DEVICE_UI_ENABLED: True},
        details_shown=True,
    )
    assert not _needs_gui_details(
        {
            CONF_DEVICE_UI_ENABLED: True,
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.home",
            CONF_WEATHER_ENTITY_ID: "weather.home",
        }
    )
    assert not _needs_gui_details({CONF_DEVICE_UI_ENABLED: False})


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


class _FakeQmlPatchApi:
    def __init__(self, status: dict[str, object]) -> None:
        self._status = status
        self.calls = 0

    async def async_qml_patch_status(self) -> dict[str, object]:
        self.calls += 1
        return self._status


def _schema_key_names(schema: vol.Schema) -> list[str]:
    return [getattr(key, "schema", key) for key in schema.schema]
