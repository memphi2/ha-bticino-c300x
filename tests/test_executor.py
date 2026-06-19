from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

if "homeassistant.config_entries" not in sys.modules:
    homeassistant = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    core = types.ModuleType("homeassistant.core")

    class ConfigEntry:  # pragma: no cover - import-time stub only
        pass

    class HomeAssistant:  # pragma: no cover - import-time stub only
        pass

    config_entries.ConfigEntry = ConfigEntry
    core.HomeAssistant = HomeAssistant
    core.callback = lambda func: func
    sys.modules.setdefault("homeassistant", homeassistant)
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core
else:
    core = sys.modules.setdefault(
        "homeassistant.core",
        types.ModuleType("homeassistant.core"),
    )
    if not hasattr(core, "callback"):
        core.callback = lambda func: func

helpers = sys.modules.setdefault(
    "homeassistant.helpers",
    types.ModuleType("homeassistant.helpers"),
)
config_validation = sys.modules.setdefault(
    "homeassistant.helpers.config_validation",
    types.ModuleType("homeassistant.helpers.config_validation"),
)
dispatcher = sys.modules.setdefault(
    "homeassistant.helpers.dispatcher",
    types.ModuleType("homeassistant.helpers.dispatcher"),
)
entity = sys.modules.setdefault(
    "homeassistant.helpers.entity",
    types.ModuleType("homeassistant.helpers.entity"),
)

if not hasattr(dispatcher, "async_dispatcher_connect"):
    dispatcher.async_dispatcher_connect = lambda *args, **kwargs: lambda: None
if not hasattr(config_validation, "config_entry_only_config_schema"):
    config_validation.config_entry_only_config_schema = lambda *_args, **_kwargs: object()

if not hasattr(entity, "Entity"):

    class Entity:  # pragma: no cover - import-time stub only
        pass

    class DeviceInfo(dict):  # pragma: no cover - import-time stub only
        pass

    entity.Entity = Entity
    entity.DeviceInfo = DeviceInfo

helpers.config_validation = config_validation
helpers.dispatcher = dispatcher
helpers.entity = entity

from custom_components.bticino_c300x.const import (  # noqa: E402
    CONF_ACTIONS,
    CONF_ALARM_ENTITY_ID,
    CONF_DASHBOARD_ENTITIES,
    CONF_DASHBOARD_ENTITY_NAME_DISPLAY,
    CONF_DASHBOARD_ENTITY_SECONDARY_INFO,
    CONF_DASHBOARD_PREVENT_RETURN,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_ADDRESS,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P,
    CONF_DEVICE_UI_ENABLED,
    CONF_WEATHER_ENTITY_ID,
    DASHBOARD_ENTITY_DOOR_UNLOCK,
)
from custom_components.bticino_c300x.executor import (  # noqa: E402
    async_dashboard_payload,
    async_execute_action,
    async_execute_alarm_command,
    async_execute_dashboard_action,
    async_status,
    async_trigger_stair_light,
    async_unlock_door,
    configured_actions,
    configured_alarm_entity_id,
    configured_dashboard_entities,
    configured_weather_entity_id,
)


@dataclass(slots=True)
class FakeState:
    state: str
    last_changed: Any = None
    attributes: dict[str, Any] = field(default_factory=dict)
    last_updated: Any = None


@dataclass(slots=True)
class FakeStates:
    values: dict[str, FakeState]

    def get(self, entity_id: str) -> FakeState | None:
        return self.values.get(entity_id)


@dataclass(slots=True)
class FakeServices:
    calls: list[tuple[str, str, dict[str, Any], bool]] = field(default_factory=list)
    targets: list[dict[str, Any] | None] = field(default_factory=list)
    states: FakeStates | None = None
    mutate_alarm_states: bool = True
    error: Exception | None = None

    async def async_call(
        self,
        domain: str,
        service: str,
        data: dict[str, Any],
        blocking: bool,
        target: dict[str, Any] | None = None,
    ) -> None:
        self.calls.append((domain, service, data, blocking))
        self.targets.append(target)
        if self.error is not None:
            raise self.error
        if self.states is None or not self.mutate_alarm_states:
            return
        entity_id = data.get("entity_id")
        state = self.states.get(str(entity_id))
        if state is None:
            return
        if domain == "alarmo" and service == "arm":
            mode = data.get("mode")
            state.state = {
                "away": "armed_away",
                "home": "armed_home",
                "night": "armed_night",
                "custom": "armed_custom_bypass",
                "vacation": "armed_vacation",
            }.get(str(mode), state.state)
            return
        if domain != "alarm_control_panel":
            return
        if service == "alarm_disarm":
            state.state = "disarmed"
        elif service == "alarm_arm_home":
            state.state = "armed_home"
        elif service == "alarm_arm_away":
            state.state = "armed_away"
        elif service == "alarm_arm_night":
            state.state = "armed_night"
        elif service == "alarm_arm_custom_bypass":
            state.state = "armed_custom_bypass"
        elif service == "alarm_arm_vacation":
            state.state = "armed_vacation"


@dataclass(slots=True)
class FakeBus:
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def async_fire(self, event_type: str, event_data: dict[str, Any]) -> None:
        self.events.append((event_type, event_data))


@dataclass(slots=True)
class FakeHass:
    services: FakeServices = field(default_factory=FakeServices)
    bus: FakeBus = field(default_factory=FakeBus)
    states: FakeStates = field(default_factory=lambda: FakeStates({}))
    data: dict[str, Any] = field(default_factory=dict)
    config: Any = field(default_factory=lambda: types.SimpleNamespace(language="de"))

    def __post_init__(self) -> None:
        self.services.states = self.states


@dataclass(slots=True)
class FakeApi:
    stair_light_calls: int = 0
    last_stair_light_address: str | None = None
    unlock_calls: list[str] = field(default_factory=list)

    async def async_stair_light(self, address: str) -> dict[str, bool]:
        self.stair_light_calls += 1
        self.last_stair_light_address = address
        return {"ok": True}

    async def async_unlock_door(self, lock_id: str) -> dict[str, bool]:
        self.unlock_calls.append(lock_id)
        return {"ok": True}


@dataclass(slots=True)
class FakeRuntimeData:
    api: FakeApi = field(default_factory=FakeApi)
    event_state: Any = None
    capabilities: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FakeEntry:
    entry_id: str = "entry-1"
    title: str = "C300X"
    data: dict[str, Any] = field(
        default_factory=lambda: {CONF_DEVICE_UI_ENABLED: True}
    )
    options: dict[str, Any] = field(default_factory=dict)
    runtime_data: FakeRuntimeData = field(default_factory=FakeRuntimeData)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


@dataclass(slots=True)
class FakeAlarmoSensorHandler:
    responses: dict[tuple[str, str], dict[str, str]]
    _config: dict[str, dict[str, str]]

    def validate_arming_event(
        self,
        area_id: str,
        target_state: str,
        **_kwargs: Any,
    ) -> tuple[dict[str, str], list[str]]:
        return self.responses.get((area_id, target_state), {}), []


def test_async_execute_action_calls_allowlisted_service() -> None:
    hass = FakeHass()
    entry = FakeEntry(
        options={
            CONF_ACTIONS: {
                "entry_light": {
                    "domain": "light",
                    "service": "toggle",
                    "data": {"entity_id": "light.entry"},
                    "target": {},
                }
            }
        }
    )

    result = run(async_execute_action(hass, entry, "entry_light"))

    assert result == {"ok": True, "action_id": "entry_light"}
    assert hass.services.calls == [
        ("light", "toggle", {"entity_id": "light.entry"}, False)
    ]
    assert hass.bus.events == [
        ("bticino_c300x_action_received", {"entry_id": "entry-1", "action_id": "entry_light"})
    ]


def test_async_execute_action_forwards_target_only_actions() -> None:
    hass = FakeHass()
    entry = FakeEntry(
        options={
            CONF_ACTIONS: {
                "area_scene": {
                    "domain": "scene",
                    "service": "turn_on",
                    "data": {},
                    "target": {"area_id": "kitchen"},
                }
            }
        }
    )

    result = run(async_execute_action(hass, entry, "area_scene"))

    assert result == {"ok": True, "action_id": "area_scene"}
    assert hass.services.calls == [("scene", "turn_on", {}, False)]
    assert hass.services.targets == [{"area_id": "kitchen"}]


def test_async_execute_dashboard_action_toggles_selected_switch() -> None:
    hass = FakeHass()
    entry = FakeEntry(options={CONF_DASHBOARD_ENTITIES: ["switch.entry"]})

    result = run(async_execute_dashboard_action(hass, entry, "switch.entry"))

    assert result == {"ok": True, "action_id": "switch.entry"}
    assert hass.services.calls == [
        ("switch", "toggle", {"entity_id": "switch.entry"}, True)
    ]


def test_async_execute_dashboard_action_presses_selected_button() -> None:
    hass = FakeHass()
    entry = FakeEntry(options={CONF_DASHBOARD_ENTITIES: ["button.restart"]})

    result = run(async_execute_dashboard_action(hass, entry, "button.restart"))

    assert result == {"ok": True, "action_id": "button.restart"}
    assert hass.services.calls == [
        ("button", "press", {"entity_id": "button.restart"}, True)
    ]


def test_async_execute_dashboard_action_presses_selected_input_button() -> None:
    hass = FakeHass()
    entry = FakeEntry(options={CONF_DASHBOARD_ENTITIES: ["input_button.door"]})

    result = run(async_execute_dashboard_action(hass, entry, "input_button.door"))

    assert result == {"ok": True, "action_id": "input_button.door"}
    assert hass.services.calls == [
        ("input_button", "press", {"entity_id": "input_button.door"}, True)
    ]


def test_async_execute_dashboard_action_adjusts_selected_slider() -> None:
    hass = FakeHass(
        states=FakeStates(
            {
                "input_number.target": FakeState(
                    "18",
                    attributes={"min": 15, "max": 20, "step": 0.5},
                )
            }
        )
    )
    entry = FakeEntry(options={CONF_DASHBOARD_ENTITIES: ["input_number.target"]})

    result = run(
        async_execute_dashboard_action(
            hass,
            entry,
            "input_number.target:increment",
        )
    )

    assert result == {"ok": True, "action_id": "input_number.target"}
    assert hass.services.calls == [
        (
            "input_number",
            "set_value",
            {"entity_id": "input_number.target", "value": 18.5},
            True,
        )
    ]


def test_async_execute_dashboard_action_clamps_zero_minimum_slider() -> None:
    hass = FakeHass(
        states=FakeStates(
            {
                "input_number.target": FakeState(
                    "0",
                    attributes={"min": 0, "max": 20, "step": 1},
                )
            }
        )
    )
    entry = FakeEntry(options={CONF_DASHBOARD_ENTITIES: ["input_number.target"]})

    result = run(
        async_execute_dashboard_action(
            hass,
            entry,
            "input_number.target:decrement",
        )
    )

    assert result == {"ok": True, "action_id": "input_number.target"}
    assert hass.services.calls == [
        (
            "input_number",
            "set_value",
            {"entity_id": "input_number.target", "value": 0.0},
            True,
        )
    ]


def test_async_execute_dashboard_action_selects_selected_option() -> None:
    hass = FakeHass()
    entry = FakeEntry(options={CONF_DASHBOARD_ENTITIES: ["select.mode"]})

    result = run(
        async_execute_dashboard_action(
            hass,
            entry,
            "select.mode",
            option="Home Assistant, manual",
        )
    )

    assert result == {"ok": True, "action_id": "select.mode"}
    assert hass.services.calls == [
        (
            "select",
            "select_option",
            {"entity_id": "select.mode", "option": "Home Assistant, manual"},
            True,
        )
    ]


def test_async_execute_dashboard_action_selects_input_select_option() -> None:
    hass = FakeHass()
    entry = FakeEntry(options={CONF_DASHBOARD_ENTITIES: ["input_select.scene"]})

    result = run(
        async_execute_dashboard_action(
            hass,
            entry,
            "input_select.scene",
            option="Night scene",
        )
    )

    assert result == {"ok": True, "action_id": "input_select.scene"}
    assert hass.services.calls == [
        (
            "input_select",
            "select_option",
            {"entity_id": "input_select.scene", "option": "Night scene"},
            True,
        )
    ]


def test_async_execute_action_rejects_unknown_action() -> None:
    hass = FakeHass()
    entry = FakeEntry(options={CONF_ACTIONS: {}})

    try:
        run(async_execute_action(hass, entry, "missing"))
    except KeyError as err:
        assert err.args == ("missing",)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("missing action should fail")


def test_configured_actions_treats_invalid_map_as_empty() -> None:
    entry = FakeEntry(
        options={
            CONF_ACTIONS: {
                "bad action": {"domain": "light", "service": "toggle"},
            }
        }
    )

    assert configured_actions(entry) == {}


def test_configured_actions_falls_back_to_entry_data() -> None:
    entry = FakeEntry(
        data={
            CONF_ACTIONS: {
                "test_light": {
                    "domain": "light",
                    "service": "toggle",
                }
            }
        },
    )

    assert configured_actions(entry) == {
        "test_light": {
            "domain": "light",
            "service": "toggle",
            "data": {},
            "target": {},
        }
    }


def test_dashboard_payload_uses_entry_data_for_prevent_return() -> None:
    hass = FakeHass()
    entry = FakeEntry(
        data={
            CONF_DEVICE_UI_ENABLED: True,
            CONF_DASHBOARD_PREVENT_RETURN: False,
        },
    )

    result = run(async_dashboard_payload(hass, entry))

    assert result["preventReturnToHomepage"] is False


def test_configured_dashboard_entities_respect_empty_option_overrides() -> None:
    entry = FakeEntry(
        data={
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.old",
            CONF_WEATHER_ENTITY_ID: "weather.old",
            CONF_DASHBOARD_ENTITIES: ["switch.old"],
        },
        options={
            CONF_ALARM_ENTITY_ID: "",
            CONF_WEATHER_ENTITY_ID: "",
            CONF_DASHBOARD_ENTITIES: [],
        },
    )

    assert configured_alarm_entity_id(entry) is None
    assert configured_weather_entity_id(entry) is None
    assert configured_dashboard_entities(entry) == ()


def test_configured_dashboard_entities_normalizes_supported_entities() -> None:
    entry = FakeEntry(
        options={
            CONF_DASHBOARD_ENTITIES: [
                " Switch.Entry ",
                "sensor.temperature",
                "switch.entry",
                "media_player.tv",
                "bad",
            ]
        },
    )

    assert configured_dashboard_entities(entry) == (
        "switch.entry",
        "sensor.temperature",
    )


def test_async_execute_alarm_command_calls_alarm_service() -> None:
    hass = FakeHass(
        states=FakeStates({"alarm_control_panel.home": FakeState("disarmed")})
    )
    entry = FakeEntry(data={CONF_ALARM_ENTITY_ID: "alarm_control_panel.home"})

    result = run(async_execute_alarm_command(hass, entry, "arm_home", "1234"))

    assert result == {
        "ok": True,
        "command": "arm_home",
        "entity_id": "alarm_control_panel.home",
        "state": "armed_home",
    }
    assert hass.services.calls == [
        (
            "alarm_control_panel",
            "alarm_arm_home",
            {"entity_id": "alarm_control_panel.home", "code": "1234"},
            True,
        )
    ]


def test_async_execute_alarm_command_switches_armed_modes_directly() -> None:
    hass = FakeHass(
        states=FakeStates({"alarm_control_panel.home": FakeState("armed_home")})
    )
    entry = FakeEntry(data={CONF_ALARM_ENTITY_ID: "alarm_control_panel.home"})

    result = run(async_execute_alarm_command(hass, entry, "arm_away", None))

    assert result == {
        "ok": True,
        "command": "arm_away",
        "entity_id": "alarm_control_panel.home",
        "state": "armed_away",
    }
    assert hass.services.calls == [
        (
            "alarm_control_panel",
            "alarm_arm_away",
            {"entity_id": "alarm_control_panel.home"},
            True,
        ),
    ]


def test_async_execute_alarm_command_returns_structured_error_when_state_unchanged() -> None:
    hass = FakeHass(
        states=FakeStates({"alarm_control_panel.home": FakeState("disarmed")})
    )
    hass.services.mutate_alarm_states = False
    entry = FakeEntry(data={CONF_ALARM_ENTITY_ID: "alarm_control_panel.home"})

    result = run(async_execute_alarm_command(hass, entry, "arm_away", None))

    assert result == {
        "ok": False,
        "error": "alarm_state_unchanged",
        "command": "arm_away",
        "entity_id": "alarm_control_panel.home",
        "state": "disarmed",
    }
    assert hass.services.calls == [
        (
            "alarm_control_panel",
            "alarm_arm_away",
            {"entity_id": "alarm_control_panel.home"},
            True,
        ),
    ]


def test_async_execute_alarm_command_forces_alarmo_open_sensors() -> None:
    alarmo_entity = types.SimpleNamespace(
        entity_id="alarm_control_panel.alarmo",
        area_id="area-1",
        _config={},
    )
    hass = FakeHass(
        states=FakeStates({"alarm_control_panel.alarmo": FakeState("disarmed")}),
        data={
            "alarmo": {
                "master": None,
                "areas": {"area-1": alarmo_entity},
            }
        },
    )
    entry = FakeEntry(data={CONF_ALARM_ENTITY_ID: "alarm_control_panel.alarmo"})

    result = run(async_execute_alarm_command(hass, entry, "arm_away", None, force=True))

    assert result == {
        "ok": True,
        "command": "arm_away",
        "entity_id": "alarm_control_panel.alarmo",
        "state": "armed_away",
    }
    assert hass.services.calls == [
        (
            "alarmo",
            "arm",
            {
                "entity_id": "alarm_control_panel.alarmo",
                "mode": "away",
                "force": True,
            },
            True,
        ),
    ]


def test_async_execute_alarm_command_returns_alarmo_blockers_before_service_call() -> None:
    alarmo_entity = types.SimpleNamespace(
        entity_id="alarm_control_panel.alarmo",
        area_id="area-1",
        _config={
            "modes": {"armed_away": {"exit_time": 0}},
        },
        _ready_to_arm_modes=["armed_away"],
        open_sensors=None,
    )
    sensor_handler = FakeAlarmoSensorHandler(
        responses={
            ("area-1", "armed_away"): {"binary_sensor.front_door": "open"},
        },
        _config={"binary_sensor.front_door": {"type": "door"}},
    )
    hass = FakeHass(
        states=FakeStates(
            {
                "alarm_control_panel.alarmo": FakeState("disarmed"),
                "binary_sensor.front_door": FakeState(
                    "on",
                    attributes={"friendly_name": "Haustuer"},
                ),
            }
        ),
        data={
            "alarmo": {
                "master": None,
                "areas": {"area-1": alarmo_entity},
                "sensor_handler": sensor_handler,
            }
        },
    )
    hass.services.mutate_alarm_states = False
    entry = FakeEntry(data={CONF_ALARM_ENTITY_ID: "alarm_control_panel.alarmo"})

    result = run(async_execute_alarm_command(hass, entry, "arm_away", None))

    assert result == {
        "ok": False,
        "error": "not_ready_to_arm",
        "command": "arm_away",
        "entity_id": "alarm_control_panel.alarmo",
        "state": "disarmed",
        "ready": False,
        "blocking_sensors": [
            {
                "entity_id": "binary_sensor.front_door",
                "name": "Haustuer",
                "state": "open",
            }
        ],
        "blocking_sensor_count": 1,
    }
    assert hass.services.calls == []


def test_async_execute_alarm_command_returns_invalid_code_error() -> None:
    hass = FakeHass(
        states=FakeStates({"alarm_control_panel.home": FakeState("armed_away")})
    )
    hass.services.error = RuntimeError("Invalid code")
    entry = FakeEntry(data={CONF_ALARM_ENTITY_ID: "alarm_control_panel.home"})

    result = run(async_execute_alarm_command(hass, entry, "disarm", "0000"))

    assert result == {
        "ok": False,
        "error": "invalid_code",
        "command": "disarm",
        "entity_id": "alarm_control_panel.home",
        "state": "armed_away",
        "message": "Invalid code",
    }
    assert hass.services.calls == [
        (
            "alarm_control_panel",
            "alarm_disarm",
            {"entity_id": "alarm_control_panel.home", "code": "0000"},
            True,
        ),
    ]


def test_async_execute_alarm_command_check_only_never_calls_service() -> None:
    alarmo_entity = types.SimpleNamespace(
        entity_id="alarm_control_panel.alarmo",
        area_id="area-1",
        _config={
            "modes": {"armed_night": {"exit_time": 0}},
        },
        _ready_to_arm_modes=[],
        open_sensors=None,
    )
    sensor_handler = FakeAlarmoSensorHandler(
        responses={
            ("area-1", "armed_night"): {"binary_sensor.kitchen": "open"},
        },
        _config={"binary_sensor.kitchen": {"type": "door"}},
    )
    hass = FakeHass(
        states=FakeStates(
            {
                "alarm_control_panel.alarmo": FakeState("disarmed"),
                "binary_sensor.kitchen": FakeState(
                    "on",
                    attributes={"friendly_name": "Kueche"},
                ),
            }
        ),
        data={
            "alarmo": {
                "master": None,
                "areas": {"area-1": alarmo_entity},
                "sensor_handler": sensor_handler,
            }
        },
    )
    entry = FakeEntry(data={CONF_ALARM_ENTITY_ID: "alarm_control_panel.alarmo"})

    result = run(
        async_execute_alarm_command(
            hass,
            entry,
            "arm_night",
            None,
            check=True,
        )
    )

    assert result == {
        "ok": False,
        "check": True,
        "error": "not_ready_to_arm",
        "command": "arm_night",
        "entity_id": "alarm_control_panel.alarmo",
        "state": "disarmed",
        "ready": False,
        "blocking_sensors": [
            {
                "entity_id": "binary_sensor.kitchen",
                "name": "Kueche",
                "state": "open",
            }
        ],
        "blocking_sensor_count": 1,
    }
    assert hass.services.calls == []


def test_async_execute_alarm_command_check_only_ready_never_calls_service() -> None:
    hass = FakeHass(
        states=FakeStates({"alarm_control_panel.home": FakeState("disarmed")})
    )
    entry = FakeEntry(data={CONF_ALARM_ENTITY_ID: "alarm_control_panel.home"})

    result = run(
        async_execute_alarm_command(
            hass,
            entry,
            "arm_home",
            None,
            check=True,
        )
    )

    assert result == {
        "ok": True,
        "check": True,
        "command": "arm_home",
        "entity_id": "alarm_control_panel.home",
        "state": "disarmed",
        "ready": True,
        "blocking_sensors": [],
        "blocking_sensor_count": 0,
    }
    assert hass.services.calls == []


def test_async_execute_alarm_command_disarms_with_code() -> None:
    hass = FakeHass(
        states=FakeStates({"alarm_control_panel.home": FakeState("armed_home")})
    )
    entry = FakeEntry(data={CONF_ALARM_ENTITY_ID: "alarm_control_panel.home"})

    result = run(async_execute_alarm_command(hass, entry, "disarm", "1234"))

    assert result == {
        "ok": True,
        "command": "disarm",
        "entity_id": "alarm_control_panel.home",
        "state": "disarmed",
    }
    assert hass.services.calls == [
        (
            "alarm_control_panel",
            "alarm_disarm",
            {"entity_id": "alarm_control_panel.home", "code": "1234"},
            True,
        ),
    ]


def test_async_status_returns_alarm_state_and_action_ids() -> None:
    hass = FakeHass(
        states=FakeStates(
            {
                "alarm_control_panel.home": FakeState(
                    "armed_home",
                    datetime(2026, 5, 25, 20, 30, tzinfo=UTC),
                )
            }
        )
    )
    entry = FakeEntry(
        data={
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.home",
            CONF_DEVICE_UI_ENABLED: True,
        },
        options={
            CONF_ACTIONS: {
                "b": {"domain": "light", "service": "toggle"},
                "a": {"domain": "scene", "service": "turn_on"},
            }
        },
    )

    result = run(async_status(hass, entry))

    assert result["alarm"] == {
        "entity_id": "alarm_control_panel.home",
        "state": "armed_home",
        "active_since": "2026-05-25T20:30:00+00:00",
        "active_since_label": "Seit 25.05. 20:30",
        "commands": [
            {
                "command": "disarm",
                "state": "disarmed",
                "name": "Aus",
                "code_required": False,
            },
            {
                "command": "arm_home",
                "state": "armed_home",
                "name": "Zuhause",
                "code_required": False,
            },
            {
                "command": "arm_away",
                "state": "armed_away",
                "name": "Abwesend",
                "code_required": False,
            },
            {
                "command": "arm_night",
                "state": "armed_night",
                "name": "Nacht",
                "code_required": False,
            },
            {
                "command": "arm_custom_bypass",
                "state": "armed_custom_bypass",
                "name": "Bypass",
                "code_required": False,
            },
            {
                "command": "arm_vacation",
                "state": "armed_vacation",
                "name": "Urlaub",
                "code_required": False,
            },
        ],
    }
    assert result["alarm_configured"] is True
    assert result["dashboard_available"] is True
    assert result["actions"] == ["a", "b"]


def test_async_status_limits_alarm_commands_to_supported_features() -> None:
    hass = FakeHass(
        states=FakeStates(
            {
                "alarm_control_panel.home": FakeState(
                    "disarmed",
                    attributes={"supported_features": 34},
                )
            }
        )
    )
    entry = FakeEntry(
        data={
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.home",
            CONF_DEVICE_UI_ENABLED: True,
        }
    )

    result = run(async_status(hass, entry))

    assert result["alarm"]["commands"] == [
        {
            "command": "arm_away",
            "state": "armed_away",
            "name": "Abwesend",
            "code_required": False,
        },
        {
            "command": "arm_vacation",
            "state": "armed_vacation",
            "name": "Urlaub",
            "code_required": False,
        },
    ]


def test_async_status_uses_alarmo_code_policy() -> None:
    alarmo_entity = types.SimpleNamespace(
        entity_id="alarm_control_panel.alarmo",
        _config={
            "code_arm_required": False,
            "code_mode_change_required": False,
            "code_disarm_required": True,
            "code_format": "number",
        },
    )
    hass = FakeHass(
        states=FakeStates(
            {
                "alarm_control_panel.alarmo": FakeState(
                    "armed_home",
                    attributes={"supported_features": 47},
                )
            }
        ),
        data={"alarmo": {"master": alarmo_entity, "areas": {}}},
    )
    entry = FakeEntry(
        data={
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.alarmo",
            CONF_DEVICE_UI_ENABLED: True,
        }
    )

    result = run(async_status(hass, entry))

    assert result["alarm"]["commands"] == [
        {
            "command": "disarm",
            "state": "disarmed",
            "name": "Aus",
            "code_required": True,
            "code_format": "number",
        },
        {
            "command": "arm_home",
            "state": "armed_home",
            "name": "Zuhause",
            "code_required": False,
            "code_format": "number",
        },
        {
            "command": "arm_away",
            "state": "armed_away",
            "name": "Abwesend",
            "code_required": False,
            "code_format": "number",
        },
        {
            "command": "arm_night",
            "state": "armed_night",
            "name": "Nacht",
            "code_required": False,
            "code_format": "number",
        },
        {
            "command": "arm_vacation",
            "state": "armed_vacation",
            "name": "Urlaub",
            "code_required": False,
            "code_format": "number",
        },
    ]


def test_async_status_uses_alarmo_ready_modes_and_open_sensors() -> None:
    alarmo_entity = types.SimpleNamespace(
        entity_id="alarm_control_panel.alarmo",
        area_id="area-1",
        _config={
            "code_arm_required": False,
            "code_mode_change_required": False,
            "code_disarm_required": False,
        },
        _ready_to_arm_modes=["armed_home", "armed_away"],
        open_sensors=None,
    )
    sensor_handler = FakeAlarmoSensorHandler(
        responses={
            (
                "area-1",
                "armed_away",
            ): {
                "binary_sensor.front_door": "open",
                "binary_sensor.hall_motion": "open",
            },
            ("area-1", "armed_night"): {"binary_sensor.front_door": "open"},
        },
        _config={
            "binary_sensor.front_door": {"type": "door"},
            "binary_sensor.hall_motion": {"type": "motion"},
        },
    )
    hass = FakeHass(
        states=FakeStates(
            {
                "alarm_control_panel.alarmo": FakeState(
                    "disarmed",
                    attributes={"supported_features": 7},
                ),
                "binary_sensor.front_door": FakeState(
                    "on",
                    attributes={"friendly_name": "Haustuer"},
                ),
                "binary_sensor.hall_motion": FakeState(
                    "on",
                    attributes={"friendly_name": "Bewegung Diele"},
                ),
            }
        ),
        data={
            "alarmo": {
                "master": None,
                "areas": {"area-1": alarmo_entity},
                "sensor_handler": sensor_handler,
            }
        },
    )
    entry = FakeEntry(
        data={
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.alarmo",
            CONF_DEVICE_UI_ENABLED: True,
        }
    )

    result = run(async_status(hass, entry))

    commands = {
        command["command"]: command for command in result["alarm"]["commands"]
    }
    assert commands["arm_home"]["ready"] is True
    assert commands["arm_home"]["blocking_sensors"] == []
    assert commands["arm_away"]["ready"] is False
    assert commands["arm_away"]["blocking_sensor_count"] == 1
    assert commands["arm_away"]["blocking_sensors"] == [
        {
            "entity_id": "binary_sensor.front_door",
            "name": "Haustuer",
            "state": "open",
        }
    ]
    assert commands["arm_night"]["ready"] is False


def test_async_status_includes_alarm_delay_remaining() -> None:
    hass = FakeHass(
        states=FakeStates(
            {
                "alarm_control_panel.home": FakeState(
                    "arming",
                    attributes={"delay": 30},
                ),
            }
        )
    )
    entry = FakeEntry(
        data={
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.home",
            CONF_DEVICE_UI_ENABLED: True,
        }
    )

    result = run(async_status(hass, entry))

    assert result["alarm"]["delay_remaining"] == 30


def test_async_status_includes_current_alarm_open_sensors() -> None:
    hass = FakeHass(
        states=FakeStates(
            {
                "alarm_control_panel.home": FakeState(
                    "triggered",
                    attributes={
                        "open_sensors": {
                            "binary_sensor.window": "open",
                        },
                    },
                ),
                "binary_sensor.window": FakeState(
                    "on",
                    attributes={"friendly_name": "Fenster"},
                ),
            }
        )
    )
    entry = FakeEntry(
        data={
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.home",
            CONF_DEVICE_UI_ENABLED: True,
        }
    )

    result = run(async_status(hass, entry))

    assert result["alarm"]["open_sensor_count"] == 1
    assert result["alarm"]["open_sensors"] == [
        {
            "entity_id": "binary_sensor.window",
            "name": "Fenster",
            "state": "open",
        }
    ]


def test_async_status_keeps_alarmo_ready_modes_without_sensor_handler() -> None:
    alarmo_entity = types.SimpleNamespace(
        entity_id="alarm_control_panel.alarmo",
        area_id="area-1",
        _config={
            "code_arm_required": False,
            "code_mode_change_required": False,
            "code_disarm_required": False,
        },
        _ready_to_arm_modes=["armed_home"],
        open_sensors=None,
    )
    hass = FakeHass(
        states=FakeStates(
            {
                "alarm_control_panel.alarmo": FakeState(
                    "disarmed",
                    attributes={"supported_features": 3},
                ),
            }
        ),
        data={
            "alarmo": {
                "master": None,
                "areas": {"area-1": alarmo_entity},
            }
        },
    )
    entry = FakeEntry(
        data={
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.alarmo",
            CONF_DEVICE_UI_ENABLED: True,
        }
    )

    result = run(async_status(hass, entry))

    commands = {
        command["command"]: command for command in result["alarm"]["commands"]
    }
    assert commands["arm_home"]["ready"] is True
    assert commands["arm_away"]["ready"] is False
    assert commands["arm_away"]["blocking_sensors"] == []


def test_async_status_matches_single_alarmo_area_after_entity_rename() -> None:
    alarmo_entity = types.SimpleNamespace(
        entity_id="alarm_control_panel.original_name",
        area_id="area-1",
        _config={
            "code_arm_required": False,
            "code_mode_change_required": False,
            "code_disarm_required": False,
        },
        _ready_to_arm_modes=["armed_vacation"],
        open_sensors=None,
    )
    sensor_handler = FakeAlarmoSensorHandler(
        responses={
            ("area-1", "armed_away"): {"binary_sensor.front_door": "open"},
            ("area-1", "armed_night"): {"binary_sensor.bedroom_window": "open"},
            ("area-1", "armed_vacation"): {},
        },
        _config={
            "binary_sensor.front_door": {"type": "door"},
            "binary_sensor.bedroom_window": {"type": "window"},
        },
    )
    hass = FakeHass(
        states=FakeStates(
            {
                "alarm_control_panel.alarmo": FakeState(
                    "disarmed",
                    attributes={"supported_features": 38},
                ),
                "binary_sensor.front_door": FakeState(
                    "on",
                    attributes={"friendly_name": "Haustuer"},
                ),
                "binary_sensor.bedroom_window": FakeState(
                    "on",
                    attributes={"friendly_name": "Schlafzimmer"},
                ),
            }
        ),
        data={
            "alarmo": {
                "master": None,
                "areas": {"area-1": alarmo_entity},
                "sensor_handler": sensor_handler,
            }
        },
    )
    entry = FakeEntry(
        data={
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.alarmo",
            CONF_DEVICE_UI_ENABLED: True,
        }
    )

    result = run(async_status(hass, entry))
    commands = {
        command["command"]: command for command in result["alarm"]["commands"]
    }

    assert commands["arm_away"]["ready"] is False
    assert commands["arm_away"]["blocking_sensors"] == [
        {
            "entity_id": "binary_sensor.front_door",
            "name": "Haustuer",
            "state": "open",
        }
    ]
    assert commands["arm_night"]["ready"] is False
    assert commands["arm_night"]["blocking_sensors"] == [
        {
            "entity_id": "binary_sensor.bedroom_window",
            "name": "Schlafzimmer",
            "state": "open",
        }
    ]
    assert commands["arm_vacation"]["ready"] is True
    assert commands["arm_vacation"]["blocking_sensors"] == []


def test_async_status_hides_display_ui_when_disabled() -> None:
    hass = FakeHass(
        states=FakeStates({"alarm_control_panel.home": FakeState("disarmed")})
    )
    entry = FakeEntry(
        data={
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.home",
            CONF_DEVICE_UI_ENABLED: False,
        },
        options={CONF_ACTIONS: {"a": {"domain": "scene", "service": "turn_on"}}},
    )

    result = run(async_status(hass, entry))

    assert result["alarm_configured"] is False
    assert result["dashboard_available"] is False
    assert result["actions"] == []


def test_async_status_marks_dashboard_available_with_weather_entity() -> None:
    hass = FakeHass()
    entry = FakeEntry(
        data={
            CONF_DEVICE_UI_ENABLED: True,
            CONF_WEATHER_ENTITY_ID: "weather.home",
        },
    )

    result = run(async_status(hass, entry))

    assert result["dashboard_available"] is True
    assert result["actions"] == []


def test_async_trigger_stair_light_calls_agent_api() -> None:
    hass = FakeHass()
    entry = FakeEntry()

    result = run(async_trigger_stair_light(hass, entry))

    assert result == {"ok": True, "action_id": "stair_light", "address": "10"}
    assert entry.runtime_data.api.stair_light_calls == 1
    assert entry.runtime_data.api.last_stair_light_address == "10"
    assert hass.bus.events == [
        (
            "bticino_c300x_action_received",
            {"entry_id": "entry-1", "action_id": "stair_light", "address": "10"},
        )
    ]


def test_async_trigger_stair_light_uses_configured_address() -> None:
    hass = FakeHass()
    entry = FakeEntry(data={CONF_DEVICE_ACTIVATION_STAIR_LIGHT_ADDRESS: "20#1"})

    result = run(async_trigger_stair_light(hass, entry))

    assert result == {"ok": True, "action_id": "stair_light", "address": "20#1"}
    assert entry.runtime_data.api.last_stair_light_address == "20#1"


def test_async_trigger_stair_light_uses_configured_p_n_address() -> None:
    hass = FakeHass()
    entry = FakeEntry(
        data={
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P: "02",
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N: "01",
        }
    )

    result = run(async_trigger_stair_light(hass, entry))

    assert result == {"ok": True, "action_id": "stair_light", "address": "21"}
    assert entry.runtime_data.api.last_stair_light_address == "21"


def test_async_trigger_stair_light_uses_option_address() -> None:
    hass = FakeHass()
    entry = FakeEntry(
        data={CONF_DEVICE_ACTIVATION_STAIR_LIGHT_ADDRESS: "20#1"},
        options={CONF_DEVICE_ACTIVATION_STAIR_LIGHT_ADDRESS: "30#1"},
    )

    result = run(async_trigger_stair_light(hass, entry))

    assert result == {"ok": True, "action_id": "stair_light", "address": "30#1"}
    assert entry.runtime_data.api.last_stair_light_address == "30#1"


def test_async_trigger_stair_light_accepts_override_address() -> None:
    hass = FakeHass()
    entry = FakeEntry(data={CONF_DEVICE_ACTIVATION_STAIR_LIGHT_ADDRESS: "20#1"})

    result = run(async_trigger_stair_light(hass, entry, "31"))

    assert result == {"ok": True, "action_id": "stair_light", "address": "31"}
    assert entry.runtime_data.api.last_stair_light_address == "31"


def test_async_unlock_door_calls_agent_api() -> None:
    hass = FakeHass()
    entry = FakeEntry()

    result = run(async_unlock_door(hass, entry, "default"))

    assert result == {
        "ok": True,
        "action_id": DASHBOARD_ENTITY_DOOR_UNLOCK,
        "lock_id": "default",
    }
    assert entry.runtime_data.api.unlock_calls == ["default"]
    assert hass.bus.events == [
        (
            "bticino_c300x_action_received",
            {
                "entry_id": "entry-1",
                "action_id": DASHBOARD_ENTITY_DOOR_UNLOCK,
                "lock_id": "default",
            },
        )
    ]


def test_async_dashboard_payload_uses_main_page_for_status_and_actions_page() -> None:
    hass = FakeHass(
        states=FakeStates({"alarm_control_panel.home": FakeState("disarmed")})
    )
    entry = FakeEntry(
        data={
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.home",
            CONF_DEVICE_UI_ENABLED: True,
        },
        options={
            CONF_ACTIONS: {
                "leave_home": {
                    "domain": "script",
                    "service": "turn_on",
                    "target": {"entity_id": "script.leave_home"},
                }
            }
        },
    )

    result = run(async_dashboard_payload(hass, entry))

    assert result["refreshInterval"] == 0
    assert result["data"]["pages"][0]["title"] == "C300X"
    pages = {page["title"]: page for page in result["data"]["pages"]}
    main_page = pages["C300X"]
    assert len(main_page["badges"]) == 3
    assert main_page["badges"][0] == {"state": "HA\nonline", "color": "#58d68d"}
    assert main_page["badges"][1] == {"state": "Alarm\nAus"}
    assert main_page["badges"][2]["state"].count("\n") == 1
    assert main_page["buttons"] == []
    assert main_page["switches"] == []
    buttons = pages["Home Assistant"]["buttons"]
    assert {
        "domain": "c300x",
        "entity_id": "leave_home",
        "name": "leave_home",
        "state_label": "",
    } in buttons


def test_async_dashboard_payload_includes_configured_weather() -> None:
    hass = FakeHass(
        states=FakeStates(
            {
                "weather.home": FakeState(
                    "sunny",
                    datetime(2026, 5, 29, 10, 30, tzinfo=UTC),
                    {
                        "friendly_name": "Zuhause",
                        "temperature": 22,
                        "temperature_unit": "C",
                        "humidity": 55,
                        "wind_speed": 12,
                        "wind_speed_unit": "km/h",
                    },
                )
            }
        )
    )
    entry = FakeEntry(
        data={
            CONF_DEVICE_UI_ENABLED: True,
            CONF_WEATHER_ENTITY_ID: "weather.home",
        }
    )

    result = run(async_dashboard_payload(hass, entry))

    pages = {page["title"]: page for page in result["data"]["pages"]}
    main_page = pages["C300X"]
    assert main_page["badges"][0] == {"state": "HA\nonline", "color": "#58d68d"}
    assert len(main_page["badges"]) == 2
    assert main_page["badges"][1]["state"].count("\n") == 1
    assert main_page["weather"] == {
        "available": True,
        "title": "Zuhause",
        "condition": "Sonnig",
        "condition_key": "sunny",
        "temperature": "22 C",
        "humidity": "55%",
        "wind": "12 km/h",
        "updated": "10:30",
        "badge": "Sonnig\n22 C",
        "color": "#f1c40f",
    }
    assert main_page["buttons"] == []
    assert main_page["switches"] == []


def test_async_dashboard_payload_builds_dynamic_pages_from_actions() -> None:
    hass = FakeHass(
        states=FakeStates(
            {
                "light.entry": FakeState("on"),
                "sensor.door_image": FakeState("http://example.test/image.jpg"),
            }
        )
    )
    entry = FakeEntry(
        options={
            CONF_ACTIONS: {
                "entry_light": {
                    "domain": "light",
                    "service": "toggle",
                    "target": {"entity_id": "light.entry"},
                    "name": "Entry light",
                    "dashboard": {
                        "page": "Licht",
                        "name": "Diele",
                        "order": 20,
                    },
                },
                "door_image": {
                    "domain": "camera",
                    "service": "snapshot",
                    "dashboard": {
                        "type": "image",
                        "page": "Kamera",
                        "state_entity_id": "sensor.door_image",
                        "width": 240,
                        "height": 135,
                    },
                },
            }
        },
    )

    result = run(async_dashboard_payload(hass, entry))

    pages = {page["title"]: page for page in result["data"]["pages"]}
    assert pages["Licht"]["switches"] == [
        {
            "domain": "c300x",
            "entity_id": "entry_light",
            "name": "Diele",
            "state": True,
            "state_label": "Ein",
        }
    ]
    assert pages["Kamera"]["images"] == [
        {
            "source": "http://example.test/image.jpg",
            "width": 240,
            "height": 135,
            "name": "door_image",
        }
    ]


def test_async_dashboard_payload_includes_selected_dashboard_entities() -> None:
    hass = FakeHass(
        states=FakeStates(
            {
                "switch.entry": FakeState("on", attributes={"friendly_name": "Entry"}),
                "sensor.temperature": FakeState(
                    "21.5",
                    attributes={
                        "friendly_name": "Temperature",
                        "unit_of_measurement": "C",
                    },
                ),
                "binary_sensor.window": FakeState(
                    "on",
                    attributes={
                        "friendly_name": "Window",
                        "device_class": "window",
                    },
                ),
                "button.restart": FakeState(
                    "unknown",
                    attributes={"friendly_name": "Restart"},
                ),
                "input_number.target": FakeState(
                    "18",
                    attributes={
                        "friendly_name": "Target",
                        "min": 15,
                        "max": 23,
                        "step": 0.5,
                        "unit_of_measurement": "C",
                    },
                ),
                "select.forwarding": FakeState(
                    "Home Assistant",
                    attributes={
                        "friendly_name": "Forwarding",
                        "options": ["Smartphone", "Home Assistant", "Blocked"],
                    },
                ),
                "input_select.scene": FakeState(
                    "Night",
                    attributes={
                        "friendly_name": "Scene",
                        "options": ["Day", "Night"],
                    },
                ),
            }
        )
    )
    entry = FakeEntry(
        options={
            CONF_DASHBOARD_ENTITIES: [
                "switch.entry",
                "sensor.temperature",
                "binary_sensor.window",
                "button.restart",
                "input_number.target",
                "select.forwarding",
                "input_select.scene",
            ],
        },
    )

    result = run(async_dashboard_payload(hass, entry))

    pages = {page["title"]: page for page in result["data"]["pages"]}
    page = pages["Home Assistant"]
    assert page["switches"] == [
        {
            "domain": "c300x",
            "entity_id": "switch.entry",
            "name": "Entry",
            "state": True,
            "state_label": "Ein",
        }
    ]
    assert page["entities"] == [
        {
            "domain": "c300x",
            "entity_id": "sensor.temperature",
            "name": "Temperature",
            "state": False,
            "state_label": "21.5 C",
        },
        {
            "domain": "c300x",
            "entity_id": "binary_sensor.window",
            "name": "Window",
            "state": True,
            "state_label": "Offen",
            "color": "#ff6b6b",
        },
    ]
    assert page["buttons"] == [
        {
            "domain": "c300x",
            "entity_id": "button.restart",
            "name": "Restart",
            "state_label": "",
        }
    ]
    assert page["sliders"] == [
        {
            "domain": "c300x",
            "entity_id": "input_number.target",
            "max": 23.0,
            "min": 15.0,
            "name": "Target",
            "state_label": "18 C",
            "step": 0.5,
            "value": 18.0,
        }
    ]
    assert page["choices"] == [
        {
            "domain": "c300x",
            "entity_id": "select.forwarding",
            "name": "Forwarding",
            "options": ["Smartphone", "Home Assistant", "Blocked"],
            "state_label": "Home Assistant",
            "value": "Home Assistant",
        },
        {
            "domain": "c300x",
            "entity_id": "input_select.scene",
            "name": "Scene",
            "options": ["Day", "Night"],
            "state_label": "Night",
            "value": "Night",
        },
    ]


def test_async_dashboard_payload_uses_binary_sensor_device_class_labels() -> None:
    states = {}
    expected_labels = {
        "window": ("Geschlossen", "Offen"),
        "door": ("Geschlossen", "Offen"),
        "motion": ("Keine Bewegung", "Bewegung"),
        "problem": ("OK", "Problem"),
        "moisture": ("Trocken", "Feucht"),
    }
    entities = []
    for device_class in expected_labels:
        off_entity = f"binary_sensor.{device_class}_off"
        on_entity = f"binary_sensor.{device_class}_on"
        states[off_entity] = FakeState(
            "off",
            attributes={
                "friendly_name": f"{device_class} off",
                "device_class": device_class,
            },
        )
        states[on_entity] = FakeState(
            "on",
            attributes={
                "friendly_name": f"{device_class} on",
                "device_class": device_class,
            },
        )
        entities.extend((off_entity, on_entity))

    hass = FakeHass(states=FakeStates(states))
    entry = FakeEntry(options={CONF_DASHBOARD_ENTITIES: entities})

    result = run(async_dashboard_payload(hass, entry))

    page = {page["title"]: page for page in result["data"]["pages"]}[
        "Home Assistant"
    ]
    labels_by_entity = {
        item["entity_id"]: item["state_label"] for item in page["entities"]
    }
    for device_class, labels in expected_labels.items():
        assert labels_by_entity[f"binary_sensor.{device_class}_off"] == labels[0]
        assert labels_by_entity[f"binary_sensor.{device_class}_on"] == labels[1]


def test_async_dashboard_payload_localizes_binary_sensor_labels() -> None:
    expected = {
        "de": ("Geschlossen", "Offen"),
        "en": ("Closed", "Open"),
        "fr": ("Ferme", "Ouvert"),
        "it": ("Chiuso", "Aperto"),
    }
    for language, labels in expected.items():
        hass = FakeHass(
            config=types.SimpleNamespace(language=language),
            states=FakeStates(
                {
                    "binary_sensor.window_off": FakeState(
                        "off",
                        attributes={
                            "friendly_name": "Window closed",
                            "device_class": "window",
                        },
                    ),
                    "binary_sensor.window_on": FakeState(
                        "on",
                        attributes={
                            "friendly_name": "Window open",
                            "device_class": "window",
                        },
                    ),
                }
            ),
        )
        entry = FakeEntry(
            options={
                CONF_DASHBOARD_ENTITIES: [
                    "binary_sensor.window_off",
                    "binary_sensor.window_on",
                ],
            }
        )

        result = run(async_dashboard_payload(hass, entry))

        page = {page["title"]: page for page in result["data"]["pages"]}[
            "Home Assistant"
        ]
        by_entity = {item["entity_id"]: item for item in page["entities"]}
        assert by_entity["binary_sensor.window_off"]["state_label"] == labels[0]
        assert by_entity["binary_sensor.window_off"]["color"] == "#58d68d"
        assert by_entity["binary_sensor.window_on"]["state_label"] == labels[1]
        assert by_entity["binary_sensor.window_on"]["color"] == "#ff6b6b"


def test_async_dashboard_payload_falls_back_to_english_without_matching_language() -> None:
    entry = FakeEntry(options={CONF_DASHBOARD_ENTITIES: ["binary_sensor.safety"]})

    for language in ("", "nl"):
        hass = FakeHass(
            config=types.SimpleNamespace(language=language),
            states=FakeStates(
                {
                    "binary_sensor.safety": FakeState(
                        "on",
                        attributes={
                            "friendly_name": "Safety",
                            "device_class": "safety",
                        },
                    ),
                }
            ),
        )

        result = run(async_dashboard_payload(hass, entry))

        page = {page["title"]: page for page in result["data"]["pages"]}[
            "Home Assistant"
        ]
        assert page["entities"][0]["state_label"] == "Unsafe"
        assert page["entities"][0]["color"] == "#ff6b6b"


def test_async_dashboard_payload_uses_dashboard_entity_display_options() -> None:
    hass = FakeHass(
        states=FakeStates(
            {
                "switch.entry": FakeState("on", attributes={"friendly_name": "Entry"}),
                "sensor.temperature": FakeState(
                    "21.5",
                    attributes={
                        "friendly_name": "Temperature",
                        "unit_of_measurement": "C",
                    },
                ),
                "button.restart": FakeState(
                    "unknown",
                    attributes={"friendly_name": "Restart"},
                ),
                "input_number.target": FakeState(
                    "18",
                    attributes={
                        "friendly_name": "Target",
                        "min": 15,
                        "max": 23,
                        "step": 0.5,
                        "unit_of_measurement": "C",
                    },
                ),
                "select.forwarding": FakeState(
                    "Home Assistant",
                    attributes={
                        "friendly_name": "Forwarding",
                        "options": ["Smartphone", "Home Assistant"],
                    },
                ),
            }
        )
    )
    entry = FakeEntry(
        options={
            CONF_DASHBOARD_ENTITIES: [
                "switch.entry",
                "sensor.temperature",
                "button.restart",
                "input_number.target",
                "select.forwarding",
            ],
            CONF_DASHBOARD_ENTITY_NAME_DISPLAY: "entity_id",
            CONF_DASHBOARD_ENTITY_SECONDARY_INFO: "entity_id",
        },
    )

    result = run(async_dashboard_payload(hass, entry))

    page = {page["title"]: page for page in result["data"]["pages"]}[
        "Home Assistant"
    ]
    assert page["switches"][0]["name"] == "switch.entry"
    assert page["switches"][0]["state_label"] == "switch.entry"
    assert page["entities"][0]["name"] == "sensor.temperature"
    assert page["entities"][0]["state_label"] == "sensor.temperature"
    assert page["buttons"][0]["name"] == "button.restart"
    assert page["buttons"][0]["state_label"] == "button.restart"
    assert page["sliders"][0]["name"] == "input_number.target"
    assert page["sliders"][0]["state_label"] == "input_number.target"
    assert page["choices"][0]["name"] == "select.forwarding"
    assert page["choices"][0]["state_label"] == "select.forwarding"


def test_async_dashboard_payload_can_show_entity_last_changed() -> None:
    changed_at = datetime(2026, 6, 14, 12, 34, tzinfo=UTC)
    hass = FakeHass(
        states=FakeStates(
            {
                "sensor.temperature": FakeState(
                    "21.5",
                    last_changed=changed_at,
                    attributes={"friendly_name": "Temperature"},
                ),
            }
        )
    )
    entry = FakeEntry(
        options={
            CONF_DASHBOARD_ENTITIES: ["sensor.temperature"],
            CONF_DASHBOARD_ENTITY_SECONDARY_INFO: "last_changed",
        },
    )

    result = run(async_dashboard_payload(hass, entry))

    page = {page["title"]: page for page in result["data"]["pages"]}[
        "Home Assistant"
    ]
    assert page["entities"][0]["name"] == "Temperature"
    assert page["entities"][0]["state_label"] == "14.06. 12:34"


def test_async_dashboard_payload_can_hide_entity_secondary_info() -> None:
    hass = FakeHass(
        states=FakeStates(
            {
                "sensor.temperature": FakeState(
                    "21.5",
                    attributes={"friendly_name": "Temperature"},
                ),
            }
        )
    )
    entry = FakeEntry(
        options={
            CONF_DASHBOARD_ENTITIES: ["sensor.temperature"],
            CONF_DASHBOARD_ENTITY_SECONDARY_INFO: "none",
        },
    )

    result = run(async_dashboard_payload(hass, entry))

    page = {page["title"]: page for page in result["data"]["pages"]}[
        "Home Assistant"
    ]
    assert page["entities"][0]["name"] == "Temperature"
    assert page["entities"][0]["state_label"] == ""


def test_async_dashboard_payload_keeps_agent_controls_off_main_page() -> None:
    hass = FakeHass()
    entry = FakeEntry()
    entry.runtime_data.capabilities = {
        "locks": {
            "supported": True,
            "default_id": "default",
            "locks": [{"id": "default", "name": "Main door"}],
        }
    }

    result = run(async_dashboard_payload(hass, entry))

    buttons = result["data"]["pages"][0]["buttons"]
    assert buttons == []
