from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.bticino_c300x import dashboard_select_texts as texts

TEXTS = {"enabled": "Smartphone", "homeassistant": "Home Assistant", "blocked": "Blockiert"}


@pytest.fixture
def hass(monkeypatch: pytest.MonkeyPatch) -> Any:
    entries = {
        "select.forwarding": SimpleNamespace(
            platform="bticino_c300x", translation_key="smartphone_forwarding_mode"
        ),
        "select.plain": SimpleNamespace(platform="other", translation_key=None),
    }
    monkeypatch.setattr(
        texts.er, "async_get", lambda _hass: SimpleNamespace(async_get=entries.get)
    )

    def translate(
        _hass: Any, state: str, domain: str, platform: str, key: str, device_class: Any
    ) -> str:
        assert (domain, platform, key, device_class) == (
            "select", "bticino_c300x", "smartphone_forwarding_mode", None,
        )
        return TEXTS.get(state, state)

    monkeypatch.setattr(texts.translation, "async_translate_state", translate)
    return SimpleNamespace(data={texts.er.DATA_REGISTRY: object()})


def _item(value: str, options: list[str]) -> dict[str, Any]:
    return {
        "state_label": value,
        "details": {"state_label": value},
        "controls": [{"command": "option", "kind": "choice", "value": value, "options": options}],
    }


def test_a_select_with_a_translation_key_gets_home_assistants_texts(hass: Any) -> None:
    options = ["enabled", "homeassistant", "blocked"]
    item = _item("blocked", options)

    texts.apply_select_texts(hass, "select.forwarding", SimpleNamespace(state="blocked"), item)

    control = item["controls"][0]
    assert control["options"] == options, "the display still sends the option back"
    assert control["value"] == "blocked"
    assert control["labels"] == ["Smartphone", "Home Assistant", "Blockiert"]
    assert item["state_label"] == "Blockiert"
    assert item["details"]["state_label"] == "Blockiert"


def test_another_secondary_line_is_left_alone(hass: Any) -> None:
    item = _item("blocked", ["enabled", "blocked"])
    item["state_label"] = "select.forwarding"

    texts.apply_select_texts(hass, "select.forwarding", SimpleNamespace(state="blocked"), item)

    assert item["state_label"] == "select.forwarding"


@pytest.mark.parametrize("entity_id", ["select.plain", "select.unknown", "input_select.scene"])
def test_a_select_without_translations_is_sent_unchanged(hass: Any, entity_id: str) -> None:
    item = _item("Night", ["Day", "Night"])

    texts.apply_select_texts(hass, entity_id, SimpleNamespace(state="Night"), item)

    assert item == _item("Night", ["Day", "Night"])


def test_a_home_assistant_without_an_entity_registry_is_tolerated() -> None:
    assert texts.select_option_texts(SimpleNamespace(), "select.forwarding", ["a"]) == ["a"]
    assert texts.select_option_texts(None, "select.forwarding", ["a"]) == ["a"]
