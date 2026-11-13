"""Native display layout forms preserve older selections and infer controls."""

import asyncio
from types import SimpleNamespace

import pytest

from custom_components.bticino_c300x.config_flow import (
    BticinoC300XConfigFlow,
    BticinoC300XOptionsFlow,
)
from custom_components.bticino_c300x.config_flow_dashboard import (
    dashboard_display_entity_ids,
    dashboard_entity_display_form,
    dashboard_entity_display_form_complete,
    dashboard_entity_display_input,
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
from custom_components.bticino_c300x.schema_compat import vol


def post_like_home_assistant(schema, changes=None):
    """Post a form the way Home Assistant's frontend and flow manager do.

    The frontend prefills suggested values and defaults, leaves out every empty
    field, and the flow manager validates the rest against the schema.
    """

    data = {}
    for key in schema.schema:
        suggested = (key.description or {}).get("suggested_value")
        if suggested is not None:
            data[str(key)] = suggested
        elif key.default is not vol.UNDEFINED:
            data[str(key)] = key.default()
    data.update(changes or {})
    return schema({name: value for name, value in data.items() if value not in (None, "")})


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
    settings = {
        "device_ui_enabled": True,
        "dashboard_entities": ["light.room"],
        "dashboard_entity_display_overrides": old,
    }
    schema = dashboard_entity_display_form(settings, old)
    posted = post_like_home_assistant(schema)
    assert posted["1. Room - Page"] == "Study"
    assert posted["1. Room - Position"] == 5
    result = dashboard_input_defaults(dashboard_entity_display_input(settings, posted))
    overrides = result["dashboard_entity_display_overrides"]
    assert normalize_dashboard_entity_display_overrides(overrides, strict=True) == old
    posted = post_like_home_assistant(schema, {"1. Room - Page": "", "1. Room - Position": 10})
    result = dashboard_input_defaults(dashboard_entity_display_input(settings, posted))
    assert result["dashboard_entity_display_overrides"] == {
        "light.room": {"name": "custom", "custom_name": "Desk", "secondary": "none"}
    }


def test_emptied_text_fields_are_stored_empty():
    # Home Assistant's frontend leaves an emptied field out of the post, so the
    # saved value must not come back as a default.
    saved = {
        "light.room": {"name": "custom", "custom_name": "Desk", "page": "Study"},
        "weather.home": {"page": "Outside"},
    }
    settings = {
        "device_ui_enabled": True,
        "weather_entity_id": "weather.home",
        "dashboard_entities": ["light.room"],
        "dashboard_entity_display_overrides": saved,
    }
    schema = dashboard_entity_display_form(settings, saved)
    emptied = {"Weather - Page": "", "1. Room - Page": "", "1. Room - Custom name": ""}
    posted = post_like_home_assistant(schema, emptied)
    assert not set(emptied) & set(posted)
    assert dashboard_entity_display_form_complete(posted, ["light.room"])

    result = dashboard_input_defaults(dashboard_entity_display_input(settings, posted))

    # Without its text a custom name leaves the Home Assistant name.
    assert result["dashboard_entity_display_overrides"] == {}
    # Untouched, the same form keeps everything.
    kept = dashboard_input_defaults(
        dashboard_entity_display_input(settings, post_like_home_assistant(schema))
    )
    assert kept["dashboard_entity_display_overrides"] == saved


def _display_flow(monkeypatch, flow_kind, entry):
    """Return a flow's dashboard step and entity-display step.

    Only the final hand-over is replaced, so the flow still validates what it
    stores and turns invalid settings back to a form.
    """

    async def placeholders(_entry):
        return {}

    async def finish(feature_data):
        return {"type": "finished", "data": feature_data}

    monkeypatch.setattr(
        "custom_components.bticino_c300x.config_flow._async_qml_patch_description_placeholders",
        placeholders,
    )
    if flow_kind == "options":
        flow = BticinoC300XOptionsFlow(entry)
        flow._feature_options = {"video_enabled": False}
        flow._connection_options = {}
        flow.async_create_entry = lambda **kwargs: {"type": "finished", "data": kwargs["data"]}
        steps = (flow.async_step_dashboard, flow.async_step_dashboard_entity_display)
    elif flow_kind == "reconfigure":
        flow = BticinoC300XConfigFlow()
        flow._get_reconfigure_entry = lambda: entry
        flow._reconfigure_feature_data = {"video_enabled": False}
        flow._async_finish_reconfigure = finish
        steps = (
            flow.async_step_reconfigure_dashboard,
            flow.async_step_reconfigure_dashboard_entity_display,
        )
    else:
        flow = BticinoC300XConfigFlow()
        flow._setup_feature_data = {"video_enabled": False}
        flow._async_create_setup_entry = finish
        steps = (flow.async_step_user_dashboard, flow.async_step_user_dashboard_entity_display)
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}
    return steps


@pytest.mark.parametrize("flow_kind", ["options", "reconfigure"])
def test_flows_store_emptied_text_fields_empty(monkeypatch, flow_kind):
    saved = {
        "light.room": {"name": "custom", "custom_name": "Desk", "page": "Study"},
        "weather.home": {"page": "Outside"},
    }
    dashboard = {
        "device_ui_enabled": True,
        "weather_entity_id": "weather.home",
        "dashboard_entities": ["light.room"],
    }
    entry = SimpleNamespace(
        data={**dashboard, "dashboard_entity_display_overrides": saved},
        options={},
        runtime_data=None,
    )
    dashboard_step, display_step = _display_flow(monkeypatch, flow_kind, entry)

    form = asyncio.run(dashboard_step(dict(dashboard)))
    posted = post_like_home_assistant(
        form["data_schema"],
        {"Weather - Page": "", "1. Room - Page": "", "1. Room - Custom name": ""},
    )
    result = asyncio.run(display_step(posted))

    assert result["type"] == "finished", result.get("errors")
    assert result["data"]["dashboard_entity_display_overrides"] == {}


@pytest.mark.parametrize("flow_kind", ["setup", "options", "reconfigure"])
def test_an_emptied_position_returns_to_the_automatic_one(monkeypatch, flow_kind):
    """Home Assistant leaves an emptied number box out of the form it sends.

    A position with a default came back as the saved one; empty means the
    entity's place in the selection and the top of the page for the card.
    """

    saved = {"light.room": {"order": "5"}, "weather.home": {"page": "Outside", "order": "15"}}
    dashboard = {
        "device_ui_enabled": True,
        "weather_entity_id": "weather.home",
        "dashboard_entities": ["light.room"],
    }
    entry = SimpleNamespace(
        data={**dashboard, "dashboard_entity_display_overrides": saved},
        options={},
        runtime_data=None,
    )
    dashboard_step, display_step = _display_flow(monkeypatch, flow_kind, entry)

    form = asyncio.run(dashboard_step(dict(dashboard)))
    if flow_kind != "setup":
        prefilled = post_like_home_assistant(form["data_schema"])
        assert prefilled["Weather - Position"] == 15
        assert prefilled["1. Room - Position"] == 5
    posted = post_like_home_assistant(
        form["data_schema"],
        {"Weather - Page": "Outside", "Weather - Position": None, "1. Room - Position": None},
    )
    assert "Weather - Position" not in posted
    assert "1. Room - Position" not in posted
    result = asyncio.run(display_step(posted))

    assert result["type"] == "finished", result.get("errors")
    assert result["data"]["dashboard_entity_display_overrides"] == {
        "weather.home": {"page": "Outside"},
    }


@pytest.mark.parametrize("flow_kind", ["options", "reconfigure"])
@pytest.mark.parametrize("field,saved,stored,empty", [
    ("alarm_entity_id", {"alarm_entity_id": "alarm_control_panel.home"}, "alarm_entity_id", ""),
    ("alarm_page_entity_id", {"alarm_page_entity_id": "switch.porch"}, "alarm_page_entity_id", ""),
    ("weather_entity_id", {"weather_entity_id": "weather.home"}, "weather_entity_id", ""),
    (
        "actions_json",
        {"actions": {"standby": {"domain": "button", "service": "press"}}},
        "actions",
        {},
    ),
    ("dashboard_entities", {"dashboard_entities": ["light.room"]}, "dashboard_entities", []),
])
def test_emptying_a_dashboard_field_stores_it_empty(
    monkeypatch, flow_kind, field, saved, stored, empty
):
    """An emptied picker or action list must not bring the saved value back.

    Home Assistant's form leaves an emptied picker or text field out of what it
    sends; an emptied entity list arrives as an empty list.
    """

    entry = SimpleNamespace(
        data={"device_ui_enabled": True, **saved}, options={}, runtime_data=None
    )
    dashboard_step, display_step = _display_flow(monkeypatch, flow_kind, entry)

    form = asyncio.run(dashboard_step(None))
    assert post_like_home_assistant(form["data_schema"])[field]
    result = asyncio.run(dashboard_step(post_like_home_assistant(
        form["data_schema"], {field: [] if isinstance(empty, list) else ""},
    )))
    if result["type"] == "form":
        assert result["step_id"].endswith("dashboard_entity_display")
        result = asyncio.run(display_step(post_like_home_assistant(result["data_schema"])))

    assert result["type"] == "finished", result.get("errors")
    assert result["data"][stored] == empty
    assert result["data"]["device_ui_enabled"] is True


@pytest.mark.parametrize("flow_kind", ["setup", "options", "reconfigure"])
def test_a_weather_entity_alone_opens_the_entity_display_dialog(monkeypatch, flow_kind):
    dashboard = {"device_ui_enabled": True, "weather_entity_id": "weather.home", "dashboard_entities": []}
    entry = SimpleNamespace(data=dict(dashboard), options={}, runtime_data=None)
    dashboard_step, display_step = _display_flow(monkeypatch, flow_kind, entry)

    form = asyncio.run(dashboard_step(dict(dashboard)))
    assert form.get("step_id", "").endswith("dashboard_entity_display")
    assert [str(key) for key in form["data_schema"].schema] == ["Weather - Page", "Weather - Position"]
    posted = post_like_home_assistant(
        form["data_schema"], {"Weather - Page": "Outside", "Weather - Position": 5}
    )
    result = asyncio.run(display_step(posted))

    assert result["type"] == "finished", result.get("errors")
    assert result["data"]["dashboard_entity_display_overrides"] == {
        "weather.home": {"page": "Outside", "order": "5"}
    }

    # Without a weather entity and without tiles there is nothing to place.
    dashboard_step, _display_step = _display_flow(monkeypatch, flow_kind, entry)
    assert asyncio.run(dashboard_step({**dashboard, "weather_entity_id": ""}))["type"] == "finished"


@pytest.mark.parametrize("flow_kind", ["setup", "options", "reconfigure"])
@pytest.mark.parametrize(
    ("changes", "stored"),
    [
        # A custom name without its text leaves the Home Assistant name.
        ({"1. Room - Name": "custom", "1. Room - Custom name": ""}, {}),
        ({"1. Room - Name": "custom", "1. Room - Custom name": "   "}, {}),
        # The text fields and the position box do not enforce the stored
        # limits, so the dialog keeps what the display can use.
        ({"1. Room - Page": "Garden\tShed"}, {"light.room": {"page": "GardenShed"}}),
        ({"1. Room - Position": 7.4}, {"light.room": {"order": "7"}}),
        ({"Weather - Page": "x" * 70}, {"weather.home": {"page": "x" * 60}}),
        ({"Weather - Position": 5.5}, {"weather.home": {"order": "6"}}),
    ],
)
def test_the_entity_display_dialog_stores_only_what_the_display_accepts(
    monkeypatch, flow_kind, changes, stored
):
    dashboard = {
        "device_ui_enabled": True,
        "weather_entity_id": "weather.home",
        "dashboard_entities": ["light.room"],
    }
    entry = SimpleNamespace(data=dict(dashboard), options={}, runtime_data=None)
    dashboard_step, display_step = _display_flow(monkeypatch, flow_kind, entry)

    form = asyncio.run(dashboard_step(dict(dashboard)))
    result = asyncio.run(display_step(post_like_home_assistant(form["data_schema"], changes)))

    # A rejected value would send the user back to the dashboard form without
    # a message and drop every change made in the dialog.
    assert result["type"] == "finished", result.get("errors")
    assert result["data"]["dashboard_entity_display_overrides"] == stored


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


def test_placing_the_weather_card_keeps_the_order_of_action_pages():
    """Pages that only configured actions use keep their order as well."""

    states = {
        "weather.home": SimpleNamespace(
            state="sunny", attributes={"temperature": 12, "temperature_unit": "C"}
        ),
        "light.one": SimpleNamespace(state="on", attributes={"supported_color_modes": ["onoff"]}),
        "light.two": SimpleNamespace(state="off", attributes={"supported_color_modes": ["onoff"]}),
        "switch.pump": SimpleNamespace(state="off", attributes={}),
        "switch.gate": SimpleNamespace(state="off", attributes={}),
    }
    hass = SimpleNamespace(
        states=SimpleNamespace(get=states.get),
        config=SimpleNamespace(language="en"),
        services=SimpleNamespace(has_service=lambda *_: True),
    )
    actions = {
        "pump": {"domain": "switch", "service": "toggle",
                 "target": {"entity_id": "switch.pump"}, "dashboard": {"page": "Lights"}},
        "gate": {"domain": "switch", "service": "toggle",
                 "target": {"entity_id": "switch.gate"}, "dashboard": {"page": "Garden"}},
    }

    def titles(overrides):
        entry = _weather_entry(overrides)
        entry.options["actions"] = actions
        payload = asyncio.run(async_dashboard_payload(hass, entry))
        return [page["title"] for page in payload["data"]["pages"]]

    assert titles({}) == ["C300X", "", "Lights", "Garden"]
    assert titles({"weather.home": {"page": "Garden"}}) == ["C300X", "", "Lights", "Garden"]
    assert titles({"weather.home": {"page": "Outside"}}) == ["C300X", "", "Lights", "Garden", "Outside"]


def test_weather_layout_fields_roundtrip_and_store_only_a_real_placement():
    schema = dashboard_entity_display_schema(["light.one"], {}, weather_entity_id="weather.home")
    posted = post_like_home_assistant(schema)
    assert "Weather - Page" not in posted
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
    reopened = post_like_home_assistant(
        dashboard_entity_display_schema(["light.one"], saved, weather_entity_id="weather.home")
    )
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

    assert dashboard_entity_ids(["media_player.kitchen"]) == ["media_player.kitchen"]
    with pytest.raises(vol.Invalid):
        alarm_page_entity_id("media_player.kitchen")
    assert alarm_page_entity_id("light.porch") == "light.porch"


@pytest.mark.parametrize(
    ("player_state", "attributes", "is_on", "reading", "playing"),
    [
        ("playing", {"media_title": "  Evening news  "}, True, "Evening news", True),
        ("paused", {"media_title": "x" * 80}, True, "x" * 60, False),
        ("buffering", {"media_title": "Evening news"}, True, "Evening news", False),
        ("idle", {"media_title": "Stale title"}, True, "Ready", False),
        ("off", {}, False, "Off", False),
        ("standby", {}, False, "Standby", False),
    ],
)
def test_media_player_item_reports_power_and_what_is_playing(
    player_state, attributes, is_on, reading, playing
):
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
    # The tile shows its state line, so that line carries what is playing.
    assert item["state_label"] == reading
    assert "media_play_pause" in [control["command"] for control in item["controls"]]
    # Play/pause is confirmed on the playback state, which the item carries
    # whether or not the player offers the button in that state.
    assert item["details"]["playing"] is playing


@pytest.mark.parametrize(("secondary", "line"), [("none", ""), ("entity_id", "media_player.kitchen")])
def test_media_player_title_respects_another_secondary_line(secondary, line):
    states = {
        "media_player.kitchen": SimpleNamespace(
            state="playing", attributes={"supported_features": 16384, "media_title": "Evening news"}
        )
    }
    hass = SimpleNamespace(
        states=SimpleNamespace(get=states.get), config=SimpleNamespace(language="en")
    )
    entry = SimpleNamespace(
        entry_id="entry", title="Door", data={},
        options={
            "device_ui_enabled": True,
            "dashboard_entities": ["media_player.kitchen"],
            "dashboard_entity_display_overrides": {"media_player.kitchen": {"secondary": secondary}},
        },
    )
    payload = asyncio.run(async_dashboard_payload(hass, entry))
    item = next(item for page in payload["data"]["pages"] for item in page.get("items", []))
    assert item["state_label"] == line
    assert item["details"]["value"] == "Evening news"


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
