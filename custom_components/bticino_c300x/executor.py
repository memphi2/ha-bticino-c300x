"""User-triggered Home Assistant and device commands."""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.core import HomeAssistant

from .action import (
    alarm_service_for_command,
    normalize_action_id,
)
from .activation_address import stair_light_where_from_entry_values
from .alarm_state import (
    _ALARMO_DOMAIN,
    _alarmo_command_preflight,
    _current_alarm_state,
    _target_alarm_states,
)
from .const import (
    ALARM_DOMAIN,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P,
    DASHBOARD_ENTITY_ANSWERING_MACHINE,
    DASHBOARD_ENTITY_DOOR_UNLOCK,
    DASHBOARD_ENTITY_STAIR_LIGHT,
    EVENT_ACTION_RECEIVED,
)
from .dashboard_config import (
    _DASHBOARD_CHOICE_ACTIONS,
    _DASHBOARD_CHOICE_ENTITY_DOMAINS,
    _DASHBOARD_SLIDER_ACTIONS,
    _DASHBOARD_SLIDER_ENTITY_DOMAINS,
    _DASHBOARD_TOGGLE_ENTITY_DOMAINS,
    _dashboard_first_attribute,
    _dashboard_float,
    configured_actions,
    configured_alarm_entity_id,
    configured_alarm_page_entity_id,
    configured_dashboard_entities,
)
from .dashboard_controls import async_execute_control
from .entry_config import entry_config_value
from .entry_types import BticinoC300XConfigEntry

_ALARMO_FORCE_ARM_MODES = {
    "arm_away": "away",
    "arm_home": "home",
    "arm_night": "night",
    "arm_custom_bypass": "custom",
    "arm_vacation": "vacation",
}


_ALARM_STATE_CHANGE_TIMEOUT_SECONDS = 5.0


_ALARM_STATE_CHANGE_INTERVAL_SECONDS = 0.2


async def async_execute_action(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
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
    entry: BticinoC300XConfigEntry,
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
        return _alarm_not_ready_response(
            command, alarm_entity_id, current_state, preflight
        )

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
    entry: BticinoC300XConfigEntry,
    address: str | None = None,
) -> dict[str, Any]:
    """Activate the staircase light through the configured agent."""

    target_address = address or stair_light_where_from_entry_values(
        entry_config_value(entry, CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P, ""),
        entry_config_value(entry, CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N, ""),
    )
    await entry.runtime_data.api.async_stair_light(target_address)
    return {
        "ok": True,
        "action_id": DASHBOARD_ENTITY_STAIR_LIGHT,
        "address": str(target_address),
    }


async def async_unlock_door(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
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


async def async_execute_dashboard_action(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
    entity_id: str,
    *,
    option: str | None = None,
) -> dict[str, Any]:
    """Execute a dashboard-compatible c300x action id."""

    from .display_notifications import NOTIFICATION_PREFIX, async_notification_action

    if entity_id.startswith(NOTIFICATION_PREFIX):
        return await async_notification_action(hass, entry, entity_id[len(NOTIFICATION_PREFIX):], option)

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


async def _async_execute_dashboard_entity(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
    entity_id: str,
    action: str | None,
    *,
    option: str | None = None,
) -> dict[str, Any]:
    """Execute the default action for a directly selected dashboard entity."""

    domain = entity_id.split(".", 1)[0]
    legacy_actions = (
        _DASHBOARD_SLIDER_ACTIONS if domain in _DASHBOARD_SLIDER_ENTITY_DOMAINS
        else _DASHBOARD_CHOICE_ACTIONS if domain in _DASHBOARD_CHOICE_ENTITY_DOMAINS
        else set()
    )
    if action in {"increment", "decrement", "next", "previous"} and action not in legacy_actions:
        raise ValueError("unsupported_dashboard_control")
    if action and action not in {"increment", "decrement", "next", "previous"}:
        await async_execute_control(hass, entity_id, action, option)
    elif domain in _DASHBOARD_TOGGLE_ENTITY_DOMAINS:
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
    if entity_id and normalized_action:
        return entity_id.lower(), normalized_action
    return normalized, None


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
    error = (
        "invalid_code"
        if _looks_like_invalid_code_error(message)
        else "alarm_command_rejected"
    )
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
