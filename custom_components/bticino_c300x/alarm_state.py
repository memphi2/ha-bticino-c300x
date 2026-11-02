"""Shared alarm state, readiness and code policy for display and commands."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import IntFlag
from typing import TYPE_CHECKING, Any, cast

from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from homeassistant.components.alarm_control_panel.const import (
        AlarmControlPanelEntityFeature,
    )
else:
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


dt_util: Any

try:
    from homeassistant.util import dt as dt_util
except ImportError:  # pragma: no cover - local test stubs
    dt_util = None


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


_ARMED_ALARM_STATES = frozenset(_ALARM_COMMAND_TARGET_STATES.values()) - {"disarmed"}


_ALARM_CODE_ARM_REQUIRED = "code_arm_required"


_ALARM_CODE_MODE_CHANGE_REQUIRED = "code_mode_change_required"


_ALARM_CODE_DISARM_REQUIRED = "code_disarm_required"


_ALARM_CODE_FORMAT = "code_format"


_ALARM_DISARM_COMMAND = ("disarm", "disarmed", "Aus")


_MAX_ALARM_BLOCKING_SENSORS = 8


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
        use_delay=for_command and _alarmo_uses_exit_delay(alarmo_entity, target_state),
        filter_readiness_sensors=not for_command,
    )
    blocking_sensors = _alarm_blocking_sensor_payloads(hass, blocking_sensor_map)
    if sensor_handler is None and not blocking_sensors:
        ready = ready_from_alarmo is not False
    else:
        ready = not blocking_sensors
    return {
        "ready": bool(ready),
        "blocking_sensors": blocking_sensors[:_MAX_ALARM_BLOCKING_SENSORS],
        "blocking_sensor_count": len(blocking_sensors),
    }


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


def _alarmo_target_ready(
    alarmo_entity: Any, state: Any, target_state: str
) -> bool | None:
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
    except AttributeError, KeyError, TypeError, ValueError:
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
    except TypeError, ValueError:
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
        if _alarmo_sensor_is_currently_closed(entity_id_text, sensor):
            continue
        attributes = getattr(sensor, "attributes", None)
        friendly_name = (
            attributes.get("friendly_name") if isinstance(attributes, dict) else None
        )
        payloads.append(
            {
                "entity_id": entity_id_text,
                "name": str(friendly_name or entity_id_text),
                "state": str(sensor_state or getattr(sensor, "state", "unknown")),
            }
        )
    return payloads


def _alarmo_sensor_is_currently_closed(entity_id: str, sensor: Any) -> bool:
    """Return whether a stale Alarmo blocker is closed in current HA state."""

    if entity_id.split(".", 1)[0] != "binary_sensor":
        return False
    return str(getattr(sensor, "state", "") or "").lower() in {"off", "closed"}


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
        attributes.get("open_sensors") if isinstance(attributes, dict) else None
    )
    if not isinstance(open_sensors, dict):
        alarmo_context = _alarmo_context(hass, entity_id)
        if alarmo_context is not None:
            _alarmo_data, alarmo_entity = alarmo_context
            open_sensors = _open_sensors_from_alarmo_entity(alarmo_entity)
    if not isinstance(open_sensors, dict) or not open_sensors:
        return {}
    sensor_payloads = _alarm_blocking_sensor_payloads(hass, open_sensors)
    if not sensor_payloads:
        return {}
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
    except TypeError, ValueError:
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
        return cast(datetime, dt_util.utcnow())
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


def _alarmo_entity_for_entity_id(
    alarmo_data: dict[str, Any], entity_id: str
) -> Any | None:
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
    except TypeError, ValueError:
        return None


def _current_alarm_state(hass: HomeAssistant, entity_id: str) -> str | None:
    state = hass.states.get(entity_id)
    return None if state is None else str(state.state)


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
