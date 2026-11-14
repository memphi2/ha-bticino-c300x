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
    dashboard_entity_display_input,
    dashboard_entity_display_overrides_from_fields,
    dashboard_entity_display_schema,
    dashboard_input_defaults,
)
from custom_components.bticino_c300x.config_flow_dashboard_pages import (
    dashboard_page_layout,
    dashboard_pages_input,
    dashboard_pages_placeholders,
)
from custom_components.bticino_c300x.config_flow_tiles import (
    TILE_LABELS,
    async_tile_labels,
    tile_form,
)
from custom_components.bticino_c300x.dashboard import (
    async_dashboard_payload,
    async_status,
)
from custom_components.bticino_c300x.dashboard_entities import (
    normalize_dashboard_entity_display_overrides,
    normalize_dashboard_pages,
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


def post_pages_like_home_assistant(schema, changes=None):
    """Post the pages form the way Home Assistant's frontend does.

    Each section is posted as its own dict with the suggested values filled in
    and every empty field left out. ``changes`` maps a section to its changes.
    """

    data = {}
    for key, page_section in schema.schema.items():
        values = {}
        for field in page_section.schema.schema:
            suggested = (field.description or {}).get("suggested_value")
            if suggested is not None:
                values[str(field)] = suggested
        values.update((changes or {}).get(str(key), {}))
        data[str(key)] = {
            name: value for name, value in values.items() if value not in (None, "", [])
        }
    return schema(data)


def post_tiles_like_home_assistant(schema, changes=None):
    """Post the tiles form the way Home Assistant's frontend does.

    Each tile is a section that is posted with what it shows. ``changes``
    maps a field label to a new value and applies to every tile.
    """

    data = {}
    for key, tile_section in schema.schema.items():
        values = {str(field): field.default() for field in tile_section.schema.schema}
        values.update(changes or {})
        data[str(key)] = {
            name: value for name, value in values.items() if value not in (None, "")
        }
    return schema(data)


def test_entity_display_dialog_keeps_the_page_and_position_of_each_entity():
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
    assert not [str(key) for key in schema.schema if str(key).endswith(("Page", "Position"))]
    posted = post_like_home_assistant(schema)
    result = dashboard_input_defaults(dashboard_entity_display_input(settings, posted))
    overrides = result["dashboard_entity_display_overrides"]
    assert normalize_dashboard_entity_display_overrides(overrides, strict=True) == old
    posted = post_like_home_assistant(schema, {"1. Room - Name": "friendly_name"})
    result = dashboard_input_defaults(dashboard_entity_display_input(settings, posted))
    assert result["dashboard_entity_display_overrides"] == {
        "light.room": {"secondary": "none", "page": "Study", "order": "5"}
    }


def test_emptied_text_fields_are_stored_empty():
    # Home Assistant's frontend leaves an emptied field out of the post, so the
    # saved value must not come back as a default.
    saved = {"light.room": {"name": "custom", "custom_name": "Desk", "page": "Study"}}
    settings = {
        "device_ui_enabled": True,
        "dashboard_entities": ["light.room"],
        "dashboard_entity_display_overrides": saved,
    }
    schema = dashboard_entity_display_form(settings, saved)
    emptied = {"1. Room - Custom name": ""}
    posted = post_like_home_assistant(schema, emptied)
    assert not set(emptied) & set(posted)

    result = dashboard_input_defaults(dashboard_entity_display_input(settings, posted))

    # Without its text a custom name leaves the Home Assistant name.
    assert result["dashboard_entity_display_overrides"] == {"light.room": {"page": "Study"}}
    # Untouched, the same form keeps everything.
    kept = dashboard_input_defaults(
        dashboard_entity_display_input(settings, post_like_home_assistant(schema))
    )
    assert kept["dashboard_entity_display_overrides"] == saved


class _OptionsAreas:
    """Open the areas of the options menu one after the other, as a user does.

    Each area saves on its own and the next one starts from what was saved.
    So the steps that the setup and reconfigure flows chain are separate
    flows here: after an area saved, the next area is opened if the menu of
    a new flow offers it.
    """

    def __init__(self, entry):
        self._entry = entry

    def _flow(self):
        flow = BticinoC300XOptionsFlow(self._entry)
        flow.async_create_entry = lambda **kwargs: {"type": "finished", "data": kwargs["data"]}
        flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}
        flow.add_suggested_values_to_schema = lambda schema, _values: schema
        return flow

    async def _area(self, step_id, user_input, next_step_id=None):
        result = await getattr(self._flow(), f"async_step_{step_id}")(user_input)
        if result["type"] != "finished" or next_step_id is None:
            return result
        self._entry.options = dict(result["data"])
        menu = (await self._flow().async_step_init())["menu_options"]
        if next_step_id not in menu:
            return result
        return await getattr(self._flow(), f"async_step_{next_step_id}")(None)

    async def dashboard(self, user_input=None):
        return await self._area("dashboard", user_input, "dashboard_pages")

    async def pages(self, user_input=None):
        return await self._area("dashboard_pages", user_input, "dashboard_entity_display")

    async def entity_display(self, user_input=None):
        return await self._area("dashboard_entity_display", user_input)


def _display_flow(monkeypatch, flow_kind, entry):
    """Return a flow's dashboard, pages and entity-display steps.

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
        areas = _OptionsAreas(entry)
        return areas.dashboard, areas.pages, areas.entity_display
    if flow_kind == "reconfigure":
        flow = BticinoC300XConfigFlow()
        flow._get_reconfigure_entry = lambda: entry
        flow._reconfigure_feature_data = {"video_enabled": False}
        flow._async_finish_reconfigure = finish
        steps = (
            flow.async_step_reconfigure_dashboard,
            flow.async_step_reconfigure_dashboard_pages,
            flow.async_step_reconfigure_dashboard_entity_display,
        )
    else:
        flow = BticinoC300XConfigFlow()
        flow._setup_feature_data = {"video_enabled": False}
        flow._async_create_setup_entry = finish
        steps = (
            flow.async_step_user_dashboard,
            flow.async_step_user_dashboard_pages,
            flow.async_step_user_dashboard_entity_display,
        )
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}
    flow.add_suggested_values_to_schema = lambda schema, _values: schema
    return steps


@pytest.mark.parametrize("flow_kind", ["options", "reconfigure"])
def test_flows_store_emptied_text_fields_empty(monkeypatch, flow_kind):
    saved = {"light.room": {"name": "custom", "custom_name": "Desk", "page": "Study"}}
    dashboard = {"device_ui_enabled": True, "dashboard_entities": ["light.room"]}
    entry = SimpleNamespace(
        data={**dashboard, "dashboard_entity_display_overrides": saved},
        options={},
        runtime_data=None,
    )
    dashboard_step, pages_step, display_step = _display_flow(monkeypatch, flow_kind, entry)

    form = asyncio.run(dashboard_step({"device_ui_enabled": True}))
    assert form["step_id"].endswith("dashboard_pages")
    # The section of a named page carries its name in its title.
    assert form["description_placeholders"]["page_2_name"] == ": Study"
    assert form["description_placeholders"]["page_3_name"] == ""
    form = asyncio.run(pages_step(post_pages_like_home_assistant(form["data_schema"])))
    assert list(form["data_schema"].schema) == ["Study \u203a Room"]
    # The name shows the typed text; emptied, it is left out of the post.
    assert post_tiles_like_home_assistant(form["data_schema"])["Study \u203a Room"]["Name"] == "Desk"
    posted = post_tiles_like_home_assistant(form["data_schema"], {"Name": "friendly_name"})
    result = asyncio.run(display_step(posted))

    assert result["type"] == "finished", result.get("errors")
    assert result["data"]["dashboard_entity_display_overrides"] == {"light.room": {"page": "Study"}}
    assert result["data"]["dashboard_pages"] == [
        {"name": "C300X", "order": 1},
        {"name": "Study", "order": 2},
    ]


@pytest.mark.parametrize("flow_kind", ["setup", "options", "reconfigure"])
def test_the_pages_form_places_and_orders_the_pages(monkeypatch, flow_kind):
    dashboard = {"device_ui_enabled": True, "weather_entity_id": "weather.home"}
    entry = SimpleNamespace(data=dict(dashboard), options={}, runtime_data=None)
    dashboard_step, pages_step, display_step = _display_flow(monkeypatch, flow_kind, entry)

    form = asyncio.run(dashboard_step(dict(dashboard)))
    assert form["step_id"].endswith("dashboard_pages")
    posted = post_pages_like_home_assistant(form["data_schema"], {
        "page_1": {"position": 2, "entities": ["sensor.temp"]},
        "page_2": {"name": "  Living\troom ", "position": 3, "entities": ["light.two", "light.one"]},
        "page_4": {"name": "Garden", "position": 1, "entities": ["cover.shade"]},
    })
    form = asyncio.run(pages_step(posted))
    # One section per tile, in the order the display shows them.
    assert list(form["data_schema"].schema) == [
        "Garden \u203a Shade",
        "Status page \u203a Temp",
        "Living room \u203a Two",
        "Living room \u203a One",
    ]
    result = asyncio.run(display_step(post_tiles_like_home_assistant(form["data_schema"])))

    assert result["type"] == "finished", result.get("errors")
    assert result["data"]["dashboard_pages"] == [
        {"name": "Garden", "order": 1},
        {"name": "C300X", "order": 2},
        {"name": "Living room", "order": 3},
    ]
    assert result["data"]["dashboard_entities"] == [
        "cover.shade", "sensor.temp", "light.two", "light.one",
    ]
    assert result["data"]["dashboard_entity_display_overrides"] == {
        "cover.shade": {"page": "Garden"},
        "sensor.temp": {"page": "C300X"},
        "light.two": {"page": "Living room"},
        "light.one": {"page": "Living room"},
    }


@pytest.mark.parametrize("flow_kind", ["setup", "options", "reconfigure"])
@pytest.mark.parametrize(
    ("changes", "errors"),
    [
        ({"page_2": {"name": "c300x"}}, {"page_2": "dashboard_page_name_reserved"}),
        (
            {"page_2": {"name": "Room"}, "page_3": {"name": "Room"}},
            {"page_3": "dashboard_page_name_duplicate"},
        ),
        (
            {"page_1": {"entities": ["light.one"]}, "page_2": {"name": "Room", "entities": ["light.one"]}},
            {"page_2": "dashboard_entity_on_several_pages"},
        ),
        ({"page_2": {"entities": ["camera.door"]}}, {"page_2": "invalid_dashboard_entities"}),
        # A page with tiles is shown with its name as the heading.
        ({"page_2": {"entities": ["light.one"]}}, {"page_2": "dashboard_page_name_missing"}),
        (
            {"page_2": {"name": "Room"}, "page_3": {"name": " room "}},
            {"page_3": "dashboard_page_name_duplicate"},
        ),
    ],
)
def test_the_pages_form_rejects_what_the_display_cannot_show(
    monkeypatch, flow_kind, changes, errors
):
    saved = {"device_ui_enabled": True, "dashboard_entities": ["light.two"]}
    entry = SimpleNamespace(data=dict(saved), options={}, runtime_data=None)
    dashboard_step, pages_step, _display_step = _display_flow(monkeypatch, flow_kind, entry)

    form = asyncio.run(dashboard_step({"device_ui_enabled": True}))
    data = {key: dict(value) for key, value in post_pages_like_home_assistant(form["data_schema"]).items()}
    for key, value in changes.items():
        data[key] = {**data.get(key, {}), **value}
    result = asyncio.run(pages_step(data))

    assert result["type"] == "form"
    assert result["step_id"].endswith("dashboard_pages")
    assert result["errors"] == errors


@pytest.mark.parametrize("flow_kind", ["setup", "options", "reconfigure"])
def test_an_emptied_page_position_returns_to_the_place_of_its_section(monkeypatch, flow_kind):
    """Home Assistant leaves an emptied number box out of the form it sends."""

    dashboard = {"device_ui_enabled": True}
    entry = SimpleNamespace(data=dict(dashboard), options={}, runtime_data=None)
    dashboard_step, pages_step, _display_step = _display_flow(monkeypatch, flow_kind, entry)

    form = asyncio.run(dashboard_step(dict(dashboard)))
    posted = post_pages_like_home_assistant(form["data_schema"], {
        "page_1": {"position": None},
        "page_3": {"name": "Room", "position": None},
    })
    assert "position" not in posted["page_1"]
    result = asyncio.run(pages_step(posted))

    assert result["type"] == "finished", result.get("errors")
    assert result["data"]["dashboard_pages"] == [
        {"name": "C300X", "order": 1},
        {"name": "Room", "order": 2},
    ]


@pytest.mark.parametrize("flow_kind", ["options", "reconfigure"])
def test_emptying_the_entities_of_every_page_stores_none(monkeypatch, flow_kind):
    saved = {
        "device_ui_enabled": True,
        "dashboard_entities": ["light.one", "light.two"],
        "dashboard_entity_display_overrides": {
            "light.one": {"page": "C300X"},
            "light.two": {"page": "Room", "width": "full"},
        },
    }
    entry = SimpleNamespace(data=dict(saved), options={}, runtime_data=None)
    dashboard_step, pages_step, _display_step = _display_flow(monkeypatch, flow_kind, entry)

    form = asyncio.run(dashboard_step({"device_ui_enabled": True}))
    prefilled = post_pages_like_home_assistant(form["data_schema"])
    assert prefilled["page_1"]["entities"] == ["light.one"]
    assert (prefilled["page_2"]["name"], prefilled["page_2"]["entities"]) == ("Room", ["light.two"])
    result = asyncio.run(pages_step(post_pages_like_home_assistant(form["data_schema"], {
        "page_1": {"entities": []},
        "page_2": {"name": "", "entities": []},
    })))

    assert result["type"] == "finished", result.get("errors")
    assert result["data"]["dashboard_entities"] == []
    assert result["data"]["dashboard_entity_display_overrides"] == {}
    assert result["data"]["dashboard_pages"] == [{"name": "C300X", "order": 1}]


@pytest.mark.parametrize("flow_kind", ["options", "reconfigure"])
def test_emptying_the_actions_stores_them_empty(monkeypatch, flow_kind):
    """An emptied action list must not bring the saved value back.

    Home Assistant's form leaves an emptied text field out of what it sends.
    """

    entry = SimpleNamespace(
        data={
            "device_ui_enabled": True,
            "actions": {"standby": {"domain": "button", "service": "press"}},
        },
        options={},
        runtime_data=None,
    )
    dashboard_step, pages_step, display_step = _display_flow(monkeypatch, flow_kind, entry)

    form = asyncio.run(dashboard_step(None))
    assert post_like_home_assistant(form["data_schema"])["actions_json"]
    result = asyncio.run(dashboard_step(post_like_home_assistant(
        form["data_schema"], {"actions_json": ""},
    )))
    assert result["step_id"].endswith("dashboard_pages")
    result = asyncio.run(pages_step(post_pages_like_home_assistant(result["data_schema"])))

    assert result["type"] == "finished", result.get("errors")
    assert result["data"]["actions"] == {}
    assert result["data"]["device_ui_enabled"] is True


@pytest.mark.parametrize("flow_kind", ["options", "reconfigure"])
def test_the_weather_is_set_with_the_status_page(monkeypatch, flow_kind):
    """The weather comes with page 1, prefilled from what is saved.

    Home Assistant's form leaves an emptied picker out of what it sends, which
    stores the setting empty in place of bringing the saved value back.
    """

    entry = SimpleNamespace(
        data={"device_ui_enabled": True, "weather_entity_id": "weather.home"},
        options={},
        runtime_data=None,
    )
    dashboard_step, pages_step, display_step = _display_flow(monkeypatch, flow_kind, entry)

    form = asyncio.run(dashboard_step({"device_ui_enabled": True}))
    assert form["step_id"].endswith("dashboard_pages")
    # The display and patch form has none of it, and the weather is the first
    # field of the status page, above its entities.
    assert [str(key) for key in form["data_schema"].schema["page_1"].schema.schema] == [
        "weather_entity_id", "position", "entities",
    ]
    assert "page_9" not in {str(key) for key in form["data_schema"].schema}
    assert post_pages_like_home_assistant(form["data_schema"])["page_1"]["weather_entity_id"] == "weather.home"

    # Kept, as shown.
    result = asyncio.run(pages_step(post_pages_like_home_assistant(form["data_schema"])))
    assert result["type"] == "finished", result.get("errors")
    assert result["data"]["weather_entity_id"] == "weather.home"

    # Emptied.
    result = asyncio.run(pages_step(post_pages_like_home_assistant(
        form["data_schema"], {"page_1": {"weather_entity_id": None}},
    )))
    assert result["type"] == "finished", result.get("errors")
    assert result["data"]["weather_entity_id"] == ""


@pytest.mark.parametrize("saved,changes,stored", [
    ({}, {"alarm_entity_id": "alarm_control_panel.home"}, {"alarm_entity_id": "alarm_control_panel.home"}),
    (
        {"alarm_entity_id": "alarm_control_panel.home", "alarm_page_entity_id": "switch.porch"},
        {},
        {"alarm_entity_id": "alarm_control_panel.home", "alarm_page_entity_id": "switch.porch"},
    ),
    # An emptied picker is left out of the post and stores the setting empty.
    (
        {"alarm_entity_id": "alarm_control_panel.home", "alarm_page_entity_id": "switch.porch"},
        {"alarm_entity_id": None},
        {"alarm_entity_id": "", "alarm_page_entity_id": "switch.porch"},
    ),
    (
        {"alarm_entity_id": "alarm_control_panel.home", "alarm_page_entity_id": "switch.porch"},
        {"alarm_page_entity_id": None},
        {"alarm_entity_id": "alarm_control_panel.home", "alarm_page_entity_id": ""},
    ),
])
def test_the_alarm_area_sets_alarmo_and_its_quick_action(monkeypatch, saved, changes, stored):
    """Alarmo has an area of its own in the options menu, prefilled and saved alone."""

    entry = SimpleNamespace(
        data={
            "device_ui_enabled": True,
            "dashboard_entities": ["light.room"],
            "dashboard_entity_display_overrides": {
                "light.room": {"page": "Room"},
                "switch.porch": {"name": "custom", "custom_name": "Porch"},
                "switch.old": {"secondary": "none"},
            },
            **saved,
        },
        options={},
        runtime_data=None,
    )
    flow = _OptionsAreas(entry)._flow()
    form = asyncio.run(flow.async_step_dashboard_alarm())
    assert form["step_id"] == "dashboard_alarm"
    assert [str(key) for key in form["data_schema"].schema] == ["alarm_entity_id", "alarm_page_entity_id"]

    result = asyncio.run(flow.async_step_dashboard_alarm(
        post_like_home_assistant(form["data_schema"], changes)
    ))

    assert result["type"] == "finished", result.get("errors")
    for key, value in stored.items():
        assert result["data"][key] == value
    # What the area does not show stays; the display settings of an entity
    # that is no longer shown go.
    assert result["data"]["dashboard_entities"] == ["light.room"]
    overrides = result["data"]["dashboard_entity_display_overrides"]
    assert overrides["light.room"] == {"page": "Room"}
    assert "switch.old" not in overrides
    assert ("switch.porch" in overrides) == (stored.get("alarm_page_entity_id") == "switch.porch")


@pytest.mark.parametrize("changes,errors", [
    ({"alarm_entity_id": "light.hall"}, {"alarm_entity_id": "invalid_alarm_entity"}),
    ({"alarm_page_entity_id": "camera.door"}, {"alarm_page_entity_id": "invalid_alarm_page_entity"}),
])
def test_the_alarm_area_rejects_a_wrong_entity(monkeypatch, changes, errors):
    entry = SimpleNamespace(data={"device_ui_enabled": True}, options={}, runtime_data=None)
    flow = _OptionsAreas(entry)._flow()
    form = asyncio.run(flow.async_step_dashboard_alarm())

    # The form is checked by Home Assistant before the step; call the step
    # with what it would pass on.
    result = asyncio.run(flow.async_step_dashboard_alarm(changes))

    assert result["type"] == "form"
    assert result["step_id"] == "dashboard_alarm"
    assert result["errors"] == errors
    assert form["step_id"] == "dashboard_alarm"


@pytest.mark.parametrize("flow_kind", ["setup", "options", "reconfigure"])
@pytest.mark.parametrize("changes,errors", [
    ({"page_1": {"weather_entity_id": "sensor.temp"}}, {"page_1": "invalid_weather_entity"}),
])
def test_the_pages_form_rejects_a_wrong_weather_entity(
    monkeypatch, flow_kind, changes, errors
):
    entry = SimpleNamespace(data={"device_ui_enabled": True}, options={}, runtime_data=None)
    dashboard_step, pages_step, _display_step = _display_flow(monkeypatch, flow_kind, entry)

    form = asyncio.run(dashboard_step({"device_ui_enabled": True}))
    data = {key: dict(value) for key, value in post_pages_like_home_assistant(form["data_schema"]).items()}
    for key, value in changes.items():
        data[key] = {**data.get(key, {}), **value}
    result = asyncio.run(pages_step(data))

    assert result["type"] == "form"
    assert result["step_id"].endswith("dashboard_pages")
    assert result["errors"] == errors


@pytest.mark.parametrize("flow_kind", ["setup", "options", "reconfigure"])
def test_a_weather_entity_needs_no_entity_display_dialog(monkeypatch, flow_kind):
    dashboard = {"device_ui_enabled": True, "weather_entity_id": "weather.home"}
    entry = SimpleNamespace(data=dict(dashboard), options={}, runtime_data=None)
    dashboard_step, pages_step, _display_step = _display_flow(monkeypatch, flow_kind, entry)

    form = asyncio.run(dashboard_step(dict(dashboard)))
    result = asyncio.run(pages_step(post_pages_like_home_assistant(form["data_schema"])))

    assert result["type"] == "finished", result.get("errors")
    assert result["data"]["weather_entity_id"] == "weather.home"
    assert result["data"]["dashboard_entity_display_overrides"] == {}

    # Without the device UI there are no pages to set up.
    dashboard_step, _pages_step, _display_step = _display_flow(monkeypatch, flow_kind, entry)
    assert asyncio.run(dashboard_step({**dashboard, "device_ui_enabled": False}))["type"] == "finished"


@pytest.mark.parametrize("flow_kind", ["setup", "options", "reconfigure"])
@pytest.mark.parametrize(
    ("changes", "stored"),
    [
        # A name without a text leaves the Home Assistant name.
        ({"Name": ""}, {}),
        ({"Name": "   "}, {}),
        ({"Name": "custom"}, {}),
        # A typed text is a name of its own.
        ({"Name": " Desk "}, {"name": "custom", "custom_name": "Desk"}),
        ({"Name": "entity_id"}, {"name": "entity_id"}),
        ({"Width": "full", "Height": "half"}, {"width": "full", "height": "half"}),
        ({"Secondary line": "none"}, {"secondary": "none"}),
    ],
)
def test_the_entity_display_dialog_stores_only_what_the_display_accepts(
    monkeypatch, flow_kind, changes, stored
):
    dashboard = {"device_ui_enabled": True}
    entry = SimpleNamespace(data=dict(dashboard), options={}, runtime_data=None)
    dashboard_step, pages_step, display_step = _display_flow(monkeypatch, flow_kind, entry)

    form = asyncio.run(dashboard_step(dict(dashboard)))
    form = asyncio.run(pages_step(post_pages_like_home_assistant(
        form["data_schema"], {"page_2": {"name": "x" * 70, "entities": ["light.room"]}}
    )))
    result = asyncio.run(display_step(post_tiles_like_home_assistant(form["data_schema"], changes)))

    # A rejected value would send the user back to the dashboard form without
    # a message and drop every change made in the dialog.
    assert result["type"] == "finished", result.get("errors")
    assert result["data"]["dashboard_entity_display_overrides"] == {
        "light.room": {**stored, "page": "x" * 60}
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
    # The status page has nothing to show here and is left out.
    assert list(pages) == ["Room", "Outside"]
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


def test_weather_card_heads_the_status_page_wherever_it_is_placed():
    shared = {"light.one": {"page": "C300X"}, "light.two": {"page": "C300X", "order": "0"}}
    payload = asyncio.run(async_dashboard_payload(_weather_hass(), _weather_entry(shared)))
    pages = payload["data"]["pages"]
    assert [page["title"] for page in pages] == ["C300X"]
    assert _kinds(pages[0]) == ["weather", "light.two", "light.one"]

    # A placement saved by an older release is dropped.
    moved = {"weather.home": {"page": "Outside", "order": "5"}, "light.two": {"page": "Outside"}}
    entry = _weather_entry(moved)
    entry.options["dashboard_pages"] = [{"name": "Outside", "order": 0}, {"name": "C300X", "order": 10}]
    payload = asyncio.run(async_dashboard_payload(_weather_hass(), entry))
    pages = {page["title"]: page for page in payload["data"]["pages"]}
    assert list(pages) == ["Outside", "C300X", ""]
    assert "weather" in pages["C300X"]
    assert "weather" not in pages["Outside"]
    assert _kinds(pages["Outside"]) == ["light.two"]


def test_pages_follow_their_configured_positions():
    pages_of = {"light.one": {"page": "Living"}, "light.two": {"page": "Garden"}}
    unordered = asyncio.run(async_dashboard_payload(_weather_hass(), _weather_entry(pages_of)))
    # Without configured pages they keep the order their names first appear in.
    assert [page["title"] for page in unordered["data"]["pages"]] == ["C300X", "Living", "Garden"]

    entry = _weather_entry(pages_of)
    entry.options["dashboard_pages"] = [
        {"name": "C300X", "order": 20},
        {"name": "Living", "order": 30},
        {"name": "Garden", "order": 10},
    ]
    payload = asyncio.run(async_dashboard_payload(_weather_hass(), entry))
    assert [page["title"] for page in payload["data"]["pages"]] == ["Garden", "C300X", "Living"]


def test_pages_only_actions_use_follow_the_configured_pages():
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

    def titles(pages):
        entry = _weather_entry({"light.one": {"page": "Garden"}, "light.two": {"page": "C300X"}})
        entry.options["actions"] = actions
        entry.options["dashboard_pages"] = pages
        payload = asyncio.run(async_dashboard_payload(hass, entry))
        return [page["title"] for page in payload["data"]["pages"]]

    assert titles([]) == ["C300X", "Garden", "Lights"]
    assert titles([{"name": "Garden", "order": 0}, {"name": "C300X", "order": 5}]) == [
        "Garden", "C300X", "Lights",
    ]


def test_weather_entity_keys_are_dropped_from_the_display_settings():
    cleaned = normalize_dashboard_entity_display_overrides(
        {"weather.home": {"page": "Outside", "order": 5}, "light.room": {"page": "Room"}},
        strict=True,
    )
    assert cleaned == {"light.room": {"page": "Room"}}
    # Only a dashboard entity may have display settings.
    with pytest.raises(ValueError):
        normalize_dashboard_entity_display_overrides({"camera.door": {"page": "x"}}, strict=True)


@pytest.mark.parametrize(
    ("pages", "expected"),
    [
        (None, ()),
        ([], ()),
        (
            [{"name": "Room", "order": 20}, {"name": "C300X", "order": 20}, {"name": " Hall ", "order": 5}],
            ({"name": "Hall", "order": 5}, {"name": "Room", "order": 20}, {"name": "C300X", "order": 20}),
        ),
        ([{"name": "Room", "order": 7.6}], ({"name": "Room", "order": 8},)),
    ],
)
def test_configured_pages_are_ordered_by_position(pages, expected):
    assert normalize_dashboard_pages(pages, strict=True) == expected


@pytest.mark.parametrize(
    "pages",
    [
        "Room",
        [["Room", 1]],
        [{"name": "Room", "order": 1}, {"name": "Room", "order": 2}],
        [{"name": "a\x07b", "order": 1}],
        [{"name": "Room", "order": "NaN"}],
        [{"name": "Room", "order": True}],
        [{"name": f"Page {index}", "order": index} for index in range(9)],
    ],
)
def test_invalid_pages_rejected_without_corrupting_saved_data(pages):
    with pytest.raises(ValueError):
        normalize_dashboard_pages(pages, strict=True)
    assert len(normalize_dashboard_pages(pages)) <= 8


def test_legacy_entries_open_the_pages_form_with_their_pages():
    """An entry saved before pages keeps its display when the form opens."""

    settings = {
        "dashboard_entities": ["light.a", "light.b", "light.c", "light.d"],
        "dashboard_entity_display_overrides": {
            "light.b": {"page": "Room", "order": "30"},
            "light.c": {"page": "Room", "order": "5"},
            "light.d": {"page": "C300X"},
        },
    }
    assert dashboard_page_layout(settings) == [
        {"name": "C300X", "order": 1, "entities": ["light.d"]},
        {"name": "", "order": 2, "entities": ["light.a"]},
        {"name": "Room", "order": 3, "entities": ["light.c", "light.b"]},
    ]

    many = {
        "dashboard_entities": [f"light.l{index}" for index in range(10)],
        "dashboard_entity_display_overrides": {
            f"light.l{index}": {"page": f"P{index}"} for index in range(10)
        },
    }
    layout = dashboard_page_layout(many)
    assert len(layout) == 8
    assert layout[-1]["entities"] == ["light.l6", "light.l7", "light.l8", "light.l9"]


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
        ("playing", {"media_title": "Morning Show\nLive from Studio 2"}, True, "Morning Show Live from Studio 2", True),
        ("playing", {"media_title": "A\r\n\t B  C\n"}, True, "A B C", True),
        ("playing", {"media_title": " \n "}, True, "Active", True),
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


def test_the_pages_form_reaches_the_frontend_as_sections():
    from homeassistant.helpers import config_validation as cv

    from custom_components.bticino_c300x.config_flow_dashboard_pages import (
        dashboard_pages_schema,
    )
    from custom_components.bticino_c300x.schema_compat import HA_USES_PROBATIO

    if HA_USES_PROBATIO:
        import probatio

        convert = probatio.to_field_list
    else:
        import voluptuous_serialize

        convert = voluptuous_serialize.convert
    schema = dashboard_pages_schema({
        "dashboard_entities": ["light.a"],
        "dashboard_entity_display_overrides": {"light.a": {"page": "Room"}},
    })

    fields = convert(schema, custom_serializer=cv.custom_serializer)

    assert [(field["name"], field["type"]) for field in fields] == [
        *((f"page_{slot}", "expandable") for slot in range(1, 9)),
    ]
    # Used pages are open, and so is the first free one to add a page.
    assert [field["expanded"] for field in fields] == [True, True, True] + [False] * 5
    assert [item["name"] for item in fields[0]["schema"]] == [
        "weather_entity_id", "position", "entities",
    ]
    assert [item["name"] for item in fields[1]["schema"]] == ["name", "position", "entities"]
    assert fields[1]["schema"][0]["description"] == {"suggested_value": "Room"}



@pytest.mark.parametrize(
    ("status_position", "page_position", "first"),
    [
        # Out of range: 8 and 1.
        (20, 0, "Room"),
        # Rounded: 3 and 2.
        (2.6, 2.4, "Room"),
        # Invalid or empty: the numbers of the sections, 1 and 2.
        (float("nan"), None, "C300X"),
        # The same position keeps the order of the sections.
        (2, 2, "C300X"),
    ],
)
def test_page_positions_are_whole_numbers_from_one_to_eight(status_position, page_position, first):
    result, errors = dashboard_pages_input({}, {
        "page_1": {"position": status_position},
        "page_2": {"name": "Room", "position": page_position, "entities": ["light.one"]},
    })

    assert errors == {}
    assert result["dashboard_pages"][0]["name"] == first
    # Stored positions count the pages in display order.
    assert [page["order"] for page in result["dashboard_pages"]] == [1, 2]


def test_section_titles_carry_the_page_names():
    settings = {
        "dashboard_entities": ["light.a"],
        "dashboard_entity_display_overrides": {"light.a": {"page": "Room"}},
    }

    assert dashboard_pages_placeholders(settings) == {
        "page_2_name": ": Room",
        **{f"page_{slot}_name": "" for slot in range(3, 9)},
    }
    # Shown again after an error, the titles follow the names that were sent.
    sent = {"page_2": {"name": " Hall "}, "page_3": {"entities": ["light.a"]}}
    assert dashboard_pages_placeholders(settings, sent)["page_2_name"] == ": Hall"
    assert dashboard_pages_placeholders(settings, sent)["page_3_name"] == ""


def test_saving_the_pages_keeps_the_name_of_the_alarmo_quick_entity():
    """The Alarmo quick entity is on no page, and its tile name is still kept.

    Saving the pages dropped the display settings of every entity that is on
    no page, which also removed the name given to the quick entity.
    """

    settings = {
        "alarm_page_entity_id": "button.stair_light",
        "dashboard_entities": ["light.one", "light.gone"],
        "dashboard_entity_display_overrides": {
            "button.stair_light": {"name": "custom", "custom_name": "Stairs"},
            "light.gone": {"name": "entity_id"},
        },
    }

    result, errors = dashboard_pages_input(settings, {
        "page_1": {"entities": ["light.one"]},
    })

    assert errors == {}
    assert result["dashboard_entity_display_overrides"] == {
        "button.stair_light": {"name": "custom", "custom_name": "Stairs"},
        "light.one": {"page": "C300X"},
    }


def test_the_tiles_form_has_a_section_per_tile_named_after_page_and_entity():
    settings = {
        "alarm_page_entity_id": "button.stair_light",
        "dashboard_entities": ["light.desk", "light.lamp", "sensor.temp"],
        "dashboard_pages": [{"name": "Study", "order": 1}, {"name": "C300X", "order": 2}],
    }
    saved = {
        "light.desk": {"page": "Study", "name": "custom", "custom_name": "Desk", "width": "full"},
        "light.lamp": {"page": "Study", "name": "entity_id", "secondary": "none"},
        "sensor.temp": {"page": "C300X"},
        "button.stair_light": {"name": "custom", "custom_name": "Stairs"},
    }
    settings["dashboard_entity_display_overrides"] = saved
    # Two entities of a page share a name; Home Assistant names the others.
    names = {"light.desk": "Lamp", "light.lamp": "Lamp", "sensor.temp": "Temperatur außen"}
    hass = SimpleNamespace(states=SimpleNamespace(
        get=lambda entity_id: (
            SimpleNamespace(name=names[entity_id]) if entity_id in names else None
        )
    ))
    labels = {"width": "Breite", "name": "Name", "status_page": "Statusseite"}

    form = tile_form(settings, saved, labels=labels, hass=hass)

    assert list(form.sections.items()) == [
        ("Study › Lamp", "light.desk"),
        ("Study › Lamp (light.lamp)", "light.lamp"),
        ("Statusseite › Temperatur außen", "sensor.temp"),
        # On no page, and named after its entity id without a state.
        ("Alarm page › Stair Light", "button.stair_light"),
    ]
    shown = post_tiles_like_home_assistant(form.schema)
    assert shown == {
        "Study › Lamp": {
            "Breite": "full", "Height": "auto", "Name": "Desk", "Secondary line": "state",
        },
        "Study › Lamp (light.lamp)": {
            "Breite": "auto", "Height": "auto", "Name": "entity_id", "Secondary line": "none",
        },
        "Statusseite › Temperatur außen": {
            "Breite": "auto", "Height": "auto", "Name": "friendly_name", "Secondary line": "state",
        },
        # The quick entity is no tile of a page and has no size.
        "Alarm page › Stair Light": {"Name": "Stairs", "Secondary line": "state"},
    }
    # Many tiles start as a list of closed sections.
    assert all(tile.options == {"collapsed": True} for tile in form.schema.schema.values())

    def stored(post):
        fields = form.entity_fields(post)
        return dashboard_input_defaults(
            dashboard_entity_display_input(settings, fields)
        )["dashboard_entity_display_overrides"]

    # Posted as shown, nothing changes.
    assert stored(shown) == saved
    # A tile whose section or field was not sent keeps what it showed.
    assert stored({}) == saved
    assert stored({"Study › Lamp": {"Height": "half"}})["light.desk"] == {
        **saved["light.desk"], "height": "half",
    }
    # A change reaches the entity of its section, also behind the shared name.
    changed = stored({**shown, "Study › Lamp (light.lamp)": {
        "Breite": "half", "Height": "full", "Name": "Reading", "Secondary line": "last_changed",
    }})
    assert changed["light.lamp"] == {
        "page": "Study", "width": "half", "height": "full",
        "name": "custom", "custom_name": "Reading", "secondary": "last_changed",
    }
    assert changed["light.desk"] == saved["light.desk"]


def test_a_few_tiles_are_shown_open():
    settings = {"dashboard_entities": ["light.one", "light.two"]}

    form = tile_form(settings)

    # Entities from before pages could be set up are on the status page.
    assert list(form.sections) == ["Status page \u203a One", "Status page \u203a Two"]
    assert [tile.options for tile in form.schema.schema.values()] == [{"collapsed": False}] * 2


def test_tile_labels_come_in_the_language_of_home_assistant(monkeypatch):
    prefix = "component.bticino_c300x.selector.tile_field.options."

    async def translations(_hass, language, category, integrations):
        assert (language, category, set(integrations)) == ("de", "selector", {"bticino_c300x"})
        return wanted

    monkeypatch.setattr("homeassistant.helpers.translation.async_get_translations", translations)
    hass = SimpleNamespace(config=SimpleNamespace(language="de"))

    wanted = {prefix + "width": "Breite", prefix + "secondary": "Zusatzzeile"}
    labels = asyncio.run(async_tile_labels(hass))
    assert labels["width"] == "Breite"
    assert labels["secondary"] == "Zusatzzeile"
    # A label without a translation stays English.
    assert labels["height"] == "Height"

    # Two fields under one label would be one field: the English labels are used.
    wanted = {prefix + "width": "Size", prefix + "height": "Size"}
    assert asyncio.run(async_tile_labels(hass)) == TILE_LABELS
    # Without Home Assistant, as in a unit test, the labels are English.
    assert asyncio.run(async_tile_labels(None)) == TILE_LABELS
