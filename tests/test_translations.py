from __future__ import annotations

import ast
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


def test_snapshot_size_help_distinguishes_native_framebuffer_from_high_stream() -> None:
    """The display sets the limit and proportions, even for the 960x576 stream."""

    for path in (INTEGRATION / "strings.json", *TRANSLATIONS.glob("*.json")):
        data = _load_json(path)
        for area, step in (
            ("config", "user_visitor_snapshot"), ("config", "reconfigure_visitor_snapshot"),
            ("options", "visitor_snapshot"),
        ):
            help_texts = data[area]["step"][step]["data_description"]
            height = help_texts["snapshot_height"]
            assert all(size in height for size in ("800×480", "960×576", "400×240", "5:3")), (path.name, step)
            width = help_texts["snapshot_width"]
            assert "800×480" in width
            assert "688" not in width and "587×480" not in height
        for area in ("config", "options"):
            assert "800×480" in data[area]["error"]["invalid_snapshot_option"], path.name


# Every value the speaker's last_result can take: the agent's endings
# (native_agent/src/announce_device.c) and the ones media_player.py sets itself.
SPEAKER_RESULTS = {
    "played", "preempted", "stopped", "device_busy", "sound_path_failed", "play_failed",
    "failed", "not_played", "unknown",
}


SPEAKER_PREEMPTED = {
    "strings": "Interrupted by a call or camera view",
    "en": "Interrupted by a call or camera view",
    "de": "Von einem Ruf oder der Kameraansicht unterbrochen",
    "fr": "Interrompu par un appel ou l'affichage caméra",
    "it": "Interrotto da una chiamata o dalla vista telecamera",
}


def test_the_speaker_shows_its_state_and_last_result_in_words_with_a_state_icon() -> None:
    from custom_components.bticino_c300x.media_player import _RESULT_ERRORS

    assert set(_RESULT_ERRORS) <= SPEAKER_RESULTS
    for path in (INTEGRATION / "strings.json", *TRANSLATIONS.glob("*.json")):
        speaker = _load_json(path)["entity"]["media_player"]["speaker"]
        assert set(speaker["state"]) == {"idle", "playing"}, path.name
        last_result = speaker["state_attributes"]["last_result"]
        assert last_result["name"]
        assert set(last_result["state"]) == SPEAKER_RESULTS, path.name
        # A door call, an intercom call and the camera view all take the speaker
        # (native_agent/src/announce_frames.c).
        assert last_result["state"]["preempted"] == SPEAKER_PREEMPTED[path.stem], path.name
        assert all(last_result["state"].values())
    icons = _load_json(INTEGRATION / "icons.json")["entity"]["media_player"]["speaker"]
    assert icons == {"default": "mdi:bullhorn-outline", "state": {"playing": "mdi:bullhorn"}}


# Every cause the capture can record for a visitor image that was not taken.
SNAPSHOT_FAILURES = {
    "snapshot_unavailable", "snapshot_throttled", "invalid_snapshot_size", "invalid_image",
    "agent_unreachable", "agent_error", "save_failed",
}


def _snapshot_failure_codes() -> set[str]:
    """Read the causes out of snapshot_capture.py: what ``_failed`` is called
    with and what ``snapshot_failure_cause`` can return."""

    tree = ast.parse((INTEGRATION / "snapshot_capture.py").read_text(encoding="utf-8"))
    sources: list[ast.AST] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_failed"):
            sources.extend(node.args)
        elif isinstance(node, ast.FunctionDef) and node.name == "snapshot_failure_cause":
            # Skip the docstring; every other text in it is a cause.
            sources.extend(node.body[1:])
    return {
        child.value for source in sources for child in ast.walk(source)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    }


def test_the_italian_visitor_image_failures_name_the_agent_as_the_file_does() -> None:
    """The Italian file keeps "device agent"; a second term for it reads as a second thing."""

    states = _load_json(TRANSLATIONS / "it.json")["entity"]["switch"]["stream_snapshots"][
        "state_attributes"]["last_failure"]["state"]
    for code in ("agent_unreachable", "agent_error"):
        assert "device agent" in states[code].lower(), code
        assert "agente del dispositivo" not in states[code].lower(), code


def test_every_visitor_image_failure_is_shown_in_words_in_every_language() -> None:
    """The switch attribute keeps the code; the frontend shows the translated text."""

    assert _snapshot_failure_codes() == SNAPSHOT_FAILURES
    english = _load_json(TRANSLATIONS / "en.json")["entity"]["switch"]["stream_snapshots"]
    for path in (INTEGRATION / "strings.json", *TRANSLATIONS.glob("*.json")):
        switch = _load_json(path)["entity"]["switch"]["stream_snapshots"]
        last_failure = switch["state_attributes"]["last_failure"]
        assert last_failure["name"], path.name
        assert set(last_failure["state"]) == SNAPSHOT_FAILURES, path.name
        assert all(last_failure["state"].values()), path.name
        if path.stem not in ("strings", "en"):
            # A copied English text is not a translation.
            assert last_failure["name"] != english["state_attributes"]["last_failure"]["name"]
            for code, text in last_failure["state"].items():
                assert text != english["state_attributes"]["last_failure"]["state"][code], (path.name, code)
    guide = (ROOT / "docs" / "user-guide.md").read_text(encoding="utf-8")
    for code, text in english["state_attributes"]["last_failure"]["state"].items():
        assert f"| `{code}` | {text} |" in guide, code


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


STAY_OPEN_WORDING = {
    "strings": ("Keep the page open on screen standby", "standby", "Alarm"),
    "en": ("Keep the page open on screen standby", "standby", "Alarm"),
    "de": ("Seite im Bildschirm-Standby offen lassen", "Standby", "Alarm-Seite"),
    "fr": ("Garder la page ouverte pendant la veille de l'écran", "veille", "Alarme"),
    "it": ("Tenere aperta la pagina durante lo standby dello schermo", "standby", "Allarme"),
}


def test_stay_open_option_names_the_screen_standby_it_acts_on() -> None:
    """The display pages only read the flag when the screen goes to standby
    (handleScreenOff in HomeAssistant.qml and Alarm.qml); the old wording
    promised a stay "after an action", which the flag never controlled."""

    for path in (INTEGRATION / "strings.json", *sorted(TRANSLATIONS.glob("*.json"))):
        data = _load_json(path)
        label, standby, alarm_page = STAY_OPEN_WORDING[path.stem]
        for area, step in (
            ("config", "user_dashboard"), ("config", "reconfigure_dashboard"),
            ("options", "dashboard"),
        ):
            form = data[area]["step"][step]
            assert form["data"]["dashboard_prevent_return"] == label, (path.name, step)
            help_text = form["data_description"]["dashboard_prevent_return"]
            assert standby in help_text, (path.name, step, help_text)
            assert alarm_page in help_text, (path.name, step, help_text)


def test_the_home_page_buttons_name_the_home_page_like_the_rest_of_german() -> None:
    """The German texts call the station's home page "Startseite" everywhere."""

    data = _load_json(TRANSLATIONS / "de.json")
    for area, step in (
        ("config", "user_dashboard"), ("config", "reconfigure_dashboard"),
        ("options", "dashboard"),
    ):
        form = data[area]["step"][step]
        for text in (form["data"]["dashboard_dynamic_homepage"],
                     form["data_description"]["dashboard_dynamic_homepage"]):
            assert "Startseite" in text, (step, text)
            assert "Hauptseite" not in text, (step, text)


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
        # The same flow, with its own text while an update owes display steps.
        for key in ("device_core_qml_hook_required", "device_display_followup_pending"):
            fix_flow = _path_value(data, "issues", key, "fix_flow")
            assert _path_value(fix_flow, "step", "confirm")["description"]
            assert _path_value(fix_flow, "error")["core_patch_failed"]
            assert _path_value(fix_flow, "error")["core_patch_verify_failed"]
            assert _path_value(fix_flow, "abort")["entry_not_loaded"]
            assert _path_value(fix_flow, "abort")["core_patch_unsupported"]
            assert _path_value(fix_flow, "abort")["display_unsupported"]
        owed = _path_value(data, "issues", "device_display_followup_pending")
        confirm = _path_value(owed, "fix_flow", "step", "confirm")["description"]
        assert owed["title"] and "{entry_title}" in confirm
        assert "{qml_patch_status}" not in confirm


def test_no_issue_has_both_a_description_and_a_fix_flow() -> None:
    """Hassfest takes the two as exclusive: a fixable issue explains itself in its flow."""

    for path in (INTEGRATION / "strings.json", *sorted(TRANSLATIONS.glob("*.json"))):
        issues = _path_value(_load_json(path), "issues")
        both = sorted(key for key, issue in issues.items() if "description" in issue and "fix_flow" in issue)
        assert both == [], f"{path.name}: {both}"


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
    removed = (
        "home page buttons", "Startseiten-Buttons", "boutons d'accueil", "pulsanti della pagina iniziale",
        # The stay-open option acts on the screen standby, not after an action.
        "after an action", "nach einer Aktion", "après une action", "dopo un'azione",
    )
    standby = {"de": "Standby", "fr": "veille", "it": "standby"}
    for name in ("strings.json", "translations/en.json", "translations/de.json", "translations/fr.json", "translations/it.json"):
        options = json.loads((root / name).read_text(encoding="utf-8"))["options"]["step"]
        text = options["display"]["menu_option_descriptions"]["dashboard"]
        assert not any(word in text for word in removed), name
        assert standby.get(Path(name).stem, "standby") in text, name
        assert options["dashboard"]["data"]["dashboard_navigation"].lower() in text.lower(), name


def test_the_display_form_texts_name_only_the_fields_of_its_schema() -> None:
    """A field removed from the form must not keep a label or help text."""

    from custom_components.bticino_c300x.config_flow_dashboard import dashboard_schema

    fields = {str(key) for key in dashboard_schema().schema}
    for path in (INTEGRATION / "strings.json", *TRANSLATIONS.glob("*.json")):
        data = _load_json(path)
        for area, step_id in (
            ("config", "user_dashboard"), ("config", "reconfigure_dashboard"), ("options", "dashboard"),
        ):
            step = data[area]["step"][step_id]
            assert set(step["data"]) == fields, (path.name, step_id)
            assert set(step["data_description"]) == fields, (path.name, step_id)


def test_every_raised_service_error_has_a_message_in_every_language() -> None:
    """A key passed to service_validation_error or home_assistant_error must exist under exceptions."""

    raised: set[str] = set()
    for path in INTEGRATION.rglob("*.py"):
        raised |= set(re.findall(
            r'(?:service_validation|home_assistant)_error\(\s*"([a-z0-9_]+)"', path.read_text(encoding="utf-8")))
    assert {"text_memo_write_not_supported", "station_busy"} <= raised
    for path in (INTEGRATION / "strings.json", *TRANSLATIONS.glob("*.json")):
        exceptions = _load_json(path)["exceptions"]
        assert sorted(key for key in raised if not exceptions.get(key, {}).get("message")) == [], path.name


def test_camera_quality_form_says_which_stream_it_sets_when_the_resolution_is_low() -> None:
    # On older firmware the values belong to the high-resolution stream; with
    # the Camera resolution select on Low, Home Assistant gets the other one.
    base = Path(__file__).parents[1] / "custom_components" / "bticino_c300x"
    for path in [base / "strings.json", *sorted((base / "translations").glob("*.json"))]:
        texts = json.loads(path.read_text(encoding="utf-8"))
        select = texts["entity"]["select"]["camera_resolution"]
        description = texts["options"]["step"]["camera_quality"]["description"]

        assert f"**{select['name']}**" in description, path.name
        assert select["state"]["high"] in description, path.name
        assert select["state"]["low"] in description, path.name
        assert "3.0.x" in description, path.name


def test_camera_quality_help_is_brief_and_preserves_reboot_and_runtime_details() -> None:
    reboot_hints = {
        "strings": ("automatically reboots the device", "about a minute"),
        "en": ("automatically reboots the device", "about a minute"),
        "de": ("Gerät automatisch neu", "etwa eine Minute"),
        "fr": ("redémarre automatiquement l'appareil", "environ une minute"),
        "it": ("riavvia automaticamente il dispositivo", "circa un minuto"),
    }
    for path in (INTEGRATION / "strings.json", *TRANSLATIONS.glob("*.json")):
        step = _load_json(path)["options"]["step"]["camera_quality"]
        assert re.findall(r"\{([^{}]+)\}", step["description"]) == ["running"], path.name
        assert len(step["description"]) <= 300, path.name
        assert all(hint in step["description"] for hint in reboot_hints[path.stem]), path.name
        assert set(step["data_description"]) == {"size", "bitrate_kbps", "fps", "use_recommended_snapshot_size"}, path.name
        for key, text in step["data_description"].items():
            assert len(text) <= (170 if key == "size" else 120), (path.name, key)


def test_camera_quality_size_help_explains_agent_dependent_optional_size() -> None:
    size_hints = {
        "strings": ("firmware", "installed device agent", "Optional", "proportions", "when offered"),
        "en": ("firmware", "installed device agent", "Optional", "proportions", "when offered"),
        "de": ("Firmware", "installiertem Geräte-Agent", "Optionales", "Proportionen", "wenn angeboten"),
        "fr": ("firmware", "agent installé", "option", "proportions", "si proposée"),
        "it": ("firmware", "agente installato", "opzione", "proporzioni", "se disponibile"),
    }
    for path in (INTEGRATION / "strings.json", *TRANSLATIONS.glob("*.json")):
        step = _load_json(path)["options"]["step"]["camera_quality"]
        size = step["data_description"]["size"]
        assert "960x576" in size, path.name
        assert all(hint in size for hint in size_hints[path.stem]), path.name


def test_camera_quality_english_translation_matches_base_strings() -> None:
    base = _load_json(INTEGRATION / "strings.json")["options"]["step"]["camera_quality"]
    english = _load_json(TRANSLATIONS / "en.json")["options"]["step"]["camera_quality"]
    assert base == english


def _is_errors(node: ast.expr) -> bool:
    """Whether ``node`` names an errors dict: ``errors``, ``setting_errors``, ``self._errors``."""
    name = node.id if isinstance(node, ast.Name) else getattr(node, "attr", "")
    return name.endswith("errors")


def _error_keys(node: ast.expr | None, scope: ast.AST, seen: frozenset[str] = frozenset()) -> set[str]:
    """The error keys ``node`` can be: a literal, both branches of ``a if c else b``,
    or a variable of ``scope`` assigned one of these."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.IfExp):
        return _error_keys(node.body, scope, seen) | _error_keys(node.orelse, scope, seen)
    if not isinstance(node, ast.Name) or node.id in seen:
        return set()
    keys: set[str] = set()
    for assign in ast.walk(scope):
        pairs = []
        if isinstance(assign, ast.Assign):
            for target in assign.targets:
                pairs.append((target, assign.value))
                if isinstance(target, ast.Tuple) and isinstance(assign.value, ast.Tuple):
                    pairs += zip(target.elts, assign.value.elts, strict=False)
        elif isinstance(assign, ast.AnnAssign):
            pairs.append((assign.target, assign.value))
        for target, value in pairs:
            if isinstance(target, ast.Name) and target.id == node.id:
                keys |= _error_keys(value, scope, seen | {node.id})
    return keys


class _FlowErrors(ast.NodeVisitor):
    """The keys a module puts into a form's errors, and whether it reports ``err.reason``.

    Only error contexts count: ``errors[field] = key``, ``errors = {...}`` (also a
    comprehension), ``errors.setdefault(field, key)``, an ``errors=`` argument, the
    dict a ``*_errors`` function returns, and any ``"base": key`` entry. A variable
    counts only through such a context, resolved in the function that holds it.
    """

    def __init__(self, tree: ast.Module) -> None:
        self.scope: ast.AST = tree
        self.keys: set[str] = set()
        self.reason = False
        self.visit(tree)

    def report(self, node: ast.expr | None) -> None:
        self.keys |= _error_keys(node, self.scope)
        self.reason |= isinstance(node, ast.Attribute) and node.attr == "reason"

    def report_dict(self, node: ast.expr | None) -> None:
        if isinstance(node, ast.Dict):
            for value in node.values:
                self.report(value)
        elif isinstance(node, ast.DictComp):
            self.report(node.value)

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        outer, self.scope = self.scope, node
        if node.name.endswith("_errors"):
            for result in ast.walk(node):
                if isinstance(result, ast.Return):
                    self.report_dict(result.value)
        self.generic_visit(node)
        self.scope = outer

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Subscript) and _is_errors(target.value):
                self.report(node.value)
            elif _is_errors(target):
                self.report_dict(node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if _is_errors(node.target):
            self.report_dict(node.value)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        function = node.func
        if isinstance(function, ast.Attribute) and function.attr == "setdefault" and _is_errors(function.value):
            self.report(node.args[1] if len(node.args) > 1 else None)
        for keyword in node.keywords:
            if keyword.arg == "errors":
                self.report_dict(keyword.value)
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        for key, value in zip(node.keys, node.values, strict=True):
            if isinstance(key, ast.Constant) and key.value == "base":
                self.report(value)
        self.generic_visit(node)


def _flow_reported_errors() -> set[str]:
    """Every error key a setup, reconfigure or options form can show."""

    paths = sorted(INTEGRATION.glob("config_flow*.py"))
    # The flows check the callback URL with this module's helper.
    paths.append(INTEGRATION / "callback_url.py")
    flows = [_FlowErrors(ast.parse(path.read_text(encoding="utf-8"))) for path in paths]
    reported = set().union(*(flow.keys for flow in flows))
    # errors["base"] = err.reason reports the reason the device installer raised.
    assert any(flow.reason for flow in flows)
    integration = "\n".join(path.read_text(encoding="utf-8") for path in INTEGRATION.glob("*.py"))
    constants = dict(re.findall(r'^([A-Z][A-Z0-9_]*) = "([a-z_]+)"$', integration, re.MULTILINE))
    installer = (INTEGRATION / "device_installer.py").read_text(encoding="utf-8")
    for key, constant in re.findall(r'C300XDeviceInstallError\((?:"([a-z_]+)"|([A-Z][A-Z0-9_]*))\)', installer):
        reported.add(key or constants[constant])
    return reported


def test_every_flow_error_message_belongs_to_an_error_the_flows_report() -> None:
    """A message for an error no flow reports is dead text that drifts unnoticed.

    Only places where a flow reports an error count: a key that is also, for
    example, a repair issue id must not keep its form message alive.
    """

    reported = _flow_reported_errors()
    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    unused = sorted(
        f"{section}.error.{key}"
        for section in ("config", "options")
        for key in strings[section].get("error", {})
        if key not in reported
    )
    assert unused == []


def test_the_home_page_buttons_name_the_vendor_layout_stock() -> None:
    names = {"en": "Stock view", "de": "Werksansicht", "it": "Vista di fabbrica", "fr": "Vue d'usine"}
    old = ("Like the original", "Wie das Original", "Come l'originale", "Comme l'original")
    for language, name in names.items():
        data = _load_json(TRANSLATIONS / f"{language}.json")
        option = data["selector"]["dashboard_dynamic_homepage"]["options"]["stock"]
        assert option.startswith(f"{name} ("), (language, option)
        for flow, step in (("config", "user_dashboard"), ("config", "reconfigure_dashboard"), ("options", "dashboard")):
            help_text = data[flow]["step"][step]["data_description"]["dashboard_dynamic_homepage"]
            assert re.search(re.escape(name) + r"\s?:", help_text), (language, step)
            assert not any(text in help_text for text in old), (language, step)
    strings = _load_json(INTEGRATION / "strings.json")
    assert strings["selector"]["dashboard_dynamic_homepage"]["options"]["stock"].startswith("Stock view (")


def test_the_busy_station_message_is_plain_in_every_language() -> None:
    assert _load_json(INTEGRATION / "strings.json")["exceptions"]["station_busy"]["message"] == (
        "The station is busy with a call. Try again after it ends."
    )
    messages = {
        path.stem: _load_json(path)["exceptions"]["station_busy"]["message"]
        for path in TRANSLATIONS.glob("*.json")
    }
    assert set(messages) == {"de", "en", "fr", "it"}
    assert messages["en"] == "The station is busy with a call. Try again after it ends."
    assert len(set(messages.values())) == 4
    for language, message in messages.items():
        # No agent, error code or HTTP wording reaches the user.
        assert not re.search(r"agent|409|station_busy|HTTP", message, re.IGNORECASE), language
