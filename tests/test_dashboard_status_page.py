"""Independent status-page visibility and configuration ordering."""

from unittest.mock import AsyncMock

import pytest
from test_config_flow_helpers import _options_area, _save_options_area
from test_executor import FakeEntry, FakeHass, FakeState, FakeStates, run

from custom_components.bticino_c300x import dashboard
from custom_components.bticino_c300x.config_flow_dashboard_pages import (
    dashboard_pages_input,
    dashboard_pages_schema,
)
from custom_components.bticino_c300x.const import (
    CONF_DASHBOARD_ENTITIES,
    CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
    CONF_DASHBOARD_STATUS_PAGE_ENABLED,
    CONF_DEVICE_UI_ENABLED,
    CONF_WEATHER_ENTITY_ID,
)


def test_status_then_energy_are_first_configuration_sections() -> None:
    schema = dashboard_pages_schema({})
    assert [str(key) for key in schema.schema][:3] == ["page_1", "energy_page", "page_2"]
    status = next(value for key, value in schema.schema.items() if str(key) == "page_1")
    enabled = next(key for key in status.schema.schema if str(key) == "enabled")
    assert enabled.default() is True


@pytest.mark.parametrize("enabled", [False, True])
def test_status_visibility_roundtrip_preserves_weather_and_tiles(enabled) -> None:
    settings, errors = dashboard_pages_input({}, {
        "page_1": {
            "enabled": enabled,
            "weather_entity_id": "weather.home",
            "entities": ["sensor.temperature"],
        },
    })
    assert not errors
    assert settings[CONF_DASHBOARD_STATUS_PAGE_ENABLED] is enabled
    assert settings[CONF_WEATHER_ENTITY_ID] == "weather.home"
    assert settings[CONF_DASHBOARD_ENTITIES] == ["sensor.temperature"]
    schema = dashboard_pages_schema(settings)
    status = next(value for key, value in schema.schema.items() if str(key) == "page_1")
    toggle = next(key for key in status.schema.schema if str(key) == "enabled")
    assert toggle.default() is enabled
    partial, errors = dashboard_pages_input(settings, {})
    assert not errors
    assert partial[CONF_DASHBOARD_STATUS_PAGE_ENABLED] is enabled


def test_disabled_status_survives_options_save_and_reopen() -> None:
    entry = FakeEntry(data={CONF_DEVICE_UI_ENABLED: True})
    _flow, result = _options_area(entry, "dashboard_pages", {
        "page_1": {"enabled": False, "weather_entity_id": "weather.home"},
    })
    _save_options_area(entry, result)
    assert entry.options[CONF_DASHBOARD_STATUS_PAGE_ENABLED] is False
    assert entry.options[CONF_WEATHER_ENTITY_ID] == "weather.home"
    _flow, result = _options_area(entry, "dashboard_pages")
    status = next(
        value for key, value in result["data_schema"].schema.items() if str(key) == "page_1"
    )
    toggle = next(key for key in status.schema.schema if str(key) == "enabled")
    assert toggle.default() is False


def test_disabled_status_hides_retained_content_and_skips_forecast(monkeypatch) -> None:
    entry = FakeEntry(
        data={CONF_DEVICE_UI_ENABLED: True, CONF_DASHBOARD_STATUS_PAGE_ENABLED: True},
        options={
            CONF_DASHBOARD_STATUS_PAGE_ENABLED: False,
            CONF_WEATHER_ENTITY_ID: "weather.home",
            CONF_DASHBOARD_ENTITIES: ["sensor.temperature"],
            CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: {"sensor.temperature": {"page": "C300X"}},
        },
    )
    hass = FakeHass(states=FakeStates({"sensor.temperature": FakeState("21")}))
    weather = AsyncMock(return_value=None)
    monkeypatch.setattr(dashboard, "async_dashboard_weather_payload", weather)
    result = run(dashboard.async_dashboard_payload(hass, entry))
    assert result["data"]["pages"] == []
    assert weather.call_args.args[1] is None
    assert run(dashboard.async_status(hass, entry))["dashboard_available"] is False
    entry.options[CONF_DASHBOARD_STATUS_PAGE_ENABLED] = True
    result = run(dashboard.async_dashboard_payload(hass, entry))
    assert [page["title"] for page in result["data"]["pages"]] == ["C300X"]
    assert weather.call_args.args[1] == "weather.home"


def test_notifications_do_not_restore_disabled_status_content(monkeypatch) -> None:
    entry = FakeEntry(data={
        CONF_DEVICE_UI_ENABLED: True,
        CONF_DASHBOARD_STATUS_PAGE_ENABLED: False,
        CONF_WEATHER_ENTITY_ID: "weather.home",
    })
    monkeypatch.setattr(dashboard, "notification_payload", lambda _entry: [{"message": "Hello"}])
    result = run(dashboard.async_dashboard_payload(FakeHass(), entry))
    assert result["data"]["pages"] == [{"title": ""}]
    assert result["notifications"] == [{"message": "Hello"}]
