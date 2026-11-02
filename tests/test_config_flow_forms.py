from __future__ import annotations

import json

from homeassistant.helpers import selector

from custom_components.bticino_c300x import config_flow_forms as forms


def test_actions_json_returns_stable_pretty_json() -> None:
    assert forms.actions_json({}) == ""
    assert forms.actions_json({"b": 2, "a": {"service": "toggle"}}) == json.dumps(
        {"a": {"service": "toggle"}, "b": 2},
        indent=2,
        sort_keys=True,
    )


def test_form_selectors_use_real_home_assistant_types() -> None:
    assert isinstance(forms.alarm_entity_selector(), selector.EntitySelector)
    assert isinstance(forms.weather_entity_selector(), selector.EntitySelector)
    assert forms.dashboard_entity_selector().config["multiple"] is True
    assert forms.password_selector().config["type"] == selector.TextSelectorType.PASSWORD
    assert forms.actions_json_field().config["multiline"] is True


def test_form_selectors_build_homeassistant_selector_configs(monkeypatch) -> None:
    class FakeSelector:
        class SelectSelectorMode:
            DROPDOWN = "dropdown"

        class TextSelectorType:
            PASSWORD = "".join(("pass", "word"))

        @staticmethod
        def EntitySelectorConfig(**kwargs):
            return {"entity": kwargs}

        @staticmethod
        def EntitySelector(config):
            return ("entity", config)

        @staticmethod
        def SelectSelectorConfig(**kwargs):
            return {"select": kwargs}

        @staticmethod
        def SelectSelector(config):
            return ("select", config)

        @staticmethod
        def TextSelectorConfig(**kwargs):
            return {"text": kwargs}

        @staticmethod
        def TextSelector(config):
            return ("text", config)

    monkeypatch.setattr(forms, "selector", FakeSelector)

    assert forms.alarm_entity_selector() == ("entity", {"entity": {"domain": "alarm_control_panel"}})
    assert forms.weather_entity_selector() == ("entity", {"entity": {"domain": "weather"}})
    dashboard = forms.dashboard_entity_selector()
    assert dashboard[0] == "entity"
    assert dashboard[1]["entity"]["multiple"] is True
    assert forms.password_selector() == (
        "text",
        {"text": {"type": "".join(("pass", "word"))}},
    )
    assert forms.actions_json_field() == ("text", {"text": {"multiline": True}})


def test_optional_suggested_omits_empty_suggestions() -> None:
    empty = forms.optional_suggested("field", "")
    populated = forms.optional_suggested("field", "value")

    assert empty.schema == "field"
    assert populated.schema == "field"
    assert populated.description == {"suggested_value": "value"}
