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
            "media_identity_source": "homeassistant",
            "account_label": " Home Assistant Test ",
            "account_id": "private-id",
        }
    )

    assert media_user_attributes(entry) == {
        "media_user_source": "homeassistant",
        "media_user_account": "homeassistant",
        "media_user_label": "Home Assistant Test",
    }
    assert media_user_attribute(entry) == {
        "media_user": {
            "source": "homeassistant",
            "account": "homeassistant",
            "label": "Home Assistant Test",
        }
    }


def test_media_user_attributes_reports_fallback_accounts_without_details() -> None:
    assert media_user_attributes(
        _entry({"media_identity_source": "existing_user_fallback"})
    ) == {
        "media_user_source": "existing_user_fallback",
        "media_user_account": "existing_user_fallback",
    }
    assert media_user_attributes(_entry({"media_identity_source": "unavailable"})) == {
        "media_user_source": "unavailable",
        "media_user_account": "unavailable",
    }


def test_media_user_attributes_ignores_empty_or_unknown_status() -> None:
    assert media_user_attributes(_entry(None)) == {}
    assert media_user_attributes(_entry({})) == {}
    assert media_user_attributes(_entry({"media_identity_source": ""})) == {}
    assert media_user_attributes(_entry({"media_identity_source": "fallback"})) == {
        "media_user_source": "fallback"
    }
    assert media_user_attribute(_entry({"media_identity_source": ""})) == {}
