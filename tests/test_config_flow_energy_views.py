"""Independent Energy view switches keep the existing stored list contract."""

import json
from itertools import product
from pathlib import Path

import pytest
from homeassistant.helpers import selector
from test_display_settings import post_pages_like_home_assistant

from custom_components.bticino_c300x.config_flow_dashboard_pages import (
    dashboard_pages_input,
    dashboard_pages_schema,
)
from custom_components.bticino_c300x.dashboard_labels import ENERGY_LABELS_BY_LANGUAGE

VIEWS = ("now", "today", "power", "consumers", "balance")
FIELDS = tuple(f"view_{view}" for view in VIEWS)


def _section(schema):
    return next(value for key, value in schema.schema.items() if str(key) == "energy_page")


def _defaults(schema):
    return {
        str(key): key.default() for key in _section(schema).schema.schema
        if str(key) in (*FIELDS, "enabled")
    }


def test_energy_has_five_independent_boolean_selectors():
    schema = dashboard_pages_schema({})
    fields = _section(schema).schema.schema

    assert [str(key) for key in fields] == ["enabled", "position", *FIELDS]
    assert all(isinstance(value, selector.BooleanSelector)
               for key, value in fields.items() if str(key) in FIELDS)
    assert _defaults(schema) == {"enabled": False, **dict.fromkeys(FIELDS, True)}


@pytest.mark.parametrize("stored", [
    {}, {"views": None}, {"views": "today"}, {"views": {}},
])
def test_missing_or_invalid_saved_views_default_to_all_five(stored):
    settings = {"energy_page": {"enabled": True, **stored}}
    schema = dashboard_pages_schema(settings)
    assert _defaults(schema) == {"enabled": True, **dict.fromkeys(FIELDS, True)}

    saved, errors = dashboard_pages_input(settings, post_pages_like_home_assistant(schema))

    assert not errors
    assert saved["energy_page"]["views"] == list(VIEWS)


@pytest.mark.parametrize("views", [
    ["now", "today", "balance"], ["now"], ["today", "balance"], ["power"],
    ["consumers"], ["power", "consumers"], [],
])
def test_opening_and_saving_keeps_exact_saved_selections(views):
    settings = {"energy_page": {"enabled": True, "position": 2, "views": views}}
    schema = dashboard_pages_schema(settings)
    assert _defaults(schema) == {"enabled": True, **{f"view_{view}": view in views for view in VIEWS}}

    saved, errors = dashboard_pages_input(settings, post_pages_like_home_assistant(schema))

    assert not errors
    assert saved["energy_page"]["views"] == views
    assert saved["energy_page"]["enabled"] is True
    assert set(saved["energy_page"]) == {"enabled", "position", "views"}


@pytest.mark.parametrize("flags", list(product((False, True), repeat=len(VIEWS))))
def test_each_toggle_survives_post_save_and_reopen(flags):
    settings = {"energy_page": {"enabled": True, "views": list(VIEWS)}}
    toggles = dict(zip(FIELDS, flags, strict=True))
    posted = post_pages_like_home_assistant(dashboard_pages_schema(settings), {
        "energy_page": toggles,
    })
    assert all(posted["energy_page"][field] is flag for field, flag in toggles.items())

    saved, errors = dashboard_pages_input(settings, posted)

    assert not errors
    assert saved["energy_page"]["views"] == [
        view for view, on in zip(VIEWS, flags, strict=True) if on
    ]
    assert _defaults(dashboard_pages_schema(saved)) == {"enabled": True, **toggles}


@pytest.mark.parametrize("enabled", [False, True])
def test_validation_retry_retains_false_flags_and_global_switch(enabled):
    settings = {"energy_page": {"enabled": True, "views": list(VIEWS)}}
    toggles = {"enabled": enabled, "view_now": False, "view_today": True,
               "view_power": False, "view_consumers": False, "view_balance": False}
    posted = post_pages_like_home_assistant(dashboard_pages_schema(settings), {
        "page_2": {"entities": ["light.room"]},
        "energy_page": toggles,
    })
    unchanged, errors = dashboard_pages_input(settings, posted)
    assert errors == {"page_2": "dashboard_page_name_missing"}
    assert unchanged == settings
    retry = dashboard_pages_schema(settings, posted)
    assert _defaults(retry) == toggles
    assert _section(retry).options["collapsed"] is (not enabled)

    saved, errors = dashboard_pages_input(settings, post_pages_like_home_assistant(retry, {
        "page_2": {"name": "Room"},
    }))
    assert not errors
    assert saved["energy_page"]["enabled"] is enabled
    assert saved["energy_page"]["views"] == ["today"]


@pytest.mark.parametrize("posted", [{}, {"energy_page": {}}, {"energy_page": {"view_power": False}}])
def test_partial_posts_do_not_add_unselected_views(posted):
    settings = {"energy_page": {"enabled": True, "position": 2, "views": ["today"]}}
    saved, errors = dashboard_pages_input(settings, posted)

    assert not errors
    assert saved["energy_page"] == settings["energy_page"]
    assert _defaults(dashboard_pages_schema(settings, posted)) == {
        "enabled": True, "view_now": False, "view_today": True,
        "view_power": False, "view_consumers": False, "view_balance": False,
    }


@pytest.mark.parametrize("views", [[], ["now", "today", "balance"], ["power"], ["consumers"]])
def test_legacy_posted_list_is_accepted_without_a_storage_migration(views):
    saved, errors = dashboard_pages_input({}, {"energy_page": {"enabled": True, "views": views}})

    assert not errors
    assert saved["energy_page"]["views"] == views
    retry = dashboard_pages_schema({}, {"energy_page": {"enabled": True, "views": views}})
    assert _defaults(retry) == {"enabled": True, **{f"view_{view}": view in views for view in VIEWS}}


def test_explicit_toggle_overrides_legacy_list():
    saved, errors = dashboard_pages_input({}, {"energy_page": {
        "enabled": True, "views": ["now", "today"], "view_now": False, "view_power": True,
    }})
    assert not errors
    assert saved["energy_page"]["views"] == ["today", "power"]


@pytest.mark.parametrize("stored,expected", [
    (["distribution"], []), (["bogus"], []), (["now", "distribution"], ["now"]),
    (["distribution", "power", "balance"], ["power", "balance"]),
])
def test_retired_view_does_not_enable_consumers_or_other_reads(stored, expected):
    settings = {"energy_page": {"enabled": True, "position": 5, "views": stored}}
    schema = dashboard_pages_schema(settings)
    defaults = _defaults(schema)
    assert defaults["view_consumers"] is False
    assert "view_distribution" not in {str(key) for key in _section(schema).schema.schema}
    assert all(defaults[f"view_{view}"] is (view in expected) for view in VIEWS)
    posted = post_pages_like_home_assistant(schema)
    saved, errors = dashboard_pages_input(settings, posted)
    assert not errors
    assert saved["energy_page"]["enabled"] is True
    assert saved["energy_page"]["views"] == expected
    if not expected:
        assert saved["energy_page"]["position"] == 5


def test_retired_form_checkbox_never_selects_consumers():
    settings = {"energy_page": {"enabled": True, "views": ["distribution"]}}
    saved, errors = dashboard_pages_input(settings, {"energy_page": {"view_distribution": True}})
    assert not errors
    assert saved["energy_page"]["views"] == []
    saved, errors = dashboard_pages_input(saved, {"energy_page": {"view_consumers": True}})
    assert not errors
    assert saved["energy_page"]["views"] == ["consumers"]


def test_all_off_keeps_global_intent_and_position_without_a_visible_slot():
    settings = {
        "energy_page": {"enabled": True, "position": 4, "views": list(VIEWS)},
        "dashboard_pages": [{"name": "C300X", "order": 1}, {"name": "Room", "order": 2}],
    }
    posted = post_pages_like_home_assistant(dashboard_pages_schema(settings), {
        "energy_page": dict.fromkeys(FIELDS, False),
    })
    saved, errors = dashboard_pages_input(settings, posted)
    assert not errors
    assert saved["energy_page"] == {"enabled": True, "position": 4, "views": []}

    # Even an off page saved at position 2 must not add a gap to other pages.
    saved["energy_page"]["position"] = 2
    second = next(value for key, value in dashboard_pages_schema(saved).schema.items() if str(key) == "page_2")
    position = next(key for key in second.schema.schema if str(key) == "position")
    assert position.description["suggested_value"] == 2


@pytest.mark.parametrize("filename", ["strings.json", *[f"translations/{language}.json" for language in ("en", "de", "fr", "it")]])
def test_all_energy_sections_translate_every_toggle(filename):
    path = Path(__file__).resolve().parents[1] / "custom_components/bticino_c300x" / filename
    catalog = json.loads(path.read_text(encoding="utf-8"))
    sections = []

    def collect(node):
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if key == "energy_page" and isinstance(value, dict) and "data" in value:
                sections.append(value)
            else:
                collect(value)

    collect(catalog)
    assert len(sections) == 3
    for section in sections:
        assert set(section["data"]) == set(section["data_description"]) == {"enabled", "position", *FIELDS}
        assert all(section["data"][field] and section["data_description"][field] for field in FIELDS)
        language = path.stem if path.stem != "strings" else "en"
        assert section["data"]["view_consumers"] == ENERGY_LABELS_BY_LANGUAGE[language]["consumers"]
    assert "energy_views" not in catalog["selector"]


@pytest.mark.parametrize("language", ["en", "de", "fr", "it"])
def test_consumers_runtime_labels_replace_retired_view(language):
    labels = ENERGY_LABELS_BY_LANGUAGE[language]
    assert all(labels[key] for key in ("consumers", "consumers_empty", "consumers_incomplete"))
    assert not any(key.startswith("distribution") for key in labels)
    if language == "de":
        assert labels["consumers"] == "Verbraucher"
