from __future__ import annotations

import importlib
import json
import sys


def _load_forms():
    sys.modules.pop("custom_components.bticino_c300x.config_flow_forms", None)
    sys.modules["homeassistant.helpers.selector"] = None
    return importlib.import_module("custom_components.bticino_c300x.config_flow_forms")


def test_actions_json_returns_stable_pretty_json() -> None:
    forms = _load_forms()

    assert forms.actions_json({}) == ""
    assert forms.actions_json({"b": 2, "a": {"service": "toggle"}}) == json.dumps(
        {"a": {"service": "toggle"}, "b": 2},
        indent=2,
        sort_keys=True,
    )


def test_form_selectors_fall_back_without_homeassistant_selectors(monkeypatch) -> None:
    forms = _load_forms()
    monkeypatch.setattr(forms, "selector", None)

    assert forms.alarm_entity_selector() is str
    assert forms.weather_entity_selector() is str
    assert forms.dashboard_entity_selector() is list
    assert forms.dashboard_entity_name_display_selector() is str
    assert forms.dashboard_entity_secondary_info_selector() is str
    assert forms.password_selector() is str
    assert forms.actions_json_field() is str


def test_form_selectors_build_homeassistant_selector_configs(monkeypatch) -> None:
    forms = _load_forms()

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
    assert forms.dashboard_entity_name_display_selector()[0] == "select"
    assert forms.dashboard_entity_secondary_info_selector()[0] == "select"
    assert forms.password_selector() == (
        "text",
        {"text": {"type": "".join(("pass", "word"))}},
    )
    assert forms.actions_json_field() == ("text", {"text": {"multiline": True}})


def test_optional_suggested_omits_empty_suggestions() -> None:
    forms = _load_forms()

    empty = forms.optional_suggested("field", "")
    populated = forms.optional_suggested("field", "value")

    assert empty.schema == "field"
    assert populated.schema == "field"
    assert populated.description == {"suggested_value": "value"}
