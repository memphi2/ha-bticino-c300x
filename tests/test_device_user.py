from __future__ import annotations

from types import SimpleNamespace

from custom_components.bticino_c300x.device_user import (
    device_user_bootstrap_needed,
    device_user_bootstrap_satisfied,
    device_user_ready,
    device_user_repair_reason,
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


def test_device_user_status_helpers_keep_single_truth() -> None:
    ready = {
        "homeassistant_user_present": True,
        "media_identity_available": True,
        "routes_consistent": True,
        "device_routing_applied": True,
    }
    missing = {
        "homeassistant_user_present": True,
        "media_identity_available": True,
        "routes_consistent": False,
    }
    unavailable = {
        "available": False,
        "homeassistant_user_present": False,
        "routes_consistent": False,
    }

    assert device_user_ready(ready) is True
    assert device_user_bootstrap_satisfied(ready) is True
    assert device_user_bootstrap_needed(ready) is False
    assert device_user_repair_reason(ready) is None

    assert device_user_ready(missing) is False
    assert device_user_bootstrap_satisfied(missing) is False
    assert device_user_bootstrap_needed(missing) is True
    assert device_user_repair_reason(missing) == "homeassistant_routes_inconsistent"

    assert device_user_ready(unavailable) is None
    assert device_user_bootstrap_satisfied(unavailable) is False
    assert device_user_bootstrap_needed(unavailable) is False
    assert device_user_repair_reason(unavailable) is None
