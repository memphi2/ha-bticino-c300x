from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from custom_components.bticino_c300x.doorbell_state import DOORBELL_STATES
from custom_components.bticino_c300x.event_types import HA_EVENT_TYPES

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "bticino_c300x"
TRANSLATIONS = INTEGRATION / "translations"


def test_localized_translation_files_match_english_keys() -> None:
    english = _load_json(TRANSLATIONS / "en.json")

    for language in ("de", "it", "fr"):
        localized = _load_json(TRANSLATIONS / f"{language}.json")
        assert _leaf_paths(localized) == _leaf_paths(english)


ACTIVATIONS_HINT = {
    "strings": ("Further door locks and lights", "are added here"),
    "en": ("Further door locks and lights", "are added here"),
    "de": ("Weitere Türschlösser und Lichter", "legst du hier an"),
    "fr": ("Les serrures et lumières supplémentaires", "s'ajoutent ici"),
    "it": ("Serrature e luci aggiuntive", "si aggiungono qui"),
}


def test_the_activations_form_says_that_further_locks_and_lights_are_added_there() -> None:
    """Users looked elsewhere for a second door or a light; the form says it is the place."""

    for path in (INTEGRATION / "strings.json", *TRANSLATIONS.glob("*.json")):
        data = _load_json(path)
        hint = ACTIVATIONS_HINT[path.stem]
        for area, step in (
            ("config", "user_device_activations"), ("config", "reconfigure_device_activations"),
            ("options", "device_activations"),
        ):
            description = data[area]["step"][step]["description"]
            first = description.split("\n\n", 1)[0]
            assert all(part in first for part in hint), (path.name, step)


def test_native_camera_audio_explains_prerequisites_on_all_feature_forms() -> None:
    for path in (INTEGRATION / "strings.json", *TRANSLATIONS.glob("*.json")):
        data = _load_json(path)
        for area, step in (
            ("config", "user_features"), ("config", "reconfigure_features"),
            ("options", "features"),
        ):
            form = data[area]["step"][step]
            assert form["data"]["native_two_way_audio"]
            hint = form["data_description"]["native_two_way_audio"]
            for prerequisite in ("2026.11", "Labs", "WebRTC", "HTTPS", "C300X"):
                assert prerequisite in hint


def test_display_patch_help_says_that_the_alarmo_settings_are_kept() -> None:
    """With the Display patch off the Alarmo entities stay (alarm commands do
    not need the patch); only weather, pages and tiles are discarded."""

    for path in (INTEGRATION / "strings.json", *sorted(TRANSLATIONS.glob("*.json"))):
        data = json.loads(path.read_text(encoding="utf-8"))
        texts = [
            data["config"]["step"]["user_dashboard"]["data_description"]["device_ui_enabled"],
            data["config"]["step"]["reconfigure_dashboard"]["data_description"]["device_ui_enabled"],
            data["options"]["step"]["dashboard"]["data_description"]["device_ui_enabled"],
        ]
        actions_word = {"de": "Aktionen", "fr": "actions", "it": "azioni"}.get(
            path.stem, "action"
        )
        for text in texts:
            assert "Alarmo" in text, (path.name, text)
            # The display actions are discarded with the patch off as well.
            assert actions_word in text, (path.name, text)


def test_doorbell_state_translations_cover_all_raw_agent_values() -> None:
    for path in (
        INTEGRATION / "strings.json",
        TRANSLATIONS / "en.json",
        TRANSLATIONS / "de.json",
        TRANSLATIONS / "it.json",
        TRANSLATIONS / "fr.json",
    ):
        translated_states = _path_value(
            _load_json(path),
            "entity",
            "sensor",
            "doorbell_state",
            "state",
        )
        assert set(DOORBELL_STATES) <= set(translated_states)


def test_smartphone_forwarding_select_translates_internal_options() -> None:
    for path in (
        INTEGRATION / "strings.json",
        TRANSLATIONS / "en.json",
        TRANSLATIONS / "de.json",
        TRANSLATIONS / "it.json",
        TRANSLATIONS / "fr.json",
    ):
        translated_states = _path_value(
            _load_json(path),
            "entity",
            "select",
            "smartphone_forwarding_mode",
            "state",
        )
        assert set(translated_states) == {"enabled", "homeassistant", "blocked"}


def test_agent_event_translations_cover_all_mapped_event_types() -> None:
    expected = set(HA_EVENT_TYPES.values())

    for path in (
        INTEGRATION / "strings.json",
        TRANSLATIONS / "en.json",
        TRANSLATIONS / "de.json",
        TRANSLATIONS / "it.json",
        TRANSLATIONS / "fr.json",
    ):
        translated_states = _path_value(
            _load_json(path),
            "entity",
            "event",
            "agent_event",
            "state_attributes",
            "event_type",
            "state",
        )
        assert expected <= set(translated_states)
        assert all(translated_states[key].strip() and translated_states[key] != key for key in expected)


def test_event_labels_translate_the_attribute_not_the_timestamp_state() -> None:
    for path in (INTEGRATION / "strings.json", *TRANSLATIONS.glob("*.json")):
        events = _load_json(path)["entity"]["event"]
        for key in ("doorbell_event", "agent_event"):
            assert "state" not in events[key], (path.name, key)
        ring = events["doorbell_event"]["state_attributes"]["event_type"]["state"]["ring"]
        assert ring.strip() and ring != "ring", path.name


def test_localized_translation_placeholders_match_base_strings() -> None:
    base_placeholders = _translation_placeholders(
        _load_json(INTEGRATION / "strings.json")
    )

    for path in (
        TRANSLATIONS / "en.json",
        TRANSLATIONS / "de.json",
        TRANSLATIONS / "it.json",
        TRANSLATIONS / "fr.json",
    ):
        assert _translation_placeholders(_load_json(path)) == base_placeholders


def test_fixable_agent_update_repair_uses_ha_issue_fix_flow_schema() -> None:
    """Validate HA can render the agent-update repair flow."""

    for path in (
        INTEGRATION / "strings.json",
        TRANSLATIONS / "en.json",
        TRANSLATIONS / "de.json",
        TRANSLATIONS / "it.json",
        TRANSLATIONS / "fr.json",
    ):
        data = _load_json(path)
        assert "repairs" not in data
        fix_flow = _path_value(
            data,
            "issues",
            "device_agent_update_required",
            "fix_flow",
        )
        assert _path_value(fix_flow, "step", "confirm")["description"]
        ssh_install = _path_value(fix_flow, "step", "ssh_install")
        assert ssh_install["description"]
        assert set(_path_value(ssh_install, "data")) == {
            "bootstrap_ssh_username",
            "bootstrap_ssh_password",
        }
        assert _path_value(fix_flow, "error")["ssh_install_failed"]
        assert _path_value(fix_flow, "abort")["entry_not_loaded"]


def test_fixable_callback_url_repair_uses_ha_issue_fix_flow_schema() -> None:
    """Validate HA can render the callback URL repair flow."""

    for path in (
        INTEGRATION / "strings.json",
        TRANSLATIONS / "en.json",
        TRANSLATIONS / "de.json",
        TRANSLATIONS / "it.json",
        TRANSLATIONS / "fr.json",
    ):
        data = _load_json(path)
        fix_flow = _path_value(
            data,
            "issues",
            "unsupported_callback_url",
            "fix_flow",
        )
        configure = _path_value(fix_flow, "step", "configure")
        assert configure["description"]
        assert set(_path_value(configure, "data")) == {"callback_base_url"}
        assert _path_value(fix_flow, "error")["invalid_callback_base_url"]
        assert _path_value(fix_flow, "abort")["entry_not_loaded"]


def test_fixable_core_qml_hook_repair_uses_ha_issue_fix_flow_schema() -> None:
    """Validate HA can render the core QML hook repair flow."""

    for path in (
        INTEGRATION / "strings.json",
        TRANSLATIONS / "en.json",
        TRANSLATIONS / "de.json",
        TRANSLATIONS / "it.json",
        TRANSLATIONS / "fr.json",
    ):
        data = _load_json(path)
        fix_flow = _path_value(
            data,
            "issues",
            "device_core_qml_hook_required",
            "fix_flow",
        )
        assert _path_value(fix_flow, "step", "confirm")["description"]
        assert _path_value(fix_flow, "error")["core_patch_failed"]
        assert _path_value(fix_flow, "error")["core_patch_verify_failed"]
        assert _path_value(fix_flow, "abort")["entry_not_loaded"]
        assert _path_value(fix_flow, "abort")["core_patch_unsupported"]


def test_fixable_frontend_card_repair_uses_ha_issue_fix_flow_schema() -> None:
    """Validate HA can render the Lovelace-card repair flow."""

    for path in (
        INTEGRATION / "strings.json",
        TRANSLATIONS / "en.json",
        TRANSLATIONS / "de.json",
        TRANSLATIONS / "it.json",
        TRANSLATIONS / "fr.json",
    ):
        data = _load_json(path)
        assert "description" not in _path_value(
            data,
            "issues",
            "device_user_required",
        )
        fix_flow = _path_value(
            data,
            "issues",
            "frontend_card_setup_hint",
            "fix_flow",
        )
        assert "description" not in _path_value(
            data,
            "issues",
            "frontend_card_setup_hint",
        )
        confirm = _path_value(fix_flow, "step", "confirm")
        assert confirm["description"]
        assert _path_value(confirm, "data")["dashboard_path"]
        assert _path_value(confirm, "data")["view_path"]


def test_fixable_media_setup_repair_uses_ha_issue_fix_flow_schema() -> None:
    """Validate HA can render the guided media setup repair flow."""

    for path in (
        INTEGRATION / "strings.json",
        TRANSLATIONS / "en.json",
        TRANSLATIONS / "de.json",
        TRANSLATIONS / "it.json",
        TRANSLATIONS / "fr.json",
    ):
        data = _load_json(path)
        issue = _path_value(
            data,
            "issues",
            "media_setup_repair_required",
        )
        assert "description" not in issue
        assert "firewall, rtsp" in issue["title"].format(failed_checks="firewall, rtsp")
        fix_flow = _path_value(
            data,
            "issues",
            "media_setup_repair_required",
            "fix_flow",
        )
        confirm = _path_value(fix_flow, "step", "confirm")
        assert confirm["title"]
        assert confirm["description"]
        assert _path_value(fix_flow, "error")["media_setup_repair_failed"]
        assert _path_value(fix_flow, "abort")["entry_not_loaded"]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _path_value(value: dict[str, Any], *path: str) -> dict[str, Any]:
    current: Any = value
    for key in path:
        current = current[key]
    assert isinstance(current, dict)
    return current


def _leaf_paths(value: Any, prefix: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    if not isinstance(value, dict):
        return {prefix}

    paths: set[tuple[str, ...]] = set()
    for key, child in value.items():
        paths.update(_leaf_paths(child, (*prefix, key)))
    return paths


def _translation_placeholders(
    value: Any,
    prefix: tuple[str, ...] = (),
) -> dict[tuple[str, ...], set[str]]:
    if isinstance(value, str):
        placeholders = set(re.findall(r"{([a-zA-Z0-9_]+)}", value))
        return {prefix: placeholders} if placeholders else {}
    if not isinstance(value, dict):
        return {}

    placeholders: dict[tuple[str, ...], set[str]] = {}
    for key, child in value.items():
        placeholders.update(_translation_placeholders(child, (*prefix, key)))
    return placeholders


def test_every_error_the_shared_flow_helpers_report_has_a_message_in_each_flow() -> None:
    """A form error without a translation shows its raw key to the user.

    The helpers that setup, reconfigure and options share report errors by key.
    The setup and reconfigure forms look the key up under ``config.error``, the
    options forms under ``options.error``, so each key needs both.
    """

    emitted = set()
    for name in (
        "config_flow_input.py", "config_flow_activations.py", "config_flow_dashboard.py",
        "config_flow_dashboard_pages.py", "config_flow_alarm.py", "config_flow_tiles.py",
    ):
        path = INTEGRATION / name
        if not path.exists():
            continue
        emitted |= set(
            re.findall(
                r'(?:errors\[[^\]]+\]\s*=\s*|"base":\s*|errors\.setdefault\([^,]+,\s*)"([a-z_]+)"',
                path.read_text(encoding="utf-8"),
            )
        )
    assert "invalid_action_map" in emitted
    # An error on a field the form does not have is not shown; it is a base error.
    assert "invalid_dashboard_entity_display_overrides" in emitted
    for path in (INTEGRATION / "strings.json", *TRANSLATIONS.glob("*.json")):
        data = _load_json(path)
        for area in ("config", "options"):
            missing = emitted - set(data[area]["error"])
            assert not missing, (path.name, area, sorted(missing))


def test_every_reason_the_flows_abort_with_has_a_message() -> None:
    """An abort reason without a translation shows its raw key.

    The setup and reconfigure flows abort with reasons of their own and with
    the default of Home Assistant's unique id check.
    """

    reasons = {"unique_id_mismatch"}
    for path in INTEGRATION.glob("config_flow*.py"):
        reasons |= set(re.findall(r'async_abort\(\s*reason="([a-z_]+)"', path.read_text(encoding="utf-8")))
    assert {"already_configured", "cannot_connect", "unique_id_mismatch"} <= reasons
    for path in (INTEGRATION / "strings.json", *TRANSLATIONS.glob("*.json")):
        missing = reasons - set(_load_json(path)["config"]["abort"])
        assert not missing, (path.name, sorted(missing))


def test_options_menu_names_and_explains_every_area() -> None:
    """Each entry of the settings menu and of its Display submenu has a label and a line."""

    menus = {
        "init": {
            "features", "visitor_snapshot", "camera_quality", "device_activations", "speech", "connection",
            "display", "done",
        },
        "display": {
            "dashboard", "dashboard_page_list", "dashboard_entity_display", "dashboard_alarm", "init",
        },
    }
    for path in (INTEGRATION / "strings.json", *TRANSLATIONS.glob("*.json")):
        steps = _load_json(path)["options"]["step"]
        for step_id, entries in menus.items():
            menu = steps[step_id]
            assert menu["title"] and menu["description"], path.name
            assert set(menu["menu_options"]) == entries, path.name
            assert set(menu["menu_option_descriptions"]) == entries, path.name
            assert all(menu["menu_options"].values()), path.name
            assert all(menu["menu_option_descriptions"].values()), path.name
            # A menu entry leads to a step of the same name; "done" closes the dialog.
            assert entries - {"done"} <= set(steps), path.name


def test_the_page_list_names_every_page_like_its_form_section() -> None:
    """A page has one name: in the list and as the title of its form."""

    for path in (INTEGRATION / "strings.json", *TRANSLATIONS.glob("*.json")):
        steps = _load_json(path)["options"]["step"]
        page_list, sections = steps["dashboard_page_list"], steps["dashboard_pages"]["sections"]
        assert page_list["title"] == steps["dashboard_pages"]["title"], path.name
        assert page_list["description"], path.name
        labels = dict(page_list["menu_options"])
        assert labels.pop("page_new") and labels.pop("display"), path.name
        assert labels == {key: section["name"] for key, section in sections.items()}, path.name
        # The texts of the pages are short enough to be read above a form.
        assert len(steps["dashboard_pages"]["description"]) < 320, path.name


def test_tiles_form_labels_and_choices_are_translated_in_every_language() -> None:
    """The tiles form reads its field labels and choices from the selectors."""

    from custom_components.bticino_c300x.config_flow_forms import (
        dashboard_entity_name_display_selector,
        dashboard_entity_secondary_info_selector,
        dashboard_entity_tile_size_selector,
    )
    from custom_components.bticino_c300x.config_flow_tiles import (
        TILE_LABEL_TRANSLATION_KEY,
        TILE_LABELS,
    )

    choices = {
        TILE_LABEL_TRANSLATION_KEY: set(TILE_LABELS),
        **{
            field.config["translation_key"]: set(field.config["options"])
            for field in (
                dashboard_entity_tile_size_selector(),
                dashboard_entity_name_display_selector(),
                dashboard_entity_secondary_info_selector(),
            )
        },
    }
    for path in (INTEGRATION / "strings.json", *TRANSLATIONS.glob("*.json")):
        selectors = _load_json(path)["selector"]
        for key, options in choices.items():
            translated = selectors[key]["options"]
            assert options <= set(translated), (path.name, key)
            assert all(translated[option].strip() for option in options), (path.name, key)
        labels = selectors[TILE_LABEL_TRANSLATION_KEY]["options"]
        fields = [labels[key] for key in ("width", "height", "name", "secondary")]
        # The labels are the keys of a tile's fields.
        assert len(set(fields)) == len(fields), path.name
    assert _load_json(INTEGRATION / "strings.json")["selector"][
        TILE_LABEL_TRANSLATION_KEY
    ]["options"] == TILE_LABELS


def test_settings_choices_are_translated_in_every_language() -> None:
    from custom_components.bticino_c300x.config_schemas import (
        _device_activation_action_selector,
        _device_activation_mode_selector,
        _device_activation_type_selector,
        webrtc_ice_policy_selector,
    )

    for field in (
        _device_activation_action_selector(has_items=True),
        _device_activation_mode_selector(),
        _device_activation_type_selector(),
        webrtc_ice_policy_selector(),
    ):
        key = field.config["translation_key"]
        for path in (INTEGRATION / "strings.json", *TRANSLATIONS.glob("*.json")):
            translated = _load_json(path)["selector"][key]["options"]
            assert set(field.config["options"]) == set(translated), (path.name, key)
            assert all(text.strip() for text in translated.values()), (path.name, key)


def test_every_settings_field_has_a_help_text() -> None:
    """Each field of the options forms says what it does, in every language."""

    for path in (INTEGRATION / "strings.json", *TRANSLATIONS.glob("*.json")):
        steps = _load_json(path)["options"]["step"]
        for step_id, step in steps.items():
            data = step.get("data", {})
            assert set(data) <= set(step.get("data_description", {})), (path.name, step_id)


def test_the_base_strings_and_the_english_translation_have_the_same_keys() -> None:
    """The other languages are compared with en.json; en.json must match the base."""

    def leaves(value: object, prefix: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
        if not isinstance(value, dict):
            return {prefix}
        found: set[tuple[str, ...]] = set()
        for key, child in value.items():
            found |= leaves(child, (*prefix, key))
        return found

    base = leaves(_load_json(INTEGRATION / "strings.json"))
    english = leaves(_load_json(TRANSLATIONS / "en.json"))

    assert sorted(english - base) == []
    assert sorted(base - english) == []


def test_one_error_has_one_wording_in_setup_and_options() -> None:
    for path in (INTEGRATION / "strings.json", *TRANSLATIONS.glob("*.json")):
        data = _load_json(path)
        for key in ("invalid_alarm_entity", "invalid_action_map", "required"):
            assert data["config"]["error"][key] == data["options"]["error"][key], (path.name, key)


def test_the_display_menu_entry_names_only_what_its_form_offers() -> None:
    """The start page buttons are no setting any more; the page navigation is."""

    root = Path(__file__).resolve().parents[1] / "custom_components" / "bticino_c300x"
    removed = ("home page buttons", "Startseiten-Buttons", "boutons d'accueil", "pulsanti della pagina iniziale")
    for name in ("strings.json", "translations/en.json", "translations/de.json", "translations/fr.json", "translations/it.json"):
        options = json.loads((root / name).read_text(encoding="utf-8"))["options"]["step"]
        text = options["display"]["menu_option_descriptions"]["dashboard"]
        assert not any(word in text for word in removed), name
        assert options["dashboard"]["data"]["dashboard_navigation"].lower() in text.lower(), name


def test_camera_quality_form_says_which_stream_it_sets_when_the_resolution_is_low() -> None:
    # On older firmware the values belong to the high-resolution stream; with
    # the Camera resolution select on Low, Home Assistant gets the other one.
    base = Path(__file__).parents[1] / "custom_components" / "bticino_c300x"
    for path in [base / "strings.json", *sorted((base / "translations").glob("*.json"))]:
        texts = json.loads(path.read_text(encoding="utf-8"))
        select = texts["entity"]["select"]["camera_resolution"]
        description = texts["options"]["step"]["camera_quality"]["description"]

        assert f"**{select['name']}**" in description, path.name
        assert select["state"]["low"] in description, path.name

