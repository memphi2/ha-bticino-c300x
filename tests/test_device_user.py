from __future__ import annotations

from types import SimpleNamespace

from custom_components.bticino_c300x.device_user import (
    homeassistant_account_label,
    media_user_attribute,
    media_user_attributes,
)


def _hass(location_name: str | None) -> SimpleNamespace:
    return SimpleNamespace(config=SimpleNamespace(location_name=location_name))


def _entry(status: object) -> SimpleNamespace:
    return SimpleNamespace(runtime_data=SimpleNamespace(device_user_status=status))


def test_homeassistant_account_label_uses_location_name_when_specific() -> None:
    assert homeassistant_account_label(_hass(None)) == "Home Assistant"
    assert homeassistant_account_label(_hass(" Home Assistant ")) == "Home Assistant"
    assert homeassistant_account_label(_hass("Villa")) == "Home Assistant Villa"


def test_media_user_attributes_exposes_safe_homeassistant_label_only() -> None:
    entry = _entry(
        {
            "homeassistant_user_present": True,
            "account_label": " Home Assistant Test ",
            "account_id": "private-id",
        }
    )

    assert media_user_attributes(entry) == {
        "media_user_account": "homeassistant",
        "media_user_label": "Home Assistant Test",
    }
    assert media_user_attribute(entry) == {
        "media_user": {
            "account": "homeassistant",
            "label": "Home Assistant Test",
        }
    }


def test_media_user_attributes_ignores_empty_or_unknown_status() -> None:
    assert media_user_attributes(_entry(None)) == {}
    assert media_user_attributes(_entry({})) == {}
    assert media_user_attributes(_entry({"homeassistant_user_present": False})) == {}
    assert media_user_attribute(_entry({"homeassistant_user_present": False})) == {}
