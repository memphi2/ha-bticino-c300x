from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from custom_components.bticino_c300x.doorbell_state import DOORBELL_STATES

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "bticino_c300x"
TRANSLATIONS = INTEGRATION / "translations"


def test_localized_translation_files_match_english_keys() -> None:
    english = _load_json(TRANSLATIONS / "en.json")

    for language in ("de", "it", "fr"):
        localized = _load_json(TRANSLATIONS / f"{language}.json")
        assert _leaf_paths(localized) == _leaf_paths(english)


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
        assert _path_value(fix_flow, "error")["camera_entity_missing"]
        assert _path_value(fix_flow, "error")["lovelace_storage_unavailable"]
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
