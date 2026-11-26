from __future__ import annotations

from types import SimpleNamespace

from custom_components.bticino_c300x import config_schemas as config_schemas_module
from custom_components.bticino_c300x.config_schemas import (
    audio_fine_gain_selector,
    door_audio_level_selector,
    reconfigure_connection_schema,
)
from custom_components.bticino_c300x.const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_CALLBACK_BASE_URL,
    CONF_MAINTENANCE_TOKEN,
    CONF_ROTATE_SHARED_SECRET,
)


def test_fine_adjustment_selector_uses_home_assistant_number_selector(
    monkeypatch,
) -> None:
    class _NumberSelectorConfig:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class _NumberSelector:
        def __init__(self, config: _NumberSelectorConfig) -> None:
            self.config = config

    fake_selector = SimpleNamespace(
        NumberSelector=_NumberSelector,
        NumberSelectorConfig=_NumberSelectorConfig,
        NumberSelectorMode=SimpleNamespace(SLIDER="slider"),
    )
    monkeypatch.setattr(config_schemas_module, "selector", fake_selector)

    result = audio_fine_gain_selector()

    assert result.config.kwargs == {
        "min": -10,
        "max": 10,
        "step": 1,
        "mode": "slider",
        "unit_of_measurement": "dB",
    }


def test_door_level_selector_offers_the_five_steps(monkeypatch) -> None:
    class _SelectSelectorConfig:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class _SelectSelector:
        def __init__(self, config: _SelectSelectorConfig) -> None:
            self.config = config

    fake_selector = SimpleNamespace(
        SelectSelector=_SelectSelector,
        SelectSelectorConfig=_SelectSelectorConfig,
        SelectSelectorMode=SimpleNamespace(DROPDOWN="dropdown"),
    )
    monkeypatch.setattr(config_schemas_module, "selector", fake_selector)

    result = door_audio_level_selector()

    assert result.config.kwargs == {
        "options": ["0", "3", "6", "9", "12"],
        "translation_key": "door_audio_level",
        "mode": "dropdown",
    }


def test_reconfigure_connection_schema_allows_empty_callback_suggestion() -> None:
    schema = reconfigure_connection_schema(
        default_agent_host="c300x.local",
        default_agent_port=8080,
        default_agent_token="token",
        default_maintenance_token="maintenance",
        default_callback_base_url="",
    )

    validated = schema({CONF_AGENT_HOST: "host.local", CONF_AGENT_TOKEN: "new-token"})

    assert validated == {
        CONF_AGENT_HOST: "host.local",
        CONF_AGENT_PORT: 8080,
        CONF_AGENT_TOKEN: "new-token",
        CONF_MAINTENANCE_TOKEN: "maintenance",
        CONF_ROTATE_SHARED_SECRET: False,
    }
    assert CONF_CALLBACK_BASE_URL not in validated
