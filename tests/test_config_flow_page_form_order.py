"""The pages form reads top to bottom like the display: 1, 2, 3 and so on.

Reported on a setup with the status page, the energy page at position 2 and
four custom pages: the form listed "Page 1", "Page 2", "Page 10", "Page 11",
then "Page 3" to "Page 6" and three sections titled just "Page". The pages
that are switched off carried their stored position as if they were shown
and stood between the shown ones, and a free section did not say what it is.
"""

import json
from pathlib import Path

import pytest
from test_display_settings import post_pages_like_home_assistant

from custom_components.bticino_c300x.config_flow_dashboard_pages import (
    dashboard_pages_input,
    dashboard_pages_placeholders,
    dashboard_pages_schema,
)
from custom_components.bticino_c300x.dashboard_energy import ENERGY_VIEWS

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "bticino_c300x"
ROOMS = ("Allgemein", "Rollladen", "Licht", "Media")


def _saved(**sections):
    posted = {
        "page_1": {"position": 1, "enabled": True, "entities": ["sensor.status"]},
        "energy_page": {"enabled": True, "position": 2, "view_now": True},
        **{
            f"page_{slot}": {"name": name, "position": slot + 1, "entities": [f"light.room_{slot}"]}
            for slot, name in enumerate(ROOMS, 2)
        },
        **sections,
    }
    saved, errors = dashboard_pages_input({}, posted)
    assert not errors
    return saved


def _titles(saved, posted=None, language="de"):
    catalog = json.loads((ROOT / "translations" / f"{language}.json").read_text(encoding="utf-8"))
    sections = catalog["options"]["step"]["dashboard_pages"]["sections"]
    placeholders = dashboard_pages_placeholders(saved, posted)
    return [
        sections[str(key)]["name"].format_map(placeholders)
        for key in dashboard_pages_schema(saved, posted).schema
    ]


def test_form_lists_the_shown_pages_in_order_then_the_pages_that_are_off():
    assert _titles(_saved()) == [
        "Seite 1: Statusseite",
        "Seite 2: Energie",
        "Seite 3: Allgemein",
        "Seite 4: Rollladen",
        "Seite 5: Licht",
        "Seite 6: Media",
        "Seite: Termine",
        "Seite: Haus verlassen",
        "Seite: Situationen",
        "Seite +", "Seite +", "Seite +",
    ]


def test_a_built_in_page_in_the_middle_takes_its_place_in_the_list():
    saved = _saved(agenda_page={"enabled": True, "position": 4, "calendars": ["calendar.home"]})
    assert _titles(saved) == [
        "Seite 1: Statusseite",
        "Seite 2: Energie",
        "Seite 3: Allgemein",
        "Seite 4: Termine",
        "Seite 5: Rollladen",
        "Seite 6: Licht",
        "Seite 7: Media",
        "Seite: Haus verlassen",
        "Seite: Situationen",
        "Seite +", "Seite +", "Seite +",
    ]


def test_energy_without_a_view_counts_as_off():
    saved = _saved(energy_page={
        "enabled": True, "position": 2, **{f"view_{view}": False for view in ENERGY_VIEWS},
    })
    assert saved["energy_page"]["enabled"] is True and saved["energy_page"]["views"] == []
    titles = _titles(saved)
    assert titles[:5] == [
        "Seite 1: Statusseite", "Seite 2: Allgemein", "Seite 3: Rollladen", "Seite 4: Licht", "Seite 5: Media",
    ]
    assert titles[5] == "Seite: Energie"


def test_an_empty_setup_lists_the_status_page_the_off_pages_and_seven_free_sections():
    schema = dashboard_pages_schema({})
    assert _titles({}) == [
        "Seite 1: Statusseite",
        "Seite: Energie",
        "Seite: Termine",
        "Seite: Haus verlassen",
        "Seite: Situationen",
        *["Seite +"] * 7,
    ]
    assert [str(key) for key in schema.schema][5:] == [f"page_{slot}" for slot in range(2, 9)]
    # Only the first free section is open.
    assert [value.options["collapsed"] for value in list(schema.schema.values())[5:]] == [False] + [True] * 6


def test_all_seven_custom_pages_leave_no_free_section():
    rooms = {f"page_{slot}": {"name": f"Raum {slot}", "position": slot + 1, "entities": [f"light.r{slot}"]}
             for slot in range(2, 9)}
    titles = _titles(_saved(**rooms))
    assert "Seite +" not in titles
    assert titles[-4:] == ["Seite 9: Raum 8", "Seite: Termine", "Seite: Haus verlassen", "Seite: Situationen"]


def test_pages_added_in_free_sections_take_their_numbers():
    saved = _saved()
    schema = dashboard_pages_schema(saved)
    assert [str(key) for key in schema.schema][-3:] == ["page_6", "page_7", "page_8"]
    posted = post_pages_like_home_assistant(schema, {
        "page_6": {"name": "Garten", "entities": ["light.garden"]},
        "page_8": {"name": "Keller", "entities": ["light.cellar"]},
    })
    added, errors = dashboard_pages_input(saved, posted)
    assert not errors
    titles = _titles(added)
    assert titles[6:8] == ["Seite 7: Garten", "Seite 8: Keller"]
    assert titles[-1] == "Seite +" and titles.count("Seite +") == 1


def test_saving_the_form_unchanged_changes_nothing():
    saved = _saved(leave_home_page={"enabled": False, "position": 3, "lights": ["light.room_2"]})
    again, errors = dashboard_pages_input(saved, post_pages_like_home_assistant(dashboard_pages_schema(saved)))
    assert not errors
    assert again == saved
    assert saved["leave_home_page"]["position"] == 3


def test_a_form_shown_again_after_an_error_keeps_its_sections_and_shows_what_was_sent():
    saved = _saved()
    schema = dashboard_pages_schema(saved)
    posted = post_pages_like_home_assistant(schema, {
        "page_6": {"entities": ["light.garden"]},
        "agenda_page": {"enabled": True, "position": 1},
    })
    unchanged, errors = dashboard_pages_input(saved, posted)
    assert errors == {"page_6": "dashboard_page_name_missing"} and unchanged == saved
    retry = dashboard_pages_schema(saved, posted)
    assert {str(key) for key in retry.schema} == {str(key) for key in schema.schema}
    titles = _titles(saved, posted)
    assert titles[0] == "Seite 1: Termine"
    assert "Seite: Haus verlassen" in titles and "Seite: Situationen" in titles
    assert post_pages_like_home_assistant(retry) == posted


@pytest.mark.parametrize("language,new_page", [("en", "Page +"), ("fr", "Page +"), ("it", "Pagina +")])
def test_other_languages_follow_the_same_order(language, new_page):
    titles = _titles(_saved(), language=language)
    assert titles[-3:] == [new_page] * 3
    numbers = [title.split(":")[0].split()[-1] for title in titles[:6]]
    assert numbers == ["1", "2", "3", "4", "5", "6"]
    assert not any(char.isdigit() for title in titles[6:] for char in title)
    assert len(titles) == 12
