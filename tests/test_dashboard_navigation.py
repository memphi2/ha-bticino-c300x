"""The display changes pages with arrows or with the favourites bar.

The setting is one choice for the whole display. It is part of the display
form, is saved with the other dashboard options and reaches the display as
``navigation`` in the dashboard data. With the bar, the status page has no
page list of its own: the bar and its More entry already reach every page.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_display_settings import _OptionsAreas
from test_executor import FakeEntry, FakeHass, FakeState, FakeStates, run

from custom_components.bticino_c300x import dashboard
from custom_components.bticino_c300x.config_flow_dashboard import dashboard_schema
from custom_components.bticino_c300x.config_flow_dashboard_pages import (
    dashboard_pages_input,
)
from custom_components.bticino_c300x.const import (
    CONF_DASHBOARD_ENTITIES,
    CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
    CONF_DASHBOARD_NAVIGATION,
    CONF_DEVICE_UI_ENABLED,
    CONF_ENERGY_PAGE,
)
from custom_components.bticino_c300x.dashboard_config import (
    configured_dashboard_navigation,
)
from custom_components.bticino_c300x.dashboard_page_order import dashboard_navigation


def _navigation_field(schema):
    return next(key for key in schema.schema if str(key) == CONF_DASHBOARD_NAVIGATION)


@pytest.mark.parametrize("value", [None, "", "pager", "TABS", "bar", 1, True, ["tabs"]])
def test_anything_but_the_bar_is_the_arrows(value) -> None:
    assert dashboard_navigation(value) == "pager"
    assert dashboard_navigation("tabs") == "tabs"
    assert configured_dashboard_navigation(FakeEntry(options={CONF_DASHBOARD_NAVIGATION: value})) == "pager"


def test_the_display_form_offers_the_choice_and_defaults_to_arrows() -> None:
    schema = dashboard_schema()
    field = _navigation_field(schema)
    assert field.default() == "pager"
    assert schema.schema[field].config["options"] == ["pager", "tabs"]
    assert schema.schema[field].config["translation_key"] == CONF_DASHBOARD_NAVIGATION
    assert _navigation_field(dashboard_schema(default_dashboard_navigation="tabs")).default() == "tabs"
    assert _navigation_field(dashboard_schema(default_dashboard_navigation="nonsense")).default() == "pager"


def test_the_pages_form_keeps_the_saved_choice() -> None:
    settings, errors = dashboard_pages_input({CONF_DASHBOARD_NAVIGATION: "tabs"}, {
        "page_1": {"enabled": True, "entities": ["sensor.temperature"]},
    })
    assert not errors
    assert settings[CONF_DASHBOARD_NAVIGATION] == "tabs"


def test_the_choice_survives_an_options_save_and_reopen() -> None:
    entry = SimpleNamespace(
        entry_id="navigation", data={CONF_DEVICE_UI_ENABLED: True},
        options={}, runtime_data=None, update_listeners=[],
    )
    areas = _OptionsAreas(entry)
    result = run(areas._flow().async_step_dashboard({
        CONF_DEVICE_UI_ENABLED: True, CONF_DASHBOARD_NAVIGATION: "tabs",
    }))
    assert result["type"] == "menu"
    assert entry.options[CONF_DASHBOARD_NAVIGATION] == "tabs"
    result = run(areas._flow().async_step_dashboard())
    assert _navigation_field(result["data_schema"]).default() == "tabs"
    # Saving another area of the options keeps the choice.
    result = run(areas._flow().async_step_dashboard_pages({"page_1": {"enabled": True}}))
    assert result["type"] == "menu"
    assert entry.options[CONF_DASHBOARD_NAVIGATION] == "tabs"
    result = run(areas._flow().async_step_dashboard({
        CONF_DEVICE_UI_ENABLED: True, CONF_DASHBOARD_NAVIGATION: "pager",
    }))
    assert entry.options[CONF_DASHBOARD_NAVIGATION] == "pager"


@pytest.mark.parametrize("navigation", [None, "pager", "tabs"])
def test_the_display_is_told_and_the_bar_replaces_the_page_list(monkeypatch, navigation) -> None:
    options = {} if navigation is None else {CONF_DASHBOARD_NAVIGATION: navigation}
    entry = FakeEntry(data={
        CONF_DEVICE_UI_ENABLED: True,
        CONF_ENERGY_PAGE: {"enabled": True, "views": ["now"]},
        CONF_DASHBOARD_ENTITIES: ["sensor.temperature"],
        CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: {"sensor.temperature": {"page": "C300X"}},
    }, options=options)
    hass = FakeHass(states=FakeStates({"sensor.temperature": FakeState("21")}))
    monkeypatch.setattr(dashboard, "async_dashboard_weather_payload", AsyncMock(return_value=None))
    monkeypatch.setattr(dashboard, "async_energy_dashboard_page", AsyncMock(
        return_value={"title": "Energy", "energy": {"views": [{"id": "now"}]}},
    ))
    result = run(dashboard.async_dashboard_payload(hass, entry))
    main = next(page for page in result["data"]["pages"] if page["title"] == "C300X")
    kinds = [item["kind"] for item in main["items"]]
    if navigation == "tabs":
        assert result["navigation"] == "tabs"
        assert kinds == ["entity"]
    else:
        assert "navigation" not in result
        assert kinds == ["navigation", "entity"]
