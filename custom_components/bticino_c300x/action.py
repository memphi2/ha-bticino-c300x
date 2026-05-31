"""Pure helpers for C300X action validation."""

from __future__ import annotations

import json
import re
from typing import Any

from .const import ALARM_COMMAND_TO_SERVICE

_ACTION_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_DOMAIN_RE = re.compile(r"^[a-z0-9_]+$")
_SERVICE_RE = re.compile(r"^[a-z0-9_]+$")
_ENTITY_ID_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
_DASHBOARD_TYPES = {"button", "switch", "image"}


class ActionValidationError(ValueError):
    """Raised when an action or alarm command is invalid."""


def normalize_action_id(action_id: Any) -> str:
    """Return a safe action id or raise ActionValidationError."""

    if not isinstance(action_id, str):
        raise ActionValidationError("action_id must be a string")
    value = action_id.strip()
    if not _ACTION_ID_RE.fullmatch(value):
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
        if not isinstance(raw_action, dict):
            raise ActionValidationError(f"action {action_id} must be an object")

        domain = raw_action.get("domain")
        service = raw_action.get("service")
        if not isinstance(domain, str) or not _DOMAIN_RE.fullmatch(domain):
            raise ActionValidationError(f"action {action_id} has invalid domain")
        if not isinstance(service, str) or not _SERVICE_RE.fullmatch(service):
            raise ActionValidationError(f"action {action_id} has invalid service")

        data = raw_action.get("data", {})
        target = raw_action.get("target", {})
        if data is None:
            data = {}
        if target is None:
            target = {}
        if not isinstance(data, dict):
            raise ActionValidationError(f"action {action_id} data must be an object")
        if not isinstance(target, dict):
            raise ActionValidationError(f"action {action_id} target must be an object")

        item = {
            "domain": domain,
            "service": service,
            "data": dict(data),
            "target": dict(target),
        }
        if isinstance(raw_action.get("name"), str):
            item["name"] = _short_text(raw_action["name"], 80)
        dashboard = _validate_dashboard_options(action_id, raw_action.get("dashboard"))
        if dashboard:
            item["dashboard"] = dashboard
        validated[action_id] = item

    return validated


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
    item_type = value.get("type")
    if item_type is not None:
        item_type = str(item_type).strip().lower()
        if item_type not in _DASHBOARD_TYPES:
            raise ActionValidationError(f"action {action_id} has invalid dashboard type")
        result["type"] = item_type

    for key, max_length in (
        ("name", 80),
        ("page", 60),
        ("state_label", 60),
        ("source", 240),
    ):
        if isinstance(value.get(key), str):
            result[key] = _short_text(value[key], max_length)

    for key in ("entity_id", "state_entity_id"):
        raw_entity_id = value.get(key)
        if raw_entity_id is None:
            continue
        entity_id = str(raw_entity_id).strip().lower()
        if not _ENTITY_ID_RE.fullmatch(entity_id):
            raise ActionValidationError(f"action {action_id} has invalid dashboard entity")
        result[key] = entity_id

    for key in ("order", "width", "height"):
        if key not in value:
            continue
        try:
            number = int(value[key])
        except (TypeError, ValueError) as err:
            raise ActionValidationError(f"action {action_id} has invalid dashboard {key}") from err
        result[key] = max(number, 0)

    return result or None


def _short_text(value: str, max_length: int) -> str:
    """Return a compact UI string without control characters."""

    return " ".join(value.split())[:max_length]
