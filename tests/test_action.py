from __future__ import annotations

import pytest

from custom_components.bticino_c300x.action import (
    ActionValidationError,
    alarm_service_for_command,
    normalize_action_id,
    parse_actions_json,
    validate_action_map,
)


def test_normalize_action_id_accepts_safe_value() -> None:
    assert normalize_action_id("entry.light-1") == "entry.light-1"


@pytest.mark.parametrize("value", ["", "contains space", "../bad", "x" * 81, None])
def test_normalize_action_id_rejects_unsafe_value(value: object) -> None:
    with pytest.raises(ActionValidationError):
        normalize_action_id(value)


def test_parse_actions_json_validates_shape() -> None:
    actions = parse_actions_json(
        '{"entry_light":{"domain":"light","service":"toggle","data":{"entity_id":"light.entry"}}}'
    )
    assert actions == {
        "entry_light": {
            "domain": "light",
            "service": "toggle",
            "data": {"entity_id": "light.entry"},
            "target": {},
        }
    }


def test_parse_actions_json_rejects_invalid_json_and_allows_empty_input() -> None:
    assert parse_actions_json(None) == {}
    assert parse_actions_json(" ") == {}
    with pytest.raises(ActionValidationError, match="actions JSON is invalid"):
        parse_actions_json("{")


def test_validate_action_map_allows_none_and_optional_none_dicts() -> None:
    assert validate_action_map(None) == {}
    actions = validate_action_map(
        {
            "entry_light": {
                "domain": "light",
                "service": "toggle",
                "data": None,
                "target": None,
            }
        }
    )

    assert actions["entry_light"]["data"] == {}
    assert actions["entry_light"]["target"] == {}


def test_validate_action_map_allows_target() -> None:
    actions = validate_action_map(
        {
            "scene:leave": {
                "domain": "scene",
                "service": "turn_on",
                "target": {"entity_id": "scene.leave_home"},
            }
        }
    )
    assert actions["scene:leave"]["target"] == {"entity_id": "scene.leave_home"}


def test_validate_action_map_allows_dashboard_metadata() -> None:
    actions = validate_action_map(
        {
            "entry_light": {
                "domain": "light",
                "service": "toggle",
                "target": {"entity_id": "light.entry"},
                "name": " Entry\nlight ",
                "dashboard": {
                    "type": "switch",
                    "page": "Licht",
                    "name": "Diele",
                    "state_entity_id": "light.entry",
                    "order": "10",
                },
            }
        }
    )

    assert actions["entry_light"] == {
        "domain": "light",
        "service": "toggle",
        "data": {},
        "target": {"entity_id": "light.entry"},
        "name": "Entry light",
        "dashboard": {
            "type": "switch",
            "page": "Licht",
            "name": "Diele",
            "state_entity_id": "light.entry",
            "order": 10,
        },
    }


@pytest.mark.parametrize(
    "value",
    [
        [],
        {"ok": []},
        {"bad id": {"domain": "light", "service": "toggle"}},
        {"ok": {"domain": "Light", "service": "toggle"}},
        {"ok": {"domain": "light", "service": "toggle-now"}},
        {"ok": {"domain": "light", "service": "toggle", "data": []}},
        {"ok": {"domain": "light", "service": "toggle", "target": []}},
        {"ok": {"domain": "light", "service": "toggle", "dashboard": []}},
        {
            "ok": {
                "domain": "light",
                "service": "toggle",
                "dashboard": {"type": "bad"},
            }
        },
        {
            "ok": {
                "domain": "light",
                "service": "toggle",
                "dashboard": {"state_entity_id": "bad id"},
            }
        },
        {
            "ok": {
                "domain": "light",
                "service": "toggle",
                "dashboard": {"order": "last"},
            }
        },
    ],
)
def test_validate_action_map_rejects_invalid_values(value: object) -> None:
    with pytest.raises(ActionValidationError):
        validate_action_map(value)


@pytest.mark.parametrize(
    ("command", "service"),
    [
        ("arm_home", "alarm_arm_home"),
        ("arm_away", "alarm_arm_away"),
        ("arm_night", "alarm_arm_night"),
        ("arm_vacation", "alarm_arm_vacation"),
        ("disarm", "alarm_disarm"),
    ],
)
def test_alarm_service_for_command(command: str, service: str) -> None:
    assert alarm_service_for_command(command) == service


def test_alarm_service_for_command_rejects_unknown_command() -> None:
    with pytest.raises(ActionValidationError):
        alarm_service_for_command("panic")
    with pytest.raises(ActionValidationError):
        alarm_service_for_command(None)
