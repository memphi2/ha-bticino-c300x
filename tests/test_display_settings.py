"""Native display layout forms preserve older selections and infer controls."""

import asyncio
from types import SimpleNamespace

import pytest

from custom_components.bticino_c300x.config_flow_dashboard import (
    dashboard_display_entity_ids,
    dashboard_entity_display_overrides_from_fields,
    dashboard_entity_display_schema,
    dashboard_input_defaults,
)
from custom_components.bticino_c300x.dashboard import (
    async_dashboard_payload,
    async_status,
)
from custom_components.bticino_c300x.dashboard_entities import (
    normalize_dashboard_entity_display_overrides,
)


def test_layout_fields_roundtrip_and_clear_without_losing_names():
    old = {
        "light.room": {
            "name": "custom",
            "custom_name": "Desk",
            "secondary": "none",
            "page": "Study",
            "order": "5",
        }
    }
    schema = dashboard_entity_display_schema(["light.room"], old)
    posted = schema({})
    assert posted["1. Room - Page"] == "Study"
    assert posted["1. Room - Position"] == 5
    result = dashboard_entity_display_overrides_from_fields(posted, ["light.room"], old)
    assert normalize_dashboard_entity_display_overrides(result, strict=True) == old
    posted["1. Room - Page"] = ""
    posted["1. Room - Position"] = 10
    result = dashboard_entity_display_overrides_from_fields(posted, ["light.room"], old)
    assert result == {
        "light.room": {"name": "custom", "custom_name": "Desk", "secondary": "none"}
    }


@pytest.mark.parametrize(
    "options",
    [
        {"page": "x" * 61},
        {"page": "a\nb"},
        {"order": "NaN"},
        {"order": True},
        {"order": -1},
        {"order": 10001},
        {"order": 1.5},
    ],
)
def test_invalid_layout_rejected_without_corrupting_saved_data(options):
    with pytest.raises(ValueError):
        normalize_dashboard_entity_display_overrides(
            {"light.room": options}, strict=True
        )
    assert normalize_dashboard_entity_display_overrides({"light.room": options}) == {}


def test_quick_action_settings_do_not_add_an_overview_entity():
    data = {
        "device_ui_enabled": True,
        "dashboard_entities": [],
        "alarm_page_entity_id": "button.porch",
    }
    ids = dashboard_display_entity_ids(data)
    assert ids == ["button.porch"]
    schema = dashboard_entity_display_schema(ids, layout_entity_ids=[])
    values = schema({"1. Porch - Name": "custom", "1. Porch - Custom name": "Porch"})
    assert "1. Porch - Page" not in values
    configured = dashboard_input_defaults({**data, **values})
    assert configured["dashboard_entities"] == []
    assert configured["dashboard_entity_display_overrides"] == {
        "button.porch": {"name": "custom", "custom_name": "Porch"}
    }
    assert dashboard_display_entity_ids({**data, "dashboard_entities": ids}) == ids


def test_pages_and_positions_are_applied_without_changing_capabilities():
    states = {
        "light.one": SimpleNamespace(
            state="on", attributes={"supported_color_modes": ["onoff"]}
        ),
        "light.two": SimpleNamespace(
            state="off", attributes={"supported_color_modes": ["onoff"]}
        ),
        "cover.shade": SimpleNamespace(
            state="closed", attributes={"supported_features": 15}
        ),
        "button.porch": SimpleNamespace(state="unknown", attributes={}),
    }
    hass = SimpleNamespace(
        states=SimpleNamespace(get=states.get), config=SimpleNamespace(language="en")
    )
    entry = SimpleNamespace(
        entry_id="entry",
        title="Door",
        data={},
        options={
            "device_ui_enabled": True,
            "dashboard_entities": ["light.one", "light.two", "cover.shade"],
            "alarm_page_entity_id": "button.porch",
            "dashboard_entity_display_overrides": {
                "light.one": {"page": "Room", "order": "20"},
                "light.two": {"page": "Room", "order": "10"},
                "cover.shade": {"page": "Outside"},
                "button.porch": {"name": "custom", "custom_name": "Outside light"},
            },
        },
    )
    payload = asyncio.run(async_dashboard_payload(hass, entry))
    pages = {page["title"]: page for page in payload["data"]["pages"]}
    assert list(pages) == ["C300X", "Room", "Outside"]
    assert [item["entity_id"] for item in pages["Room"]["items"]] == [
        "light.two",
        "light.one",
    ]
    assert pages["Outside"]["items"][0]["controls"][0]["command"] == "open_cover"
    status = asyncio.run(async_status(hass, entry))
    assert status["alarm_page_entity"]["name"] == "Outside light"
    assert all(
        item["entity_id"] != "button.porch"
        for page in pages.values()
        for item in page.get("items", [])
    )


@pytest.mark.parametrize(
    ("secondary", "expected"),
    [("none", ""), ("entity_id", "light.porch"), ("state", "On")],
)
def test_quick_entity_honors_secondary_line_without_overview_selection(secondary, expected):
    state = SimpleNamespace(state="on", attributes={"friendly_name": "Porch"})
    hass = SimpleNamespace(
        states=SimpleNamespace(get=lambda entity_id: state if entity_id == "light.porch" else None),
        config=SimpleNamespace(language="en"),
    )
    entry = SimpleNamespace(
        entry_id="entry", title="Door", data={},
        options={
            "device_ui_enabled": True,
            "dashboard_entities": [],
            "alarm_page_entity_id": "light.porch",
            "dashboard_entity_display_overrides": {
                "light.porch": {"secondary": secondary},
            },
        },
    )
    status = asyncio.run(async_status(hass, entry))
    assert status["alarm_page_entity"]["state_label"] == expected


def test_tile_size_fields_roundtrip_and_automatic_stores_nothing():
    schema = dashboard_entity_display_schema(["cover.shade"], {})
    posted = schema({})
    # A form that was never touched must not start writing sizes.
    assert posted["1. Shade - Width"] == "auto"
    assert posted["1. Shade - Height"] == "auto"
    assert dashboard_entity_display_overrides_from_fields(posted, ["cover.shade"], {}) == {}

    posted["1. Shade - Width"] = "full"
    posted["1. Shade - Height"] = "full"
    saved = dashboard_entity_display_overrides_from_fields(posted, ["cover.shade"], {})
    assert saved == {"cover.shade": {"width": "full", "height": "full"}}
    assert normalize_dashboard_entity_display_overrides(saved, strict=True) == saved

    reopened = dashboard_entity_display_schema(["cover.shade"], saved)({})
    assert reopened["1. Shade - Width"] == "full"
    reopened["1. Shade - Width"] = "auto"
    reopened["1. Shade - Height"] = "half"
    assert dashboard_entity_display_overrides_from_fields(
        reopened, ["cover.shade"], saved
    ) == {"cover.shade": {"height": "half"}}


def test_a_form_without_size_fields_keeps_the_saved_sizes():
    """An older or partial post must not silently reset a configured tile."""

    saved = {"cover.shade": {"width": "full", "height": "full"}}
    assert dashboard_entity_display_overrides_from_fields({}, ["cover.shade"], saved) == saved


@pytest.mark.parametrize("options", [{"width": "wide"}, {"height": "2"}, {"height": 94}])
def test_invalid_tile_size_rejected_without_corrupting_saved_data(options):
    with pytest.raises(ValueError):
        normalize_dashboard_entity_display_overrides({"light.room": options}, strict=True)
    assert normalize_dashboard_entity_display_overrides({"light.room": options}) == {}


def test_tile_sizes_reach_the_display_only_when_configured():
    states = {
        "cover.shade": SimpleNamespace(state="closed", attributes={"supported_features": 15}),
        "light.one": SimpleNamespace(state="on", attributes={"supported_color_modes": ["onoff"]}),
        "sensor.temp": SimpleNamespace(state="21.5", attributes={}),
    }
    hass = SimpleNamespace(
        states=SimpleNamespace(get=states.get), config=SimpleNamespace(language="en")
    )
    entry = SimpleNamespace(
        entry_id="entry",
        title="Door",
        data={},
        options={
            "device_ui_enabled": True,
            "dashboard_entities": ["cover.shade", "light.one", "sensor.temp"],
            "dashboard_entity_display_overrides": {
                "cover.shade": {"width": "full", "height": "full"},
                "sensor.temp": {"height": "half"},
            },
        },
    )
    payload = asyncio.run(async_dashboard_payload(hass, entry))
    items = {
        item["entity_id"]: item
        for page in payload["data"]["pages"]
        for item in page.get("items", [])
    }
    assert (items["cover.shade"]["tile_width"], items["cover.shade"]["tile_height"]) == ("full", "full")
    assert items["sensor.temp"]["tile_height"] == "half"
    assert "tile_width" not in items["sensor.temp"]
    # Automatic sends nothing, so an unconfigured dashboard payload is unchanged.
    assert "tile_width" not in items["light.one"]
    assert "tile_height" not in items["light.one"]


def _weather_entry(overrides):
    return SimpleNamespace(
        entry_id="entry",
        title="Door",
        data={},
        options={
            "device_ui_enabled": True,
            "weather_entity_id": "weather.home",
            "dashboard_entities": ["light.one", "light.two"],
            "dashboard_entity_display_overrides": overrides,
        },
    )


def _weather_hass():
    states = {
        "weather.home": SimpleNamespace(
            state="sunny", attributes={"temperature": 12, "temperature_unit": "C"}
        ),
        "light.one": SimpleNamespace(state="on", attributes={"supported_color_modes": ["onoff"]}),
        "light.two": SimpleNamespace(state="off", attributes={"supported_color_modes": ["onoff"]}),
    }
    return SimpleNamespace(
        states=SimpleNamespace(get=states.get),
        config=SimpleNamespace(language="en"),
        services=SimpleNamespace(has_service=lambda *_: False),
    )


def _kinds(page):
    return [item.get("entity_id", item["kind"]) for item in page.get("items", [])]


def test_weather_card_stays_on_the_status_page_until_placed():
    """Unplaced, the card is alone on the first page, as before the setting."""

    payload = asyncio.run(async_dashboard_payload(_weather_hass(), _weather_entry({})))
    pages = {page["title"]: page for page in payload["data"]["pages"]}
    assert list(pages) == ["C300X", ""]
    assert "weather" in pages["C300X"]
    assert _kinds(pages["C300X"]) == ["weather"]
    assert _kinds(pages[""]) == ["light.one", "light.two"]


def test_weather_card_takes_a_position_among_the_tiles_and_a_page():
    # Tiles join the status page by its name; the card then sorts with them.
    shared = {
        "light.one": {"page": "C300X"},
        "light.two": {"page": "C300X"},
        "weather.home": {"order": "15"},
    }
    payload = asyncio.run(async_dashboard_payload(_weather_hass(), _weather_entry(shared)))
    pages = payload["data"]["pages"]
    assert [page["title"] for page in pages] == ["C300X"]
    assert _kinds(pages[0]) == ["light.one", "weather", "light.two"]

    moved = {"weather.home": {"page": "Outside", "order": "5"}, "light.two": {"page": "Outside"}}
    payload = asyncio.run(async_dashboard_payload(_weather_hass(), _weather_entry(moved)))
    pages = {page["title"]: page for page in payload["data"]["pages"]}
    assert "weather" not in pages["C300X"]
    assert "items" not in pages["C300X"]
    assert "weather" in pages["Outside"]
    assert _kinds(pages["Outside"]) == ["weather", "light.two"]
    assert _kinds(pages[""]) == ["light.one"]


def test_placing_the_weather_card_keeps_the_order_of_the_pages():
    """Named pages follow their first entity; the card cannot pull one ahead."""

    pages_of = {"light.one": {"page": "Living"}, "light.two": {"page": "Garden"}}
    unplaced = asyncio.run(async_dashboard_payload(_weather_hass(), _weather_entry(pages_of)))
    assert [page["title"] for page in unplaced["data"]["pages"]] == ["C300X", "Living", "Garden"]

    on_garden = {**pages_of, "weather.home": {"page": "Garden", "order": "5"}}
    payload = asyncio.run(async_dashboard_payload(_weather_hass(), _weather_entry(on_garden)))
    assert [page["title"] for page in payload["data"]["pages"]] == ["C300X", "Living", "Garden"]
    assert _kinds(payload["data"]["pages"][2]) == ["weather", "light.two"]

    unnamed = {"light.one": {"page": "Living"}, "weather.home": {"page": "Living"}}
    payload = asyncio.run(async_dashboard_payload(_weather_hass(), _weather_entry(unnamed)))
    assert [page["title"] for page in payload["data"]["pages"]] == ["C300X", "Living", ""]

    # A page only the card uses comes after the pages of the entities.
    own_page = {**pages_of, "weather.home": {"page": "Outside"}}
    payload = asyncio.run(async_dashboard_payload(_weather_hass(), _weather_entry(own_page)))
    assert [page["title"] for page in payload["data"]["pages"]] == ["C300X", "Living", "Garden", "Outside"]


def test_weather_layout_fields_roundtrip_and_store_only_a_real_placement():
    schema = dashboard_entity_display_schema(["light.one"], {}, weather_entity_id="weather.home")
    posted = schema({})
    assert posted["Weather - Page"] == ""
    assert posted["Weather - Position"] == 0
    assert dashboard_entity_display_overrides_from_fields(
        posted, ["light.one"], {}, weather_entity_id="weather.home"
    ) == {}

    posted["Weather - Page"] = "Outside"
    posted["Weather - Position"] = 25
    saved = dashboard_entity_display_overrides_from_fields(
        posted, ["light.one"], {}, weather_entity_id="weather.home"
    )
    assert saved == {"weather.home": {"page": "Outside", "order": "25"}}
    assert normalize_dashboard_entity_display_overrides(saved, strict=True) == saved
    reopened = dashboard_entity_display_schema(["light.one"], saved, weather_entity_id="weather.home")({})
    assert (reopened["Weather - Page"], reopened["Weather - Position"]) == ("Outside", 25)

    # No weather entity: no fields, and a layout saved for an old one is dropped.
    assert "Weather - Page" not in dashboard_entity_display_schema(["light.one"], saved)({})
    assert dashboard_entity_display_overrides_from_fields({}, ["light.one"], saved) == {}


def test_weather_layout_key_carries_a_place_and_nothing_else():
    cleaned = normalize_dashboard_entity_display_overrides(
        {"weather.home": {"page": "Outside", "order": 5, "width": "full", "name": "custom", "custom_name": "x"}},
        strict=True,
    )
    assert cleaned == {"weather.home": {"page": "Outside", "order": "5"}}
    with pytest.raises(ValueError):
        normalize_dashboard_entity_display_overrides({"weather.home": {"order": -1}}, strict=True)
    # Only a weather entity may be a non-dashboard key.
    with pytest.raises(ValueError):
        normalize_dashboard_entity_display_overrides({"camera.door": {"page": "x"}}, strict=True)


def test_media_player_is_a_display_tile_but_not_an_alarm_quick_action():
    from custom_components.bticino_c300x.config_flow_dashboard import (
        alarm_page_entity_id,
        dashboard_entity_ids,
    )
    from custom_components.bticino_c300x.schema_compat import vol

    assert dashboard_entity_ids(["media_player.kitchen"]) == ["media_player.kitchen"]
    with pytest.raises(vol.Invalid):
        alarm_page_entity_id("media_player.kitchen")
    assert alarm_page_entity_id("light.porch") == "light.porch"


@pytest.mark.parametrize(
    ("player_state", "attributes", "is_on", "reading"),
    [
        ("playing", {"media_title": "  Evening news  "}, True, "Evening news"),
        ("paused", {"media_title": "x" * 80}, True, "x" * 60),
        ("idle", {"media_title": "Stale title"}, True, "Ready"),
        ("off", {}, False, "Off"),
        ("standby", {}, False, "Standby"),
    ],
)
def test_media_player_item_reports_power_and_what_is_playing(player_state, attributes, is_on, reading):
    states = {
        "media_player.kitchen": SimpleNamespace(
            state=player_state,
            attributes={"supported_features": 1 | 4 | 256 | 16384, "volume_level": 0.5, **attributes},
        )
    }
    hass = SimpleNamespace(
        states=SimpleNamespace(get=states.get), config=SimpleNamespace(language="en")
    )
    entry = SimpleNamespace(
        entry_id="entry", title="Door", data={},
        options={"device_ui_enabled": True, "dashboard_entities": ["media_player.kitchen"]},
    )
    payload = asyncio.run(async_dashboard_payload(hass, entry))
    item = next(
        item for page in payload["data"]["pages"] for item in page.get("items", [])
    )
    assert item["kind"] == "entity"
    assert item["state"] is is_on
    assert item["available"] is True
    assert item["details"]["type"] == "media_player"
    assert item["details"]["value"] == reading
    assert "media_play_pause" in [control["command"] for control in item["controls"]]


def test_unavailable_media_player_is_offline_without_controls():
    states = {"media_player.kitchen": SimpleNamespace(state="unavailable", attributes={})}
    hass = SimpleNamespace(
        states=SimpleNamespace(get=states.get), config=SimpleNamespace(language="en")
    )
    entry = SimpleNamespace(
        entry_id="entry", title="Door", data={},
        options={"device_ui_enabled": True, "dashboard_entities": ["media_player.kitchen"]},
    )
    payload = asyncio.run(async_dashboard_payload(hass, entry))
    item = next(item for page in payload["data"]["pages"] for item in page.get("items", []))
    assert item["available"] is False
    assert item["state"] is False
    assert item["controls"] == []
