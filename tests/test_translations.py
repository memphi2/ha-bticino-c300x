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
        assert {
            "enabled",
            "homeassistant",
            "blocked",
            "unprovisioned",
        } <= set(translated_states)
        assert translated_states["homeassistant"] != "homeassistant"


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
            "state",
        )
        assert expected <= set(translated_states)


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
    # A key the setup flow alone reports is not shared.
    emitted -= {"required"}
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
    """Each area of the options menu has a label and a line saying what it holds."""

    areas = {
        "dashboard_pages", "dashboard_alarm", "dashboard_entity_display", "dashboard",
        "features", "device_activations", "connection",
    }
    for path in (INTEGRATION / "strings.json", *TRANSLATIONS.glob("*.json")):
        steps = _load_json(path)["options"]["step"]
        menu = steps["init"]
        assert menu["title"] and menu["description"], path.name
        assert set(menu["menu_options"]) == areas, path.name
        assert set(menu["menu_option_descriptions"]) == areas, path.name
        assert all(menu["menu_options"].values()), path.name
        assert all(menu["menu_option_descriptions"].values()), path.name
        # A menu entry leads to a step of the same name.
        assert areas <= set(steps), path.name


def test_tiles_form_labels_and_choices_are_translated_in_every_language() -> None:
    """The tiles form reads its field labels and choices from the selectors."""

    from custom_components.bticino_c300x.config_flow_forms import (
        dashboard_entity_secondary_info_selector,
        dashboard_entity_tile_size_selector,
        dashboard_tile_name_selector,
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
                dashboard_tile_name_selector(),
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
