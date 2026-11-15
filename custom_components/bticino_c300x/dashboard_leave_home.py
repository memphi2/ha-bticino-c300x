"""Read-only departure checks and explicitly selected existing action IDs."""

from typing import Any

from .alarm_state import _alarm_commands_for_state
from .const import DASHBOARD_ACTION_DOMAIN
from .dashboard_config import configured_actions, configured_alarm_entity_id
from .dashboard_labels import (
    _DASHBOARD_STATE_LABELS_BY_LANGUAGE,
    _DASHBOARD_STATE_LABELS_EN,
)
from .dashboard_optional_config import configured_leave_home_page
from .dashboard_optional_labels import optional_labels


def leave_home_entity_ids(entry: Any) -> tuple[str, ...]:
    """Entities to include in the existing display state-change subscription."""
    settings = configured_leave_home_page(entry)
    if not settings["enabled"]:
        return ()
    return (*settings["contacts"], *settings["lights"])


def _text(value: Any, limit: int = 80) -> str:
    return " ".join(str(value or "").split())[:limit]


def leave_home_dashboard_page(hass: Any, entry: Any, language: str = "en") -> dict[str, Any] | None:
    """Project HA state only; opening or refreshing the page executes nothing."""
    settings = configured_leave_home_page(entry)
    if not settings["enabled"]:
        return None
    labels = optional_labels(language)
    checks: list[dict[str, Any]] = []
    attention_count = 0
    for kind in ("contacts", "lights"):
        for entity_id in settings[kind]:
            state = hass.states.get(entity_id)
            raw = state.state if state is not None else "unavailable"
            valid_contact = kind != "contacts" or (state is not None and state.attributes.get("device_class") in {
                "door", "window", "opening", "garage_door",
            })
            available = raw in ("on", "off") and valid_contact
            label = "unavailable" if not available else (
                ("open" if raw == "on" else "closed") if kind == "contacts" else raw
            )
            attention_count += not available or raw == "on"
            checks.append({
                "name": _text(state.attributes.get("friendly_name", entity_id) if state else entity_id),
                "state_label": labels[label],
                "color": "#ffd166" if not available else "#ff6b6b" if raw == "on" else "#58d68d",
            })
    allowlist = configured_actions(entry)
    actions = []
    for action_id in settings["actions"]:
        if action_id not in allowlist:
            continue
        action = allowlist[action_id]
        dashboard = action.get("dashboard", {})
        actions.append({"domain": DASHBOARD_ACTION_DOMAIN, "entity_id": action_id,
                        "name": _text(dashboard.get("name") or action.get("name") or action_id),
                        "_kind": "button"})
    alarm = None
    if settings["show_alarm"] and (entity_id := configured_alarm_entity_id(entry)):
        state = hass.states.get(entity_id)
        available = state is not None and state.state not in ("unknown", "unavailable")
        raw_state = state.state if state is not None else "unavailable"
        away = next((command for command in _alarm_commands_for_state(hass, entity_id, state)
                     if command["command"] == "arm_away"), {}) if available and raw_state == "disarmed" else {}
        ready = away.get("ready")
        state_labels = _DASHBOARD_STATE_LABELS_BY_LANGUAGE.get(language, _DASHBOARD_STATE_LABELS_EN)
        state_label = state_labels.get(raw_state, state_labels["unknown"])
        if away:
            state_label = labels["ready" if ready else "not_ready"] if isinstance(ready, bool) else state_labels["unknown"]
        alarm = {"entity_id": entity_id, "name": labels["alarm"],
                 "state": raw_state,
                 "ready": ready, "available": available,
                 "state_label": state_label,
                 "blocking_sensor_count": away.get("blocking_sensor_count", 0)}
    return {"title": labels["leave_home"], "leave_home": {
        "checks": checks, "actions": actions, "alarm": alarm,
        "empty_text": labels["no_checks"],
        "confirm_label": labels["confirm"], "cancel_label": labels["cancel"],
        "attention_count": attention_count,
    }}
