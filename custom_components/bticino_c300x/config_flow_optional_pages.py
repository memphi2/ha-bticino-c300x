"""Form sections for independently enabled optional display pages."""

from typing import Any

from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from .action import ActionValidationError, parse_actions_json, validate_action_map
from .config_flow_forms import optional_suggested
from .const import (
    CONF_ACTIONS,
    CONF_ACTIONS_JSON,
    CONF_AGENDA_PAGE,
    CONF_LEAVE_HOME_PAGE,
    CONF_SITUATIONS_PAGE,
)
from .dashboard_optional_config import (
    MAX_ACTIONS,
    MAX_CALENDARS,
    MAX_CHECKS,
    SITUATION_DOMAINS,
    optional_page_values,
)
from .dashboard_page_order import PAGE_POSITION_MAX
from .schema_compat import vol


def page_position_selector() -> selector.NumberSelector:
    return selector.NumberSelector(selector.NumberSelectorConfig(
        min=1, max=PAGE_POSITION_MAX, step=1, mode=selector.NumberSelectorMode.BOX,
    ))


def optional_page_sections(saved: dict[str, Any], posted: dict[str, Any] | None) -> dict[Any, Any]:
    """Use saved selections on first open and preserve cleared fields on retry."""
    values = optional_page_values(saved)
    try:
        actions = (parse_actions_json(saved[CONF_ACTIONS_JSON]) if CONF_ACTIONS_JSON in saved
                   else validate_action_map(saved.get(CONF_ACTIONS, {})))
    except ActionValidationError:
        actions = {}
    fields: dict[Any, Any] = {}
    for key, options in values.items():
        shown = posted.get(key, options) if posted is not None else options
        shown = shown if isinstance(shown, dict) else {}
        enabled = shown.get("enabled", options["enabled"]) is True
        inner: dict[Any, Any] = {
            vol.Required("enabled", default=enabled): selector.BooleanSelector(),
            optional_suggested("position", shown.get("position")): page_position_selector(),
        }
        domains = {"calendars": "calendar"} if key == CONF_AGENDA_PAGE else {
            "contacts": "binary_sensor", "lights": "light",
        }
        if key == CONF_SITUATIONS_PAGE:
            domains = SITUATION_DOMAINS
        for field, domain in domains.items():
            config = selector.EntitySelectorConfig(domain=domain, multiple=True, reorder=True)
            if field == "contacts":
                config["device_class"] = ["door", "window", "opening", "garage_door"]
            if field == "garages":
                config["device_class"] = ["garage"]
            inner[optional_suggested(field, shown.get(field))] = selector.EntitySelector(config)
        if key == CONF_LEAVE_HOME_PAGE:
            # Retain a removed action visibly so it can be cleared; the backend
            # always intersects selections with the current action allowlist.
            selected = options["actions"]
            choices = list(dict.fromkeys([*actions, *selected]))
            inner[optional_suggested("actions", shown.get("actions"))] = selector.SelectSelector(
                selector.SelectSelectorConfig(options=[selector.SelectOptionDict(
                    value=action_id,
                    label=str(actions.get(action_id, {}).get("name") or action_id),
                ) for action_id in choices], multiple=True, mode=selector.SelectSelectorMode.DROPDOWN)
            )
            inner[vol.Required("show_alarm", default=shown.get("show_alarm") is True)] = selector.BooleanSelector()
        fields[vol.Required(key)] = section(vol.Schema(inner), {"collapsed": not enabled})
    return fields


def optional_pages_input(saved: dict[str, Any], posted: dict[str, Any]) -> dict[str, Any]:
    values = optional_page_values(saved)
    for key, options in values.items():
        if isinstance(posted.get(key), dict):
            values[key] = {"enabled": options["enabled"], **posted[key]}
            if not values[key]["enabled"]:
                values[key].setdefault("position", options["position"])
    return optional_page_values(values)


def optional_pages_errors(posted: dict[str, Any]) -> dict[str, str]:
    """Reject out-of-bound form submissions instead of silently dropping choices."""
    errors: dict[str, str] = {}
    for key, limits in (
        (CONF_AGENDA_PAGE, {"calendars": MAX_CALENDARS}),
        (CONF_LEAVE_HOME_PAGE, {"contacts": MAX_CHECKS, "lights": MAX_CHECKS, "actions": MAX_ACTIONS}),
        (CONF_SITUATIONS_PAGE, dict.fromkeys(SITUATION_DOMAINS, MAX_CHECKS)),
    ):
        section_input = posted.get(key)
        if not isinstance(section_input, dict):
            continue
        normalized = optional_page_values({key: section_input})[key]
        for field, limit in limits.items():
            raw = section_input.get(field, [])
            if not isinstance(raw, list) or len(raw) > limit or raw != normalized[field]:
                errors[key] = "invalid_action_map" if field == "actions" else "invalid_dashboard_entities"
    return errors
