"""Execution helpers used by webhooks and services."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from enum import IntFlag
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

try:
    from homeassistant.components.alarm_control_panel import (
        AlarmControlPanelEntityFeature,
    )
except ImportError:  # pragma: no cover - local test stubs

    class AlarmControlPanelEntityFeature(IntFlag):
        """Fallback subset of HA alarm-control-panel feature flags."""

        ARM_HOME = 1
        ARM_AWAY = 2
        ARM_NIGHT = 4
        ARM_CUSTOM_BYPASS = 16
        ARM_VACATION = 32

try:
    from homeassistant.util import dt as dt_util
except ImportError:  # pragma: no cover - local test stubs
    dt_util = None

try:
    from homeassistant.helpers import entity_registry as er
except (ImportError, ModuleNotFoundError):  # pragma: no cover - local test stubs
    er = None

from .action import (
    ActionValidationError,
    alarm_service_for_command,
    normalize_action_id,
    validate_action_map,
)
from .activation_address import stair_light_where_from_entry_values
from .capabilities import entry_device_ui_enabled_or_patch_active
from .const import (
    ALARM_DOMAIN,
    CONF_ACTIONS,
    CONF_ALARM_ENTITY_ID,
    CONF_ALARM_PAGE_ENTITY_ID,
    CONF_DASHBOARD_ENTITIES,
    CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
    CONF_DASHBOARD_PREVENT_RETURN,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P,
    CONF_WEATHER_ENTITY_ID,
    DASHBOARD_ACTION_DOMAIN,
    DASHBOARD_ENTITY_ANSWERING_MACHINE,
    DASHBOARD_ENTITY_DOOR_UNLOCK,
    DASHBOARD_ENTITY_NAME_DISPLAY_CUSTOM,
    DASHBOARD_ENTITY_NAME_DISPLAY_ENTITY_ID,
    DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME,
    DASHBOARD_ENTITY_SECONDARY_INFO_ENTITY_ID,
    DASHBOARD_ENTITY_SECONDARY_INFO_LAST_CHANGED,
    DASHBOARD_ENTITY_SECONDARY_INFO_LAST_UPDATED,
    DASHBOARD_ENTITY_SECONDARY_INFO_NONE,
    DASHBOARD_ENTITY_SECONDARY_INFO_STATE,
    DASHBOARD_ENTITY_STAIR_LIGHT,
    DOMAIN,
    EVENT_ACTION_RECEIVED,
)
from .dashboard_entities import (
    DASHBOARD_ENTITY_DOMAIN_SET,
    dashboard_entity_custom_name_override,
    dashboard_entity_name_display_override,
    dashboard_entity_secondary_info_override,
    normalize_dashboard_entity_display_overrides,
    normalize_dashboard_entity_ids,
)
from .dashboard_labels import (
    _BINARY_SENSOR_DEVICE_CLASS_COLORS,
    _BINARY_SENSOR_DEVICE_CLASS_LABELS_BY_LANGUAGE,
    _BINARY_SENSOR_DEVICE_CLASS_LABELS_EN,
    _DASHBOARD_COLOR_BAD,
    _DASHBOARD_COLOR_GOOD,
    _DASHBOARD_COLOR_NEUTRAL,
    _DASHBOARD_COLOR_WARNING,
    _DASHBOARD_ON_STATES,
    _DASHBOARD_STATE_LABELS_BY_LANGUAGE,
    _DASHBOARD_STATE_LABELS_EN,
)
from .dashboard_weather import dashboard_weather_payload
from .entity import entry_config_value


def _alarm_feature(name: str, fallback: int) -> AlarmControlPanelEntityFeature:
    return getattr(
        AlarmControlPanelEntityFeature,
        name,
        AlarmControlPanelEntityFeature(fallback),
    )


_ALARM_ARM_COMMANDS = (
    ("arm_home", "armed_home", "Zuhause", _alarm_feature("ARM_HOME", 1)),
    ("arm_away", "armed_away", "Abwesend", _alarm_feature("ARM_AWAY", 2)),
    ("arm_night", "armed_night", "Nacht", _alarm_feature("ARM_NIGHT", 4)),
    (
        "arm_custom_bypass",
        "armed_custom_bypass",
        "Bypass",
        _alarm_feature("ARM_CUSTOM_BYPASS", 16),
    ),
    (
        "arm_vacation",
        "armed_vacation",
        "Urlaub",
        _alarm_feature("ARM_VACATION", 32),
    ),
)

_ALARM_COMMAND_TARGET_STATES = {
    command: state for command, state, _name, _feature in _ALARM_ARM_COMMANDS
}
_ALARM_COMMAND_TARGET_STATES["disarm"] = "disarmed"
_ALARMO_DOMAIN = "alarmo"
_ALARMO_FORCE_ARM_MODES = {
    "arm_away": "away",
    "arm_home": "home",
    "arm_night": "night",
    "arm_custom_bypass": "custom",
    "arm_vacation": "vacation",
}
_ARMED_ALARM_STATES = frozenset(_ALARM_COMMAND_TARGET_STATES.values()) - {"disarmed"}
_ALARM_CODE_ARM_REQUIRED = "code_arm_required"
_ALARM_CODE_MODE_CHANGE_REQUIRED = "code_mode_change_required"
_ALARM_CODE_DISARM_REQUIRED = "code_disarm_required"
_ALARM_CODE_FORMAT = "code_format"
_ALARM_DISARM_COMMAND = ("disarm", "disarmed", "Aus")
_DASHBOARD_DEFAULT_PAGE = "C300X"
_DASHBOARD_ACTION_PAGE = "Home Assistant"
_ALARM_STATE_CHANGE_TIMEOUT_SECONDS = 5.0
_ALARM_STATE_CHANGE_INTERVAL_SECONDS = 0.2
_MAX_ALARM_BLOCKING_SENSORS = 8
_DASHBOARD_SWITCH_DOMAINS = {"fan", "input_boolean", "light", "switch"}
_DASHBOARD_SWITCH_SERVICES = {"toggle"}
_DASHBOARD_TOGGLE_ENTITY_DOMAINS = {"fan", "input_boolean", "light", "switch"}
_DASHBOARD_BUTTON_ENTITY_DOMAINS = {"button", "input_button", "scene", "script"}
_DASHBOARD_SLIDER_ENTITY_DOMAINS = {"input_number", "number"}
_DASHBOARD_CHOICE_ENTITY_DOMAINS = {"input_select", "select"}
_DASHBOARD_READ_ONLY_ENTITY_DOMAINS = {"binary_sensor", "sensor"}
_DASHBOARD_SUPPORTED_ENTITY_DOMAINS = DASHBOARD_ENTITY_DOMAIN_SET
_DASHBOARD_SLIDER_ACTIONS = {"decrement", "increment"}
_DASHBOARD_CHOICE_ACTIONS = {"next", "previous"}


def _dashboard_language(hass: HomeAssistant | None) -> str:
    language = str(getattr(getattr(hass, "config", None), "language", "") or "").lower()
    if language.startswith("de"):
        return "de"
    if language.startswith("fr"):
        return "fr"
    if language.startswith("it"):
        return "it"
    return "en"


def configured_alarm_entity_id(entry: ConfigEntry) -> str | None:
    """Return the alarm entity configured for a C300X entry."""

    value = entry_config_value(entry, CONF_ALARM_ENTITY_ID)
    return value if isinstance(value, str) and value else None


def configured_alarm_page_entity_id(entry: ConfigEntry) -> str | None:
    """Return the optional dashboard-compatible entity shown on the alarm page."""

    value = entry_config_value(entry, CONF_ALARM_PAGE_ENTITY_ID)
    entities = _dashboard_entity_ids([value] if isinstance(value, str) else value)
    return entities[0] if entities else None


def configured_weather_entity_id(entry: ConfigEntry) -> str | None:
    """Return the weather entity configured for the C300X dashboard."""

    value = entry_config_value(entry, CONF_WEATHER_ENTITY_ID)
    return value if isinstance(value, str) and value else None


def configured_actions(entry: ConfigEntry) -> dict[str, dict[str, Any]]:
    """Return the validated configured action allowlist."""

    try:
        return validate_action_map(
            entry_config_value(entry, CONF_ACTIONS, {})
        )
    except ActionValidationError:
        return {}


def configured_dashboard_entities(entry: ConfigEntry) -> tuple[str, ...]:
    """Return selected standard HA entities for the C300X dashboard."""

    return _dashboard_entity_ids(entry_config_value(entry, CONF_DASHBOARD_ENTITIES, []))


def configured_dashboard_entity_display_overrides(
    entry: ConfigEntry,
) -> dict[str, dict[str, str]]:
    """Return per-entity dashboard display overrides."""

    return normalize_dashboard_entity_display_overrides(
        entry_config_value(entry, CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES, {})
    )


def configured_dashboard_prevent_return(entry: ConfigEntry) -> bool:
    """Return whether the dashboard should prevent returning to the homepage."""

    return bool(entry_config_value(entry, CONF_DASHBOARD_PREVENT_RETURN, True))


def _dashboard_entity_ids(value: Any) -> tuple[str, ...]:
    """Normalize selected dashboard entity IDs without importing the config flow."""

    return normalize_dashboard_entity_ids(value)


async def async_status(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return state data intended for the C300X UI."""

    device_ui_enabled = bool(entry_device_ui_enabled_or_patch_active(entry))
    actions = configured_actions(entry)
    dashboard_entities = configured_dashboard_entities(entry)
    alarm_entity_id = configured_alarm_entity_id(entry)
    language = _dashboard_language(hass)
    alarm: dict[str, Any] | None = None
    if device_ui_enabled and alarm_entity_id:
        state = hass.states.get(alarm_entity_id)
        active_since, active_since_label = _state_active_since(state)
        alarm = {
            "entity_id": alarm_entity_id,
            "state": state.state if state is not None else "unavailable",
            "active_since": active_since,
            "active_since_label": active_since_label,
            "commands": _alarm_commands_for_state(hass, alarm_entity_id, state),
        }
        alarm.update(_alarm_delay_payload(hass, alarm_entity_id, state))
        alarm.update(_alarm_sensor_payload(hass, alarm_entity_id, state))

    return {
        "ok": True,
        "entry_id": entry.entry_id,
        "title": entry.title,
        "alarm": alarm,
        "alarm_page_entity": _alarm_page_entity(hass, entry, language)
        if device_ui_enabled
        else None,
        "alarm_configured": alarm is not None,
        "dashboard_available": device_ui_enabled
        and (
            bool(actions)
            or bool(dashboard_entities)
            or configured_weather_entity_id(entry) is not None
        ),
        "device_ui_enabled": device_ui_enabled,
        "actions": sorted(actions.keys()) if device_ui_enabled else [],
    }


async def async_execute_action(
    hass: HomeAssistant,
    entry: ConfigEntry,
    action_id: str,
) -> dict[str, Any]:
    """Execute a configured action by id."""

    normalized_id = normalize_action_id(action_id)
    actions = configured_actions(entry)
    if normalized_id not in actions:
        raise KeyError(normalized_id)

    action = actions[normalized_id]
    service_data = dict(action.get("data") or {})
    target = dict(action.get("target") or {})
    if "entity_id" in target and "entity_id" not in service_data:
        service_data["entity_id"] = target["entity_id"]

    await hass.services.async_call(
        action["domain"],
        action["service"],
        service_data,
        blocking=False,
        target=target or None,
    )
    hass.bus.async_fire(
        EVENT_ACTION_RECEIVED,
        {"entry_id": entry.entry_id, "action_id": normalized_id},
    )
    return {"ok": True, "action_id": normalized_id}


async def async_execute_alarm_command(
    hass: HomeAssistant,
    entry: ConfigEntry,
    command: str,
    code: str | None,
    *,
    force: bool = False,
    check: bool = False,
) -> dict[str, Any]:
    """Execute an alarm command against the configured alarm entity."""

    alarm_entity_id = configured_alarm_entity_id(entry)
    if alarm_entity_id is None:
        raise ValueError("alarm entity is not configured")

    current_state = _current_alarm_state(hass, alarm_entity_id)
    alarm_state = hass.states.get(alarm_entity_id)
    if check:
        preflight = _alarmo_command_preflight(
            hass,
            alarm_entity_id,
            alarm_state,
            command,
            for_command=True,
        )
        if preflight is not None and preflight["ready"] is False:
            return _alarm_not_ready_response(
                command,
                alarm_entity_id,
                current_state,
                preflight,
                check=True,
            )
        return {
            "ok": True,
            "check": True,
            "command": command,
            "entity_id": alarm_entity_id,
            "state": current_state,
            **(
                preflight
                if preflight is not None
                else {
                    "ready": True,
                    "blocking_sensors": [],
                    "blocking_sensor_count": 0,
                }
            ),
        }

    if (
        not force
        and (
            preflight := _alarmo_command_preflight(
                hass,
                alarm_entity_id,
                alarm_state,
                command,
                for_command=True,
            )
        )
        is not None
        and preflight["ready"] is False
    ):
        return _alarm_not_ready_response(command, alarm_entity_id, current_state, preflight)

    if force and command in _ALARMO_FORCE_ARM_MODES:
        domain = _ALARMO_DOMAIN
        service = "arm"
        service_data = {
            "entity_id": alarm_entity_id,
            "mode": _ALARMO_FORCE_ARM_MODES[command],
            "force": True,
        }
        if code:
            service_data["code"] = code
    else:
        domain = ALARM_DOMAIN
        service = alarm_service_for_command(command)
        service_data = {"entity_id": alarm_entity_id}
        if code:
            service_data["code"] = code

    try:
        await hass.services.async_call(
            domain,
            service,
            service_data,
            blocking=True,
        )
    except Exception as err:
        if (
            preflight := _alarmo_command_preflight(
                hass,
                alarm_entity_id,
                hass.states.get(alarm_entity_id),
                command,
                for_command=True,
            )
        ) is not None and preflight["ready"] is False:
            return _alarm_not_ready_response(
                command,
                alarm_entity_id,
                _current_alarm_state(hass, alarm_entity_id),
                preflight,
            )
        return _alarm_service_error_response(
            command,
            alarm_entity_id,
            _current_alarm_state(hass, alarm_entity_id),
            err,
        )
    target_states = _target_alarm_states(command)
    if (
        current_state is not None
        and target_states
        and not await _async_wait_for_alarm_state(hass, alarm_entity_id, target_states)
    ):
        if (
            preflight := _alarmo_command_preflight(
                hass,
                alarm_entity_id,
                hass.states.get(alarm_entity_id),
                command,
                for_command=True,
            )
        ) is not None and preflight["ready"] is False:
            return _alarm_not_ready_response(
                command,
                alarm_entity_id,
                _current_alarm_state(hass, alarm_entity_id),
                preflight,
            )
        return _alarm_state_unchanged_response(
            command,
            alarm_entity_id,
            _current_alarm_state(hass, alarm_entity_id),
            code=code,
        )
    return {
        "ok": True,
        "command": command,
        "entity_id": alarm_entity_id,
        "state": _current_alarm_state(hass, alarm_entity_id),
    }


async def async_trigger_stair_light(
    hass: HomeAssistant,
    entry: ConfigEntry,
    address: str | None = None,
) -> dict[str, Any]:
    """Activate the staircase light through the configured agent."""

    target_address = address or stair_light_where_from_entry_values(
        entry_config_value(entry, CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P, ""),
        entry_config_value(entry, CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N, ""),
    )
    await entry.runtime_data.api.async_stair_light(target_address)
    hass.bus.async_fire(
        EVENT_ACTION_RECEIVED,
        {
            "entry_id": entry.entry_id,
            "action_id": DASHBOARD_ENTITY_STAIR_LIGHT,
            "address": str(target_address),
        },
    )
    return {
        "ok": True,
        "action_id": DASHBOARD_ENTITY_STAIR_LIGHT,
        "address": str(target_address),
    }


async def async_unlock_door(
    hass: HomeAssistant,
    entry: ConfigEntry,
    lock_id: str = "default",
) -> dict[str, Any]:
    """Unlock a configured C300X door lock through the device agent."""

    await entry.runtime_data.api.async_unlock_door(lock_id)
    hass.bus.async_fire(
        EVENT_ACTION_RECEIVED,
        {
            "entry_id": entry.entry_id,
            "action_id": DASHBOARD_ENTITY_DOOR_UNLOCK,
            "lock_id": str(lock_id),
        },
    )
    return {
        "ok": True,
        "action_id": DASHBOARD_ENTITY_DOOR_UNLOCK,
        "lock_id": str(lock_id),
    }


async def async_dashboard_payload(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return data in the c300x-dashboard `/homeassistant` JSON shape."""

    status = await async_status(hass, entry)
    prevent_return = configured_dashboard_prevent_return(entry)
    if not status.get("device_ui_enabled"):
        return {
            "preventReturnToHomepage": prevent_return,
            "refreshInterval": 0,
            "data": {"pages": []},
        }
    language = _dashboard_language(hass)
    pages: dict[str, dict[str, Any]] = {}
    main_page = _dashboard_page(pages, _DASHBOARD_DEFAULT_PAGE)
    badges = [{"state": "HA\nonline", "color": "#58d68d"}]

    alarm = status.get("alarm")
    if isinstance(alarm, dict):
        badges.append(
            {"state": f"Alarm\n{_dashboard_alarm_state(alarm.get('state'), language)}"}
        )

    badges.append({"state": _dashboard_datetime_label()})
    weather = dashboard_weather_payload(hass, configured_weather_entity_id(entry), language)
    if weather is not None:
        main_page["weather"] = weather

    main_page["badges"] = badges
    entity_display_overrides = configured_dashboard_entity_display_overrides(entry)
    for index, entity_id in enumerate(configured_dashboard_entities(entry), start=1):
        dashboard_item = _dashboard_item_for_entity(
            hass,
            entity_id,
            index * 10,
            name_display=dashboard_entity_name_display_override(
                entity_display_overrides,
                entity_id,
                DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME,
            ),
            custom_name=dashboard_entity_custom_name_override(
                entity_display_overrides,
                entity_id,
            ),
            secondary_info=dashboard_entity_secondary_info_override(
                entity_display_overrides,
                entity_id,
                DASHBOARD_ENTITY_SECONDARY_INFO_STATE,
            ),
            language=language,
        )
        if dashboard_item is None:
            continue
        page = _dashboard_page(pages, dashboard_item.pop("_page"))
        kind = dashboard_item.pop("_kind")
        page[_dashboard_collection_key(kind)].append(dashboard_item)

    for action_id, action in configured_actions(entry).items():
        dashboard_item = _dashboard_item_for_action(
            hass,
            action_id,
            action,
            language=language,
        )
        if dashboard_item is None:
            continue
        page = _dashboard_page(pages, dashboard_item.pop("_page"))
        kind = dashboard_item.pop("_kind")
        page[_dashboard_collection_key(kind)].append(dashboard_item)

    return {
        "preventReturnToHomepage": prevent_return,
        "refreshInterval": 0,
        "data": {
            "pages": [
                _finalize_dashboard_page(page)
                for page in pages.values()
                if _dashboard_page_has_content(page)
            ]
        },
    }


async def async_execute_dashboard_action(
    hass: HomeAssistant,
    entry: ConfigEntry,
    entity_id: str,
    *,
    option: str | None = None,
) -> dict[str, Any]:
    """Execute a dashboard-compatible c300x action id."""

    if entity_id == DASHBOARD_ENTITY_STAIR_LIGHT:
        return await async_trigger_stair_light(hass, entry)
    if entity_id == DASHBOARD_ENTITY_DOOR_UNLOCK:
        return await async_unlock_door(hass, entry)
    if entity_id == DASHBOARD_ENTITY_ANSWERING_MACHINE:
        status = await entry.runtime_data.api.async_answering_machine_status()
        enabled = bool(status.get("enabled"))
        result = await entry.runtime_data.api.async_set_answering_machine_enabled(
            not enabled
        )
        return {
            "ok": True,
            "action_id": DASHBOARD_ENTITY_ANSWERING_MACHINE,
            "enabled": result.get("enabled"),
        }
    selected_entity_id, selected_action = _dashboard_selected_entity_action(entity_id)
    allowed_dashboard_entities = set(configured_dashboard_entities(entry))
    alarm_page_entity_id = configured_alarm_page_entity_id(entry)
    if alarm_page_entity_id:
        allowed_dashboard_entities.add(alarm_page_entity_id)
    if selected_entity_id in allowed_dashboard_entities:
        return await _async_execute_dashboard_entity(
            hass,
            entry,
            selected_entity_id,
            selected_action,
            option=option,
        )
    return await async_execute_action(hass, entry, entity_id)


def _dashboard_alarm_state(state: Any, language: str) -> str:
    return _dashboard_state_label(state, language)


def _dashboard_datetime_label() -> str:
    """Return the compact date/time badge for the device dashboard."""

    now_func = getattr(dt_util, "now", None) if dt_util is not None else None
    now = now_func() if callable(now_func) else datetime.now()
    return now.strftime("%d.%m.\n%H:%M")


def _alarm_page_entity(
    hass: HomeAssistant,
    entry: ConfigEntry,
    language: str,
) -> dict[str, Any]:
    entity_id = configured_alarm_page_entity_id(entry)
    if entity_id is None:
        return {
            "kind": "button",
            "domain": DASHBOARD_ACTION_DOMAIN,
            "entity_id": DASHBOARD_ENTITY_STAIR_LIGHT,
            "name": DASHBOARD_ENTITY_STAIR_LIGHT,
            "name_key": "stair_light",
            "state_label": "",
        }
    item = _dashboard_item_for_entity(
        hass,
        entity_id,
        0,
        language=language,
    )
    if item is None:
        return {
            "kind": "entity",
            "domain": DASHBOARD_ACTION_DOMAIN,
            "entity_id": entity_id,
            "name": entity_id,
            "state_label": "unavailable",
            "color": _DASHBOARD_COLOR_WARNING,
        }
    payload = dict(item)
    payload["kind"] = str(payload.pop("_kind", "entity"))
    payload.pop("_page", None)
    payload.pop("_order", None)
    return payload


def _dashboard_page(
    pages: dict[str, dict[str, Any]],
    title: Any,
) -> dict[str, Any]:
    page_title = _dashboard_text(title, _DASHBOARD_ACTION_PAGE, 60)
    if page_title not in pages:
        pages[page_title] = {
            "title": page_title,
            "badges": [],
            "buttons": [],
            "switches": [],
            "entities": [],
            "sliders": [],
            "choices": [],
            "images": [],
            "weather": None,
        }
    return pages[page_title]


def _dashboard_item_for_entity(
    hass: HomeAssistant,
    entity_id: str,
    order: int,
    *,
    name_display: str = DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME,
    custom_name: str = "",
    secondary_info: str = DASHBOARD_ENTITY_SECONDARY_INFO_STATE,
    language: str = "en",
) -> dict[str, Any] | None:
    """Return a dashboard item for one directly selected HA entity."""

    domain = entity_id.split(".", 1)[0]
    if domain not in _DASHBOARD_SUPPORTED_ENTITY_DOMAINS:
        return None

    state = hass.states.get(entity_id)
    name = _entity_name(
        entity_id,
        state,
        display=name_display,
        custom_name=custom_name,
    )
    item: dict[str, Any] = {
        "domain": DASHBOARD_ACTION_DOMAIN,
        "entity_id": entity_id,
        "name": name,
        "state_label": _entity_secondary_label(
            state,
            entity_id,
            secondary_info,
            language=language,
        ),
        "_page": _DASHBOARD_ACTION_PAGE,
        "_order": order,
    }
    if domain in _DASHBOARD_TOGGLE_ENTITY_DOMAINS:
        item["_kind"] = "switch"
        item["state"] = _dashboard_state_is_on(state.state if state else None)
        return item
    if domain in _DASHBOARD_BUTTON_ENTITY_DOMAINS:
        item["_kind"] = "button"
        item["state_label"] = _button_secondary_label(
            state,
            entity_id,
            secondary_info,
            language=language,
        )
        return item
    if domain in _DASHBOARD_SLIDER_ENTITY_DOMAINS:
        item["_kind"] = "slider"
        item.update(_dashboard_slider_payload(state))
        return item
    if domain in _DASHBOARD_CHOICE_ENTITY_DOMAINS:
        item["_kind"] = "choice"
        item.update(_dashboard_choice_payload(state))
        return item
    item["_kind"] = "entity"
    item["state"] = _dashboard_state_is_on(state.state if state else None)
    color = _entity_state_color(state, entity_id=entity_id)
    if color is not None:
        item["color"] = color
    return item


def _dashboard_item_for_action(
    hass: HomeAssistant,
    action_id: str,
    action: dict[str, Any],
    *,
    language: str = "en",
) -> dict[str, Any] | None:
    dashboard = action.get("dashboard")
    if not isinstance(dashboard, dict):
        dashboard = {}

    kind = _dashboard_kind(action, dashboard)
    page = _dashboard_text(dashboard.get("page"), _DASHBOARD_ACTION_PAGE, 60)
    order = _dashboard_int(dashboard.get("order"), 1000)
    name = _dashboard_text(
        dashboard.get("name") or action.get("name"),
        action_id,
        80,
    )

    if kind == "image":
        source = _dashboard_image_source(hass, action, dashboard)
        if not source:
            return None
        image = {
            "source": source,
            "width": _dashboard_int(dashboard.get("width"), 220),
            "height": _dashboard_int(dashboard.get("height"), 120),
            "_kind": "image",
            "_page": page,
            "_order": order,
        }
        if name:
            image["name"] = name
        return image

    item: dict[str, Any] = {
        "domain": DASHBOARD_ACTION_DOMAIN,
        "entity_id": action_id,
        "name": name,
        "_kind": kind,
        "_page": page,
        "_order": order,
    }
    state = _dashboard_action_state(hass, action, dashboard)
    if kind == "switch":
        item["state"] = _dashboard_state_is_on(state.state if state else None)
    if kind == "button":
        item["state_label"] = _dashboard_text(dashboard.get("state_label"), "", 60)
    elif state is not None:
        item["state_label"] = _dashboard_text(
            dashboard.get("state_label"),
            _dashboard_state_label(state.state, language),
            60,
        )
    return item


def _dashboard_kind(action: dict[str, Any], dashboard: dict[str, Any]) -> str:
    item_type = dashboard.get("type")
    if item_type in {"button", "image", "switch"}:
        return str(item_type)
    if (
        action.get("domain") in _DASHBOARD_SWITCH_DOMAINS
        and action.get("service") in _DASHBOARD_SWITCH_SERVICES
    ):
        return "switch"
    if dashboard.get("source"):
        return "image"
    return "button"


async def _async_execute_dashboard_entity(
    hass: HomeAssistant,
    entry: ConfigEntry,
    entity_id: str,
    action: str | None,
    *,
    option: str | None = None,
) -> dict[str, Any]:
    """Execute the default action for a directly selected dashboard entity."""

    domain = entity_id.split(".", 1)[0]
    if domain in _DASHBOARD_TOGGLE_ENTITY_DOMAINS:
        await hass.services.async_call(
            domain,
            "toggle",
            {"entity_id": entity_id},
            blocking=True,
        )
    elif domain == "button":
        await hass.services.async_call(
            domain,
            "press",
            {"entity_id": entity_id},
            blocking=True,
        )
    elif domain == "input_button":
        await hass.services.async_call(
            "input_button",
            "press",
            {"entity_id": entity_id},
            blocking=True,
        )
    elif domain in {"scene", "script"}:
        await hass.services.async_call(
            domain,
            "turn_on",
            {"entity_id": entity_id},
            blocking=True,
        )
    elif domain in _DASHBOARD_SLIDER_ENTITY_DOMAINS:
        await _async_adjust_dashboard_slider(hass, entity_id, action)
    elif domain in _DASHBOARD_CHOICE_ENTITY_DOMAINS:
        await _async_adjust_dashboard_choice(hass, entity_id, action, option=option)
    else:
        raise ValueError("read_only_dashboard_entity")

    hass.bus.async_fire(
        EVENT_ACTION_RECEIVED,
        {"entry_id": entry.entry_id, "action_id": entity_id},
    )
    return {"ok": True, "action_id": entity_id}


async def _async_adjust_dashboard_slider(
    hass: HomeAssistant,
    entity_id: str,
    action: str | None,
) -> None:
    """Increment or decrement a selected number/input_number entity."""

    if action not in _DASHBOARD_SLIDER_ACTIONS:
        raise ValueError("invalid_dashboard_slider_action")
    state = hass.states.get(entity_id)
    if state is None:
        raise ValueError("dashboard_entity_unavailable")
    attributes = getattr(state, "attributes", None)
    if not isinstance(attributes, dict):
        attributes = {}
    current = _dashboard_float(state.state, None)
    if current is None:
        raise ValueError("invalid_dashboard_slider_state")
    step = _dashboard_float(
        _dashboard_first_attribute(
            attributes,
            "step",
            "native_step",
            "native_step_value",
        ),
        1.0,
    )
    if step is None or step <= 0:
        step = 1.0
    next_value = current + (step if action == "increment" else -step)
    minimum = _dashboard_float(
        _dashboard_first_attribute(
            attributes,
            "min",
            "native_min",
            "native_min_value",
        ),
        None,
    )
    maximum = _dashboard_float(
        _dashboard_first_attribute(
            attributes,
            "max",
            "native_max",
            "native_max_value",
        ),
        None,
    )
    if minimum is not None:
        next_value = max(next_value, minimum)
    if maximum is not None:
        next_value = min(next_value, maximum)
    await hass.services.async_call(
        entity_id.split(".", 1)[0],
        "set_value",
        {"entity_id": entity_id, "value": next_value},
        blocking=True,
    )


async def _async_adjust_dashboard_choice(
    hass: HomeAssistant,
    entity_id: str,
    action: str | None,
    *,
    option: str | None = None,
) -> None:
    """Select an option or cycle a select/input_select entity."""

    if option is not None:
        if not option:
            raise ValueError("invalid_dashboard_choice_action")
        domain = entity_id.split(".", 1)[0]
        await hass.services.async_call(
            domain,
            "select_option",
            {"entity_id": entity_id, "option": option},
            blocking=True,
        )
        return
    if not action:
        raise ValueError("invalid_dashboard_choice_action")
    domain = entity_id.split(".", 1)[0]
    if action not in _DASHBOARD_CHOICE_ACTIONS:
        raise ValueError("invalid_dashboard_choice_action")
    await hass.services.async_call(
        domain,
        f"select_{action}",
        {"entity_id": entity_id, "cycle": True},
        blocking=True,
    )


def _dashboard_selected_entity_action(action_id: str) -> tuple[str, str | None]:
    """Split a selected entity action such as `input_number.temp:increment`."""

    raw = str(action_id or "").strip()
    normalized = raw.lower()
    if ":" not in raw:
        return normalized, None
    entity_id, action = raw.rsplit(":", 1)
    normalized_action = action.lower()
    if normalized_action in _DASHBOARD_SLIDER_ACTIONS | _DASHBOARD_CHOICE_ACTIONS:
        return entity_id.lower(), normalized_action
    return normalized, None


def _dashboard_collection_key(kind: str) -> str:
    return {
        "button": "buttons",
        "choice": "choices",
        "entity": "entities",
        "image": "images",
        "slider": "sliders",
        "switch": "switches",
    }[kind]


def _dashboard_action_state(
    hass: HomeAssistant,
    action: dict[str, Any],
    dashboard: dict[str, Any],
) -> Any | None:
    entity_id = _dashboard_state_entity_id(action, dashboard)
    return hass.states.get(entity_id) if entity_id else None


def _dashboard_state_entity_id(
    action: dict[str, Any],
    dashboard: dict[str, Any],
) -> str | None:
    for source in (
        dashboard.get("state_entity_id"),
        dashboard.get("entity_id"),
        (action.get("target") or {}).get("entity_id")
        if isinstance(action.get("target"), dict)
        else None,
        (action.get("data") or {}).get("entity_id")
        if isinstance(action.get("data"), dict)
        else None,
    ):
        entity_id = _first_entity_id(source)
        if entity_id:
            return entity_id
    return None


def _dashboard_image_source(
    hass: HomeAssistant,
    action: dict[str, Any],
    dashboard: dict[str, Any],
) -> str | None:
    source = dashboard.get("source")
    if isinstance(source, str) and source.strip():
        return source.strip()
    state = _dashboard_action_state(hass, action, dashboard)
    if state is not None and isinstance(state.state, str) and state.state.strip():
        return state.state.strip()
    return None


def _first_entity_id(value: Any) -> str | None:
    if isinstance(value, str) and "." in value:
        return value.strip()
    if isinstance(value, list):
        for item in value:
            entity_id = _first_entity_id(item)
            if entity_id:
                return entity_id
    return None


def _dashboard_state_is_on(value: Any) -> bool:
    return str(value or "").lower() in _DASHBOARD_ON_STATES


def _dashboard_state_label(value: Any, language: str = "en") -> str:
    raw = str(value or "unknown").lower()
    labels = _DASHBOARD_STATE_LABELS_BY_LANGUAGE.get(language, _DASHBOARD_STATE_LABELS_EN)
    return labels.get(raw, str(value or "unknown"))


def _entity_name(
    entity_id: str,
    state: Any | None,
    *,
    display: str = DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME,
    custom_name: str = "",
) -> str:
    if display == DASHBOARD_ENTITY_NAME_DISPLAY_CUSTOM and custom_name.strip():
        return _dashboard_text(custom_name, entity_id, 80)
    if display == DASHBOARD_ENTITY_NAME_DISPLAY_ENTITY_ID:
        return _dashboard_text(entity_id, entity_id, 80)
    attributes = getattr(state, "attributes", None)
    if isinstance(attributes, dict):
        name = attributes.get("friendly_name")
        if isinstance(name, str) and name.strip():
            return _dashboard_text(name, entity_id, 80)
    object_id = entity_id.split(".", 1)[-1].replace("_", " ")
    return _dashboard_text(object_id.title(), entity_id, 80)


def _entity_secondary_label(
    state: Any | None,
    entity_id: str,
    secondary_info: str,
    *,
    language: str = "en",
    fallback: str | None = None,
) -> str:
    if fallback is None:
        fallback = _dashboard_state_label("unknown", language)
    if secondary_info == DASHBOARD_ENTITY_SECONDARY_INFO_NONE:
        return ""
    if secondary_info == DASHBOARD_ENTITY_SECONDARY_INFO_ENTITY_ID:
        return _dashboard_text(entity_id, entity_id, 60)
    if secondary_info == DASHBOARD_ENTITY_SECONDARY_INFO_LAST_CHANGED:
        return _state_time_label(state, "last_changed")
    if secondary_info == DASHBOARD_ENTITY_SECONDARY_INFO_LAST_UPDATED:
        return _state_time_label(state, "last_updated")
    return _entity_state_label(
        state,
        entity_id=entity_id,
        fallback=fallback,
        language=language,
    )


def _button_secondary_label(
    state: Any | None,
    entity_id: str,
    secondary_info: str,
    *,
    language: str = "en",
) -> str:
    if secondary_info in {
        DASHBOARD_ENTITY_SECONDARY_INFO_STATE,
        DASHBOARD_ENTITY_SECONDARY_INFO_LAST_CHANGED,
        DASHBOARD_ENTITY_SECONDARY_INFO_LAST_UPDATED,
        DASHBOARD_ENTITY_SECONDARY_INFO_NONE,
    }:
        return ""
    return _entity_secondary_label(
        state,
        entity_id,
        secondary_info,
        language=language,
        fallback="",
    )


def _entity_state_label(
    state: Any | None,
    *,
    entity_id: str | None = None,
    language: str = "en",
    fallback: str = "",
) -> str:
    if not fallback:
        fallback = _dashboard_state_label("unknown", language)
    if state is None:
        return "Offline"
    attributes = getattr(state, "attributes", None)
    if not isinstance(attributes, dict):
        attributes = {}
    state_value = str(state.state or "unknown")
    if str(entity_id or getattr(state, "entity_id", "")).startswith("binary_sensor."):
        return _binary_sensor_state_label(
            state_value,
            attributes,
            fallback=fallback,
            language=language,
        )
    label = _dashboard_state_label(state_value, language)
    unit = attributes.get("unit_of_measurement")
    labels = _DASHBOARD_STATE_LABELS_BY_LANGUAGE.get(language, _DASHBOARD_STATE_LABELS_EN)
    if unit and state_value.lower() not in labels:
        label = f"{state_value} {unit}"
    if label == "unknown" and fallback:
        return fallback
    return _dashboard_text(label, fallback, 60)


def _binary_sensor_state_label(
    state_value: str,
    attributes: dict[str, Any],
    *,
    language: str = "en",
    fallback: str,
) -> str:
    raw = state_value.lower()
    if raw in {"unknown", "unavailable"}:
        return _dashboard_state_label(raw, language)
    device_labels = _BINARY_SENSOR_DEVICE_CLASS_LABELS_BY_LANGUAGE.get(
        language,
        _BINARY_SENSOR_DEVICE_CLASS_LABELS_EN,
    )
    labels = device_labels.get(
        str(attributes.get("device_class") or "").lower()
    )
    if labels is not None and raw in {"off", "on"}:
        return labels[1] if raw == "on" else labels[0]
    state_labels = _DASHBOARD_STATE_LABELS_BY_LANGUAGE.get(
        language,
        _DASHBOARD_STATE_LABELS_EN,
    )
    return _dashboard_state_label(raw, language) if raw in state_labels else fallback


def _entity_state_color(
    state: Any | None,
    *,
    entity_id: str | None = None,
) -> str | None:
    if state is None:
        return _DASHBOARD_COLOR_WARNING
    attributes = getattr(state, "attributes", None)
    if not isinstance(attributes, dict):
        attributes = {}
    raw = str(state.state or "unknown").lower()
    if str(entity_id or getattr(state, "entity_id", "")).startswith("binary_sensor."):
        return _binary_sensor_state_color(raw, attributes)
    return _raw_state_color(raw)


def _binary_sensor_state_color(
    raw: str,
    attributes: dict[str, Any],
) -> str:
    if raw in {"unknown", "unavailable"}:
        return _DASHBOARD_COLOR_WARNING
    if raw in {"off", "on"}:
        colors = _BINARY_SENSOR_DEVICE_CLASS_COLORS.get(
            str(attributes.get("device_class") or "").lower()
        )
        if colors is not None:
            return colors[1] if raw == "on" else colors[0]
        return _DASHBOARD_COLOR_BAD if raw == "on" else _DASHBOARD_COLOR_GOOD
    return _raw_state_color(raw) or _DASHBOARD_COLOR_NEUTRAL


def _raw_state_color(raw: str) -> str | None:
    if raw in {"closed", "disarmed", "idle", "locked", "off", "ok", "safe"}:
        return _DASHBOARD_COLOR_GOOD
    if raw in {
        "on",
        "open",
        "problem",
        "triggered",
        "unsafe",
        "unlocked",
        "violated",
    }:
        return _DASHBOARD_COLOR_BAD
    if raw in {"unknown", "unavailable"}:
        return _DASHBOARD_COLOR_WARNING
    return None


def _state_time_label(state: Any | None, attribute: str) -> str:
    value = getattr(state, attribute, None)
    if value is None:
        return ""
    as_local = getattr(dt_util, "as_local", None) if dt_util is not None else None
    display_time = as_local(value) if callable(as_local) else value
    if hasattr(display_time, "strftime"):
        return display_time.strftime("%d.%m. %H:%M")
    return ""


def _dashboard_slider_payload(state: Any | None) -> dict[str, Any]:
    attributes = getattr(state, "attributes", None)
    if not isinstance(attributes, dict):
        attributes = {}
    value = _dashboard_float(getattr(state, "state", None), 0.0) or 0.0
    minimum = _dashboard_float(
        _dashboard_first_attribute(
            attributes,
            "min",
            "native_min",
            "native_min_value",
        ),
        0.0,
    )
    maximum = _dashboard_float(
        _dashboard_first_attribute(
            attributes,
            "max",
            "native_max",
            "native_max_value",
        ),
        100.0,
    )
    step = _dashboard_float(
        _dashboard_first_attribute(
            attributes,
            "step",
            "native_step",
            "native_step_value",
        ),
        1.0,
    )
    return {
        "value": value,
        "min": 0.0 if minimum is None else minimum,
        "max": 100.0 if maximum is None else maximum,
        "step": 1.0 if step is None or step <= 0 else step,
    }


def _dashboard_choice_payload(state: Any | None) -> dict[str, Any]:
    attributes = getattr(state, "attributes", None)
    if not isinstance(attributes, dict):
        attributes = {}
    raw_options = attributes.get("options")
    if not isinstance(raw_options, list):
        raw_options = []
    value = "" if state is None else str(state.state or "")
    return {
        "value": value,
        "options": [
            {
                "label": _dashboard_text(option, "", 80),
                "value": option,
            }
            for option in raw_options
            if isinstance(option, str) and option.strip()
        ][:12],
    }


def _dashboard_float(value: Any, fallback: float | None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _dashboard_first_attribute(attributes: dict[str, Any], *names: str) -> Any | None:
    """Return the first present slider attribute while preserving zero values."""

    for name in names:
        if name in attributes and attributes[name] not in (None, ""):
            return attributes[name]
    return None


def _dashboard_text(value: Any, fallback: str, max_length: int) -> str:
    if isinstance(value, str):
        text = " ".join(value.split())
        if text:
            return text[:max_length]
    return fallback[:max_length]


def _dashboard_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(parsed, 0)


def _finalize_dashboard_page(page: dict[str, Any]) -> dict[str, Any]:
    finalized = {
        "title": page.get("title") or _DASHBOARD_ACTION_PAGE,
    }
    if badges := list(page.get("badges") or []):
        finalized["badges"] = badges
    for key in ("buttons", "choices", "entities", "switches", "sliders", "images"):
        if items := _finalize_dashboard_items(page.get(key)):
            finalized[key] = items
    if isinstance(page.get("weather"), dict):
        finalized["weather"] = page["weather"]
    if page.get("flow"):
        finalized["flow"] = page["flow"]
    return finalized


def _finalize_dashboard_items(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    result = []
    for item in sorted(
        items,
        key=lambda value: (
            _dashboard_int(value.get("_order") if isinstance(value, dict) else None, 1000),
            str(value.get("name") or value.get("entity_id") or value.get("source") or ""),
        ),
    ):
        if not isinstance(item, dict):
            continue
        cleaned = dict(item)
        cleaned.pop("_kind", None)
        cleaned.pop("_order", None)
        cleaned.pop("_page", None)
        result.append(cleaned)
    return result


def _dashboard_page_has_content(page: dict[str, Any]) -> bool:
    return any(
        bool(page.get(key))
        for key in (
            "badges",
            "buttons",
            "choices",
            "entities",
            "switches",
            "sliders",
            "images",
            "weather",
            "flow",
        )
    )


def _alarm_commands_for_state(
    hass: HomeAssistant,
    entity_id: str,
    state: Any,
) -> list[dict[str, Any]]:
    """Return the arming commands supported by the configured alarm entity."""

    if state is None:
        return []
    state_value = str(state.state)
    code_policy = _alarm_code_policy(hass, entity_id, state)
    supported_features = _supported_alarm_features(state)
    if supported_features is None:
        commands = _default_alarm_commands(code_policy)
    else:
        commands = [
            _alarm_command_payload(
                command,
                armed_state,
                name,
                _alarm_arm_command_requires_code(state_value, code_policy),
                code_policy,
            )
            for command, armed_state, name, feature in _ALARM_ARM_COMMANDS
            if supported_features & feature
        ]
    if state_value in {*_ARMED_ALARM_STATES, "arming", "pending", "triggered"}:
        commands = [
            _alarm_command_payload(
                *_ALARM_DISARM_COMMAND,
                code_policy["disarm"],
                code_policy,
            ),
            *commands,
        ]
    return _commands_with_alarmo_readiness(hass, entity_id, state, commands)


def _commands_with_alarmo_readiness(
    hass: HomeAssistant,
    entity_id: str,
    state: Any,
    commands: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Add Alarmo arming readiness when the selected alarm entity exposes it."""

    alarmo_context = _alarmo_context(hass, entity_id)
    if alarmo_context is None:
        return commands
    alarmo_data, alarmo_entity = alarmo_context
    sensor_handler = alarmo_data.get("sensor_handler")
    if (
        sensor_handler is None
        and not _open_sensors_from_alarmo_entity(alarmo_entity)
        and not isinstance(getattr(alarmo_entity, "_ready_to_arm_modes", None), list)
    ):
        return commands

    enriched: list[dict[str, Any]] = []
    for command_payload in commands:
        payload = dict(command_payload)
        target_state = str(payload.get("state") or "")
        if payload.get("command") == "disarm" or target_state == "disarmed":
            payload["ready"] = True
            payload["blocking_sensors"] = []
            payload["blocking_sensor_count"] = 0
            enriched.append(payload)
            continue

        if (
            preflight := _alarmo_command_preflight(
                hass,
                entity_id,
                state,
                str(payload.get("command") or ""),
                for_command=False,
            )
        ) is None:
            payload["ready"] = True
            payload["blocking_sensors"] = []
            payload["blocking_sensor_count"] = 0
        else:
            payload.update(preflight)
        enriched.append(payload)
    return enriched


def _alarmo_command_preflight(
    hass: HomeAssistant,
    entity_id: str,
    state: Any,
    command: str,
    *,
    for_command: bool,
) -> dict[str, Any] | None:
    """Return Alarmo readiness details for one arm command.

    Alarmo's own frontend shows ready/not-ready from the sensor validator. The
    C300X UI uses this for display and preflight checks, while real commands
    still go through Home Assistant so Alarmo can run its normal command path.
    """

    target_state = _ALARM_COMMAND_TARGET_STATES.get(command)
    if target_state is None or target_state == "disarmed":
        return None

    alarmo_context = _alarmo_context(hass, entity_id)
    if alarmo_context is None:
        return None
    alarmo_data, alarmo_entity = alarmo_context
    sensor_handler = alarmo_data.get("sensor_handler")

    ready_from_alarmo = _alarmo_target_ready(alarmo_entity, state, target_state)
    blocking_sensor_map = _alarmo_blocking_sensor_map(
        alarmo_data,
        alarmo_entity,
        sensor_handler,
        state,
        target_state,
        use_delay=for_command
        and _alarmo_uses_exit_delay(alarmo_entity, target_state),
        filter_readiness_sensors=not for_command,
    )
    blocking_sensors = _alarm_blocking_sensor_payloads(hass, blocking_sensor_map)
    if sensor_handler is None and not blocking_sensor_map:
        ready = ready_from_alarmo is not False
    else:
        ready = not blocking_sensor_map
    return {
        "ready": bool(ready),
        "blocking_sensors": blocking_sensors[:_MAX_ALARM_BLOCKING_SENSORS],
        "blocking_sensor_count": len(blocking_sensors),
    }


def _alarm_not_ready_response(
    command: str,
    entity_id: str,
    current_state: str | None,
    preflight: dict[str, Any],
    *,
    check: bool = False,
) -> dict[str, Any]:
    """Return a structured Alarmo block response without treating it as transport failure."""

    response = {
        "ok": False,
        "error": "not_ready_to_arm",
        "command": command,
        "entity_id": entity_id,
        "state": current_state,
        **preflight,
    }
    if check:
        response["check"] = True
    return response


def _alarm_state_unchanged_response(
    command: str,
    entity_id: str,
    current_state: str | None,
    *,
    code: str | None = None,
) -> dict[str, Any]:
    """Return a structured alarm command failure without surfacing a HTTP error."""

    if code:
        return {
            "ok": False,
            "error": "invalid_code",
            "command": command,
            "entity_id": entity_id,
            "state": current_state,
        }
    return {
        "ok": False,
        "error": "alarm_state_unchanged",
        "command": command,
        "entity_id": entity_id,
        "state": current_state,
    }


def _alarm_service_error_response(
    command: str,
    entity_id: str,
    current_state: str | None,
    err: Exception,
) -> dict[str, Any]:
    """Return a structured alarm service error for the C300X UI."""

    message = str(err).strip()
    error = "invalid_code" if _looks_like_invalid_code_error(message) else "alarm_command_rejected"
    response: dict[str, Any] = {
        "ok": False,
        "error": error,
        "command": command,
        "entity_id": entity_id,
        "state": current_state,
    }
    if message:
        response["message"] = message[:160]
    return response


def _looks_like_invalid_code_error(message: str) -> bool:
    """Return true when a service error is most likely a bad alarm code."""

    normalized = message.lower()
    return "code" in normalized and any(
        token in normalized
        for token in ("invalid", "incorrect", "wrong", "bad", "falsch", "ungueltig")
    )


def _alarmo_context(
    hass: HomeAssistant,
    entity_id: str,
) -> tuple[dict[str, Any], Any] | None:
    """Return Alarmo runtime data for the configured alarm entity."""

    hass_data = getattr(hass, "data", None)
    if not isinstance(hass_data, dict):
        return None
    alarmo_data = hass_data.get("alarmo")
    if not isinstance(alarmo_data, dict):
        return None
    entity = _alarmo_entity_for_entity_id(alarmo_data, entity_id)
    if entity is None:
        return None
    return alarmo_data, entity


def _alarmo_target_ready(alarmo_entity: Any, state: Any, target_state: str) -> bool | None:
    """Return Alarmo's ready-to-arm status for one target state."""

    if str(getattr(state, "state", "unknown")) == target_state:
        return True

    ready_modes = getattr(alarmo_entity, "_ready_to_arm_modes", None)
    if not isinstance(ready_modes, list):
        return None
    return target_state in ready_modes


def _alarmo_blocking_sensor_map(
    alarmo_data: dict[str, Any],
    alarmo_entity: Any,
    sensor_handler: Any,
    state: Any,
    target_state: str,
    *,
    use_delay: bool = False,
    filter_readiness_sensors: bool = True,
) -> dict[str, Any]:
    """Return currently blocking Alarmo sensors for one target arm state."""

    if sensor_handler is None or not hasattr(sensor_handler, "validate_arming_event"):
        return _open_sensors_from_alarmo_entity(alarmo_entity)

    area_id = getattr(alarmo_entity, "area_id", None)
    try:
        if area_id:
            open_sensors = _validate_alarmo_area(
                sensor_handler,
                area_id,
                target_state,
                use_delay=use_delay,
            )
            return (
                _filter_alarmo_readiness_sensors(
                    sensor_handler,
                    open_sensors,
                    getattr(state, "state", "unknown"),
                )
                if filter_readiness_sensors
                else open_sensors
            )
        return _master_alarmo_blocking_sensor_map(
            alarmo_data,
            sensor_handler,
            target_state,
            use_delay=use_delay,
            filter_readiness_sensors=filter_readiness_sensors,
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        return _open_sensors_from_alarmo_entity(alarmo_entity)


def _master_alarmo_blocking_sensor_map(
    alarmo_data: dict[str, Any],
    sensor_handler: Any,
    target_state: str,
    *,
    use_delay: bool,
    filter_readiness_sensors: bool,
) -> dict[str, Any]:
    """Return blocking sensors across Alarmo areas for a master alarm entity."""

    areas = alarmo_data.get("areas")
    if not isinstance(areas, dict):
        return {}

    blocking_sensors: dict[str, Any] = {}
    for area_entity in areas.values():
        if getattr(area_entity, "state", None) == target_state:
            continue
        area_id = getattr(area_entity, "area_id", None)
        if not area_id:
            continue
        open_sensors = _validate_alarmo_area(
            sensor_handler,
            area_id,
            target_state,
            use_delay=use_delay,
        )
        blocking_sensors.update(
            _filter_alarmo_readiness_sensors(
                sensor_handler,
                open_sensors,
                getattr(area_entity, "state", "unknown"),
            )
            if filter_readiness_sensors
            else open_sensors
        )
    return blocking_sensors


def _validate_alarmo_area(
    sensor_handler: Any,
    area_id: str,
    target_state: str,
    *,
    use_delay: bool = False,
) -> dict[str, Any]:
    """Call Alarmo's sensor validation and return its blocking sensor map."""

    open_sensors, _bypassed_sensors = sensor_handler.validate_arming_event(
        area_id,
        target_state,
        use_delay=use_delay,
    )
    return open_sensors if isinstance(open_sensors, dict) else {}


def _alarmo_uses_exit_delay(alarmo_entity: Any, target_state: str) -> bool:
    """Return whether Alarmo will validate this command in the arming state."""

    config = getattr(alarmo_entity, "_config", None)
    if not isinstance(config, dict):
        return False
    modes = config.get("modes")
    if not isinstance(modes, dict):
        return False
    mode_config = modes.get(target_state)
    if not isinstance(mode_config, dict):
        return False
    try:
        return int(mode_config.get("exit_time") or 0) > 0
    except (TypeError, ValueError):
        return False


def _filter_alarmo_readiness_sensors(
    sensor_handler: Any,
    open_sensors: dict[str, Any],
    state_value: Any,
) -> dict[str, Any]:
    """Mirror Alarmo's ready-to-arm rule that ignores motion sensors while disarmed."""

    if str(state_value) != "disarmed":
        return open_sensors

    sensor_config = getattr(sensor_handler, "_config", None)
    if not isinstance(sensor_config, dict):
        return open_sensors
    return {
        entity_id: sensor_state
        for entity_id, sensor_state in open_sensors.items()
        if sensor_config.get(entity_id, {}).get("type") != "motion"
    }


def _open_sensors_from_alarmo_entity(alarmo_entity: Any) -> dict[str, Any]:
    """Return Alarmo's last recorded open sensors, if present."""

    open_sensors = getattr(alarmo_entity, "open_sensors", None)
    if isinstance(open_sensors, dict):
        return open_sensors
    raw_open_sensors = getattr(alarmo_entity, "_open_sensors", None)
    return raw_open_sensors if isinstance(raw_open_sensors, dict) else {}


def _alarm_blocking_sensor_payloads(
    hass: HomeAssistant,
    open_sensors: dict[str, Any],
) -> list[dict[str, str]]:
    """Return display-safe blocking sensor data."""

    payloads: list[dict[str, str]] = []
    for entity_id, sensor_state in open_sensors.items():
        entity_id_text = str(entity_id)
        if entity_id_text == "group_id":
            continue
        sensor = hass.states.get(entity_id_text)
        attributes = getattr(sensor, "attributes", None)
        friendly_name = (
            attributes.get("friendly_name")
            if isinstance(attributes, dict)
            else None
        )
        payloads.append(
            {
                "entity_id": entity_id_text,
                "name": str(friendly_name or entity_id_text),
                "state": str(sensor_state or getattr(sensor, "state", "unknown")),
            }
        )
    return payloads


def _default_alarm_commands(code_policy: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a broad fallback for tests and entities without feature metadata."""

    return [
        _alarm_command_payload(
            command,
            armed_state,
            name,
            _alarm_arm_command_requires_code("disarmed", code_policy),
            code_policy,
        )
        for command, armed_state, name, _feature in _ALARM_ARM_COMMANDS
    ]


def _alarm_command_payload(
    command: str,
    state: str,
    name: str,
    code_required: bool,
    code_policy: dict[str, Any],
) -> dict[str, Any]:
    """Return one display alarm command with code metadata."""

    payload: dict[str, Any] = {
        "command": command,
        "state": state,
        "name": name,
        "code_required": bool(code_required),
    }
    code_format = code_policy.get("code_format")
    if code_format:
        payload["code_format"] = code_format
    return payload


def _alarm_delay_payload(
    hass: HomeAssistant,
    entity_id: str,
    state: Any,
) -> dict[str, int]:
    """Return a compact arming/pending countdown payload for the device UI."""

    if state is None or str(getattr(state, "state", "unknown")) not in {
        "arming",
        "pending",
    }:
        return {}

    remaining = _alarmo_delay_remaining(hass, entity_id)
    if remaining is None:
        remaining = _state_delay_remaining(state)
    if remaining is None or remaining <= 0:
        return {}
    return {"delay_remaining": remaining}


def _alarm_sensor_payload(
    hass: HomeAssistant,
    entity_id: str,
    state: Any,
) -> dict[str, Any]:
    """Return current Alarmo sensor feedback for triggered or blocked states."""

    if state is None:
        return {}
    attributes = getattr(state, "attributes", None)
    open_sensors = (
        attributes.get("open_sensors")
        if isinstance(attributes, dict)
        else None
    )
    if not isinstance(open_sensors, dict):
        alarmo_context = _alarmo_context(hass, entity_id)
        if alarmo_context is not None:
            _alarmo_data, alarmo_entity = alarmo_context
            open_sensors = _open_sensors_from_alarmo_entity(alarmo_entity)
    if not isinstance(open_sensors, dict) or not open_sensors:
        return {}
    sensor_payloads = _alarm_blocking_sensor_payloads(hass, open_sensors)
    return {
        "open_sensors": sensor_payloads[:_MAX_ALARM_BLOCKING_SENSORS],
        "open_sensor_count": len(sensor_payloads),
    }


def _alarmo_delay_remaining(hass: HomeAssistant, entity_id: str) -> int | None:
    """Return Alarmo's live delay countdown if the runtime entity exposes it."""

    alarmo_context = _alarmo_context(hass, entity_id)
    if alarmo_context is None:
        return None
    _alarmo_data, alarmo_entity = alarmo_context
    expiration = getattr(alarmo_entity, "expiration", None)
    if expiration is None:
        return None
    return _seconds_until(expiration)


def _state_delay_remaining(state: Any) -> int | None:
    """Return delay seconds from generic state attributes without polling."""

    attributes = getattr(state, "attributes", None)
    if not isinstance(attributes, dict):
        return None
    try:
        delay = int(attributes.get("delay", 0) or 0)
    except (TypeError, ValueError):
        return None
    if delay <= 0:
        return None

    last_changed = getattr(state, "last_changed", None)
    if last_changed is None:
        return delay
    elapsed = _seconds_since(last_changed)
    if elapsed is None:
        return delay
    return max(0, delay - elapsed)


def _seconds_until(target: Any) -> int | None:
    """Return whole seconds until a datetime-like value."""

    if not hasattr(target, "__sub__"):
        return None
    now = _utcnow()
    try:
        if getattr(target, "tzinfo", None) is None:
            now = now.replace(tzinfo=None)
        delta = target - now
    except TypeError:
        return None
    return max(0, int(delta.total_seconds() + 0.999))


def _seconds_since(start: Any) -> int | None:
    """Return whole seconds since a datetime-like value."""

    if not hasattr(start, "__sub__"):
        return None
    now = _utcnow()
    try:
        if getattr(start, "tzinfo", None) is None:
            now = now.replace(tzinfo=None)
        delta = now - start
    except TypeError:
        return None
    return max(0, int(delta.total_seconds()))


def _utcnow() -> datetime:
    """Return an aware UTC timestamp without requiring Home Assistant in tests."""

    if dt_util is not None:
        return dt_util.utcnow()
    return datetime.now(UTC)


def _alarm_arm_command_requires_code(
    state_value: str,
    code_policy: dict[str, Any],
) -> bool:
    """Return whether an arm command needs a code from the current alarm state."""

    if state_value in _ARMED_ALARM_STATES:
        return bool(code_policy["mode_change"])
    return bool(code_policy["arm"])


def _alarm_code_policy(
    hass: HomeAssistant,
    entity_id: str,
    state: Any,
) -> dict[str, Any]:
    """Return code requirements for arm, mode-change and disarm commands."""

    if (alarmo_policy := _alarmo_code_policy(hass, entity_id)) is not None:
        return alarmo_policy

    attributes = getattr(state, "attributes", None)
    if not isinstance(attributes, dict):
        attributes = {}
    state_value = str(getattr(state, "state", "unknown"))
    code_format = _optional_string(attributes.get(_ALARM_CODE_FORMAT))
    code_arm_required = _optional_bool(attributes.get(_ALARM_CODE_ARM_REQUIRED))
    current_action_requires_code = bool(code_format)
    return {
        "arm": code_arm_required
        if code_arm_required is not None
        else state_value == "disarmed" and current_action_requires_code,
        "mode_change": state_value != "disarmed" and current_action_requires_code,
        "disarm": state_value != "disarmed" and current_action_requires_code,
        "code_format": code_format,
    }


def _alarmo_code_policy(
    hass: HomeAssistant,
    entity_id: str,
) -> dict[str, Any] | None:
    """Return Alarmo's live code policy when the configured entity is Alarmo."""

    hass_data = getattr(hass, "data", None)
    if not isinstance(hass_data, dict):
        return None
    alarmo_data = hass_data.get("alarmo")
    if not isinstance(alarmo_data, dict):
        return None
    entity = _alarmo_entity_for_entity_id(alarmo_data, entity_id)
    if entity is None:
        return None
    config = getattr(entity, "_config", None)
    if not isinstance(config, dict):
        return None

    arm_required = _bool_config(config, _ALARM_CODE_ARM_REQUIRED, True)
    return {
        "arm": arm_required,
        "mode_change": _bool_config(
            config,
            _ALARM_CODE_MODE_CHANGE_REQUIRED,
            arm_required,
        ),
        "disarm": _bool_config(config, _ALARM_CODE_DISARM_REQUIRED, True),
        "code_format": _optional_string(config.get(_ALARM_CODE_FORMAT)),
    }


def _alarmo_entity_for_entity_id(alarmo_data: dict[str, Any], entity_id: str) -> Any | None:
    """Return the Alarmo runtime entity matching a Home Assistant entity id."""

    candidates = [alarmo_data.get("master")]
    areas = alarmo_data.get("areas")
    if isinstance(areas, dict):
        candidates.extend(areas.values())
    for candidate in candidates:
        if getattr(candidate, "entity_id", None) == entity_id:
            return candidate
    if isinstance(areas, dict) and len(areas) == 1:
        # Some Alarmo setups expose the single area through a user-renamed entity
        # id while hass.data still keeps the original runtime entity id.
        return next(iter(areas.values()))
    return None


def _bool_config(config: dict[str, Any], key: str, fallback: bool) -> bool:
    """Return a bool config value using Alarmo's conservative fallback semantics."""

    value = _optional_bool(config.get(key))
    return fallback if value is None else value


def _optional_bool(value: Any) -> bool | None:
    """Return a bool for explicit boolean-like values."""

    if isinstance(value, bool):
        return value
    return None


def _optional_string(value: Any) -> str | None:
    """Return a non-empty string value."""

    if isinstance(value, str) and value:
        return value
    return None


def _supported_alarm_features(state: Any) -> AlarmControlPanelEntityFeature | None:
    attributes = getattr(state, "attributes", None)
    if not isinstance(attributes, dict) or "supported_features" not in attributes:
        return None
    try:
        return AlarmControlPanelEntityFeature(int(attributes["supported_features"]))
    except (TypeError, ValueError):
        return None


def _current_alarm_state(hass: HomeAssistant, entity_id: str) -> str | None:
    state = hass.states.get(entity_id)
    return None if state is None else str(state.state)


async def _async_wait_for_alarm_state(
    hass: HomeAssistant,
    entity_id: str,
    wanted_states: set[str],
) -> bool:
    """Wait briefly for an alarm state transition triggered by a service call."""

    deadline = asyncio.get_running_loop().time() + _ALARM_STATE_CHANGE_TIMEOUT_SECONDS
    while True:
        if _current_alarm_state(hass, entity_id) in wanted_states:
            return True
        if asyncio.get_running_loop().time() >= deadline:
            return False
        await asyncio.sleep(_ALARM_STATE_CHANGE_INTERVAL_SECONDS)


def _target_alarm_states(command: str) -> set[str]:
    """Return states that prove an alarm command was accepted."""

    target = _ALARM_COMMAND_TARGET_STATES.get(command)
    if target is None:
        return set()
    if command.startswith("arm_"):
        return {target, "arming", "pending"}
    return {target}


def _state_active_since(state: Any) -> tuple[str | None, str | None]:
    """Return alarm state activation timestamp and a compact display label."""

    if state is None:
        return None, None
    last_changed = getattr(state, "last_changed", None)
    if last_changed is None:
        return None, None
    as_local = getattr(dt_util, "as_local", None) if dt_util is not None else None
    display_time = as_local(last_changed) if callable(as_local) else last_changed
    active_since = (
        display_time.isoformat()
        if hasattr(display_time, "isoformat")
        else str(display_time)
    )
    active_since_label = (
        f"Seit {display_time.strftime('%d.%m. %H:%M')}"
        if hasattr(display_time, "strftime")
        else f"Seit {active_since}"
    )
    return active_since, active_since_label


def _entity_state(
    hass: HomeAssistant,
    entry: ConfigEntry,
    domain: str,
    key: str,
) -> str | None:
    if er is None:
        return None
    try:
        registry = er.async_get(hass)
    except Exception:  # noqa: BLE001 - tests and early setup may not have a registry
        return None
    entity_id = registry.async_get_entity_id(domain, DOMAIN, f"{entry.entry_id}_{key}")
    if entity_id is None:
        return None
    state = hass.states.get(entity_id)
    return state.state if state is not None else None
