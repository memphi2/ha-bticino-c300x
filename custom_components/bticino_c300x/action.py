"""Pure helpers for C300X action validation."""

from __future__ import annotations

import json
from typing import Any

from .const import ALARM_COMMAND_TO_SERVICE
from .validation_patterns import (
    HA_ACTION_ID_RE,
    HA_DOMAIN_RE,
    HA_ENTITY_ID_RE,
    HA_SERVICE_RE,
)

_DASHBOARD_TYPES = {"button", "switch", "image"}
_DASHBOARD_TEXT_FIELDS = (
    ("name", 80),
    ("page", 60),
    ("state_label", 60),
    ("source", 240),
)
_DASHBOARD_ENTITY_FIELDS = ("entity_id", "state_entity_id")
_DASHBOARD_NUMBER_FIELDS = ("order", "width", "height")


class ActionValidationError(ValueError):
    """Raised when an action or alarm command is invalid."""


def normalize_action_id(action_id: Any) -> str:
    """Return a safe action id or raise ActionValidationError."""

    if not isinstance(action_id, str):
        raise ActionValidationError("action_id must be a string")
    value = action_id.strip()
    if not HA_ACTION_ID_RE.fullmatch(value):
        raise ActionValidationError("action_id contains unsupported characters")
    return value


def alarm_service_for_command(command: Any) -> str:
    """Map a UI alarm command to a Home Assistant alarm_control_panel service."""

    if not isinstance(command, str):
        raise ActionValidationError("command must be a string")
    value = command.strip().lower()
    try:
        return ALARM_COMMAND_TO_SERVICE[value]
    except KeyError as err:
        raise ActionValidationError(f"unsupported alarm command: {value}") from err


def parse_actions_json(raw_value: str | None) -> dict[str, dict[str, Any]]:
    """Parse and validate the JSON action map from an options form."""

    if raw_value is None or raw_value.strip() == "":
        return {}
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as err:
        raise ActionValidationError(f"actions JSON is invalid: {err.msg}") from err
    return validate_action_map(parsed)


def validate_action_map(value: Any) -> dict[str, dict[str, Any]]:
    """Validate the configured action allowlist.

    Expected shape:
    {
      "entry_light": {
        "domain": "light",
        "service": "toggle",
        "data": {"entity_id": "light.entry"}
      }
    }
    """

    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ActionValidationError("actions must be a JSON object")

    validated: dict[str, dict[str, Any]] = {}
    for raw_action_id, raw_action in value.items():
        action_id = normalize_action_id(raw_action_id)
        validated[action_id] = _validate_action_entry(action_id, raw_action)

    return validated


def _validate_action_entry(action_id: str, value: Any) -> dict[str, Any]:
    """Validate one action allowlist entry."""

    if not isinstance(value, dict):
        raise ActionValidationError(f"action {action_id} must be an object")

    item: dict[str, Any] = {
        "domain": _validate_text_pattern(
            action_id,
            value.get("domain"),
            field="domain",
            pattern=HA_DOMAIN_RE,
        ),
        "service": _validate_text_pattern(
            action_id,
            value.get("service"),
            field="service",
            pattern=HA_SERVICE_RE,
        ),
        "data": _validate_action_dict(action_id, value.get("data", {}), "data"),
        "target": _validate_action_dict(action_id, value.get("target", {}), "target"),
    }
    if isinstance(value.get("name"), str):
        item["name"] = _short_text(value["name"], 80)
    dashboard = _validate_dashboard_options(action_id, value.get("dashboard"))
    if dashboard:
        item["dashboard"] = dashboard
    return item


def _validate_text_pattern(
    action_id: str,
    value: Any,
    *,
    field: str,
    pattern: Any,
) -> str:
    """Validate one action text field against a compiled expression."""

    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ActionValidationError(f"action {action_id} has invalid {field}")
    return value


def _validate_action_dict(action_id: str, value: Any, field: str) -> dict[str, Any]:
    """Validate one optional action data or target object."""

    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ActionValidationError(f"action {action_id} {field} must be an object")
    return dict(value)


def _validate_dashboard_options(
    action_id: str,
    value: Any,
) -> dict[str, str | int] | None:
    """Validate optional display metadata for the C300X dashboard."""

    if value is None:
        return None
    if not isinstance(value, dict):
        raise ActionValidationError(f"action {action_id} dashboard must be an object")

    result: dict[str, str | int] = {}
    _copy_dashboard_type(action_id, value, result)
    _copy_dashboard_text_fields(value, result)
    _copy_dashboard_entity_fields(action_id, value, result)
    _copy_dashboard_number_fields(action_id, value, result)

    return result or None


def _copy_dashboard_type(
    action_id: str,
    value: dict[str, Any],
    result: dict[str, str | int],
) -> None:
    item_type = value.get("type")
    if item_type is None:
        return
    item_type = str(item_type).strip().lower()
    if item_type not in _DASHBOARD_TYPES:
        raise ActionValidationError(f"action {action_id} has invalid dashboard type")
    result["type"] = item_type


def _copy_dashboard_text_fields(
    value: dict[str, Any],
    result: dict[str, str | int],
) -> None:
    for key, max_length in _DASHBOARD_TEXT_FIELDS:
        if isinstance(value.get(key), str):
            result[key] = _short_text(value[key], max_length)


def _copy_dashboard_entity_fields(
    action_id: str,
    value: dict[str, Any],
    result: dict[str, str | int],
) -> None:
    for key in _DASHBOARD_ENTITY_FIELDS:
        raw_entity_id = value.get(key)
        if raw_entity_id is None:
            continue
        entity_id = str(raw_entity_id).strip().lower()
        if not HA_ENTITY_ID_RE.fullmatch(entity_id):
            raise ActionValidationError(f"action {action_id} has invalid dashboard entity")
        result[key] = entity_id


def _copy_dashboard_number_fields(
    action_id: str,
    value: dict[str, Any],
    result: dict[str, str | int],
) -> None:
    for key in _DASHBOARD_NUMBER_FIELDS:
        if key not in value:
            continue
        try:
            number = int(value[key])
        except (TypeError, ValueError) as err:
            raise ActionValidationError(f"action {action_id} has invalid dashboard {key}") from err
        result[key] = max(number, 0)


def _short_text(value: str, max_length: int) -> str:
    """Return a compact UI string without control characters."""

    return " ".join(value.split())[:max_length]
