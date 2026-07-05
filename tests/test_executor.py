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
if not hasattr(config_validation, "ensure_list"):
    config_validation.ensure_list = lambda value: value if isinstance(value, list) else [value]

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
helpers.selector = None
sys.modules.pop("homeassistant.helpers.selector", None)

import custom_components.bticino_c300x.executor as executor_module  # noqa: E402
from custom_components.bticino_c300x.config_flow_dashboard import (  # noqa: E402
    dashboard_entity_display_overrides_from_fields,
)
from custom_components.bticino_c300x.const import (  # noqa: E402
    CONF_ACTIONS,
    CONF_ALARM_ENTITY_ID,
    CONF_ALARM_PAGE_ENTITY_ID,
    CONF_DASHBOARD_ENTITIES,
    CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
    CONF_DASHBOARD_PREVENT_RETURN,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P,
    CONF_DEVICE_UI_ENABLED,
    CONF_WEATHER_ENTITY_ID,
    DASHBOARD_ENTITY_DOOR_UNLOCK,
    DASHBOARD_ENTITY_NAME_DISPLAY_CUSTOM,
    DASHBOARD_ENTITY_NAME_DISPLAY_ENTITY_ID,
    DASHBOARD_ENTITY_SECONDARY_INFO_ENTITY_ID,
    DASHBOARD_ENTITY_SECONDARY_INFO_LAST_CHANGED,
    DASHBOARD_ENTITY_SECONDARY_INFO_LAST_UPDATED,
    DASHBOARD_ENTITY_SECONDARY_INFO_NONE,
    DASHBOARD_ENTITY_SECONDARY_INFO_STATE,
)
from custom_components.bticino_c300x.dashboard_weather import (  # noqa: E402
    _cached_weather_forecast,
    _weather_forecast,
    _weather_forecast_cache,
    _weather_forecast_temperature,
    _weather_forecast_time_label,
    _weather_sun,
    dashboard_weather_payload,
)
from custom_components.bticino_c300x.executor import (  # noqa: E402
    _button_secondary_label,
    _dashboard_choice_payload,
    _dashboard_first_attribute,
    _dashboard_float,
    _dashboard_image_source,
    _dashboard_int,
    _dashboard_slider_payload,
    _dashboard_state_entity_id,
    _dashboard_text,
    _entity_name,
    _entity_secondary_label,
    _entity_state_color,
    _entity_state_label,
    _finalize_dashboard_items,
    _finalize_dashboard_page,
    _first_entity_id,
    _raw_state_color,
    _state_time_label,
    async_dashboard_payload,
    async_execute_action,
    async_execute_alarm_command,
    async_execute_dashboard_action,
    async_status,
    async_trigger_stair_light,
    async_unlock_door,
    configured_actions,
    configured_alarm_entity_id,
    configured_alarm_page_entity_id,
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
    responses: dict[tuple[str, str], Any] = field(default_factory=dict)
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
        return_response: bool = False,
    ) -> Any:
        self.calls.append((domain, service, data, blocking))
        self.targets.append(target)
        if self.error is not None:
            raise self.error
        if return_response:
            return self.responses.get((domain, service), {})
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
    answering_machine_enabled: bool = False

    async def async_stair_light(self, address: str) -> dict[str, bool]:
        self.stair_light_calls += 1
        self.last_stair_light_address = address
        return {"ok": True}

    async def async_unlock_door(self, lock_id: str) -> dict[str, bool]:
        self.unlock_calls.append(lock_id)
        return {"ok": True}

    async def async_answering_machine_status(self) -> dict[str, bool]:
        return {"enabled": self.answering_machine_enabled}

    async def async_set_answering_machine_enabled(
        self,
        enabled: bool,
    ) -> dict[str, bool]:
        self.answering_machine_enabled = enabled
        return {"enabled": enabled}


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


def test_dashboard_entity_name_secondary_label_and_color_helpers() -> None:
    changed = datetime(2026, 6, 21, 14, 30, tzinfo=UTC)
    state = FakeState(
        "on",
        last_changed=changed,
        last_updated=changed,
        attributes={"friendly_name": "Window", "device_class": "window"},
    )

    assert _entity_name("binary_sensor.window", state) == "Window"
    assert (
        _entity_name(
            "binary_sensor.window",
            state,
            display=DASHBOARD_ENTITY_NAME_DISPLAY_CUSTOM,
            custom_name="Kitchen window",
        )
        == "Kitchen window"
    )
    assert (
        _entity_name(
            "binary_sensor.window",
            state,
            display=DASHBOARD_ENTITY_NAME_DISPLAY_ENTITY_ID,
        )
        == "binary_sensor.window"
    )
    assert _entity_name("sensor.outside_temp", None) == "Outside Temp"

    assert (
        _entity_secondary_label(
            state,
            "binary_sensor.window",
            DASHBOARD_ENTITY_SECONDARY_INFO_ENTITY_ID,
        )
        == "binary_sensor.window"
    )
    assert (
        _entity_secondary_label(
            state,
            "binary_sensor.window",
            DASHBOARD_ENTITY_SECONDARY_INFO_LAST_CHANGED,
        )
        == "21.06. 14:30"
    )
    assert (
        _entity_secondary_label(
            state,
            "binary_sensor.window",
            DASHBOARD_ENTITY_SECONDARY_INFO_LAST_UPDATED,
        )
        == "21.06. 14:30"
    )
    assert (
        _entity_secondary_label(
            state,
            "binary_sensor.window",
            DASHBOARD_ENTITY_SECONDARY_INFO_NONE,
        )
        == ""
    )
    assert (
        _button_secondary_label(
            state,
            "button.restart",
            DASHBOARD_ENTITY_SECONDARY_INFO_STATE,
        )
        == ""
    )
    assert (
        _button_secondary_label(
            state,
            "button.restart",
            DASHBOARD_ENTITY_SECONDARY_INFO_ENTITY_ID,
        )
        == "button.restart"
    )

    assert _entity_state_label(None, entity_id="sensor.missing") == "Offline"
    assert (
        _entity_state_label(
            FakeState("21", attributes={"unit_of_measurement": "°C"}),
            entity_id="sensor.temp",
        )
        == "21 °C"
    )
    assert (
        _entity_state_label(
            FakeState("on", attributes={"device_class": "window"}),
            entity_id="binary_sensor.window",
        )
        == "Open"
    )
    assert (
        _entity_state_label(
            FakeState("custom"),
            entity_id="sensor.custom",
            fallback="Fallback",
        )
        == "custom"
    )
    assert (
        _entity_state_label(
            FakeState("unknown"),
            entity_id="sensor.unknown",
            fallback="Fallback",
        )
        == "Unknown"
    )

    assert _entity_state_color(None, entity_id="sensor.missing") == "#f1c40f"
    assert (
        _entity_state_color(
            FakeState("on", attributes={"device_class": "window"}),
            entity_id="binary_sensor.window",
        )
        == "#ff6b6b"
    )
    assert (
        _entity_state_color(
            FakeState("off", attributes={"device_class": "window"}),
            entity_id="binary_sensor.window",
        )
        == "#58d68d"
    )
    assert (
        _entity_state_color(FakeState("unlocked"), entity_id="lock.front_door")
        == "#ff6b6b"
    )


def test_dashboard_payload_normalization_helpers() -> None:
    slider = _dashboard_slider_payload(
        FakeState(
            "5.5",
            attributes={
                "native_min_value": "1",
                "native_max_value": "10",
                "native_step_value": "0",
            },
        )
    )
    assert slider == {"value": 5.5, "min": 1.0, "max": 10.0, "step": 1.0}
    assert _dashboard_slider_payload(None) == {
        "value": 0.0,
        "min": 0.0,
        "max": 100.0,
        "step": 1.0,
    }

    choice = _dashboard_choice_payload(
        FakeState(
            "eco",
            attributes={
                "options": [
                    "eco",
                    "  comfort   mode  ",
                    "",
                    123,
                    *[f"mode-{idx}" for idx in range(20)],
                ]
            },
        )
    )
    assert choice["value"] == "eco"
    assert choice["options"][:2] == [
        {"label": "eco", "value": "eco"},
        {"label": "comfort mode", "value": "  comfort   mode  "},
    ]
    assert len(choice["options"]) == 12

    assert _dashboard_float("bad", 7.0) == 7.0
    assert _dashboard_first_attribute({"min": "", "native_min": 0}, "min", "native_min") == 0
    assert _dashboard_text("  a   b   c  ", "fallback", 80) == "a b c"
    assert _dashboard_text("", "fallback", 4) == "fall"
    assert _dashboard_int("-5", 9) == 0
    assert _dashboard_int("bad", 9) == 9

    finalized_items = _finalize_dashboard_items(
        [
            {"name": "B", "_order": 2, "_kind": "entity", "_page": "main"},
            "bad",
            {"name": "A", "_order": 1, "kind": "image"},
        ]
    )
    assert finalized_items == [
        {"name": "A", "kind": "image"},
        {"name": "B", "kind": "entity"},
    ]
    assert _finalize_dashboard_items("bad") == []

    assert _finalize_dashboard_page(
        {
            "title": "Main",
            "badges": [{"name": "Ready"}],
            "items": finalized_items,
            "weather": {"state": "sunny"},
            "flow": [{"page": "next"}],
        }
    ) == {
        "title": "Main",
        "badges": [{"name": "Ready"}],
        "items": finalized_items,
        "weather": {"state": "sunny"},
        "flow": [{"page": "next"}],
    }
    assert _finalize_dashboard_page({}) == {"title": ""}


def test_dashboard_source_and_state_helpers() -> None:
    changed = datetime(2026, 6, 21, 14, 30, tzinfo=UTC)
    hass = FakeHass(
        states=FakeStates(
            {
                "sensor.image": FakeState("/local/pic.jpg"),
                "sensor.blank": FakeState(""),
            }
        )
    )

    assert (
        _dashboard_state_entity_id(
            {"target": {"entity_id": "sensor.target"}},
            {"entity_id": "sensor.dashboard"},
        )
        == "sensor.dashboard"
    )
    assert (
        _dashboard_state_entity_id(
            {"target": {"entity_id": ["sensor.target"]}},
            {},
        )
        == "sensor.target"
    )
    assert _first_entity_id(["bad", ["sensor.nested"]]) == "sensor.nested"
    assert _first_entity_id({"entity_id": "sensor.dict"}) is None
    assert _first_entity_id(123) is None

    assert (
        _dashboard_image_source(hass, {}, {"entity_id": "sensor.image"})
        == "/local/pic.jpg"
    )
    assert (
        _dashboard_image_source(hass, {}, {"source": " /local/manual.jpg "})
        == "/local/manual.jpg"
    )
    assert _dashboard_image_source(hass, {}, {"entity_id": "sensor.blank"}) is None
    assert _dashboard_image_source(hass, {}, {}) is None

    assert _raw_state_color("closed") == "#58d68d"
    assert _raw_state_color("open") == "#ff6b6b"
    assert _raw_state_color("unavailable") == "#f1c40f"
    assert _raw_state_color("custom") is None

    assert (
        _state_time_label(FakeState("on", last_changed=changed), "last_changed")
        == "21.06. 14:30"
    )
    assert _state_time_label(None, "last_changed") == ""


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


def test_async_execute_dashboard_action_turns_on_selected_scene_and_script() -> None:
    hass = FakeHass()
    entry = FakeEntry(
        options={
            CONF_DASHBOARD_ENTITIES: [
                "scene.evening",
                "script.leave_home",
            ]
        }
    )

    scene_result = run(async_execute_dashboard_action(hass, entry, "scene.evening"))
    script_result = run(
        async_execute_dashboard_action(hass, entry, "script.leave_home")
    )

    assert scene_result == {"ok": True, "action_id": "scene.evening"}
    assert script_result == {"ok": True, "action_id": "script.leave_home"}
    assert hass.services.calls == [
        ("scene", "turn_on", {"entity_id": "scene.evening"}, True),
        ("script", "turn_on", {"entity_id": "script.leave_home"}, True),
    ]


def test_async_execute_dashboard_action_rejects_read_only_entity() -> None:
    hass = FakeHass()
    entry = FakeEntry(options={CONF_DASHBOARD_ENTITIES: ["sensor.temperature"]})

    try:
        run(async_execute_dashboard_action(hass, entry, "sensor.temperature"))
    except ValueError as err:
        assert str(err) == "read_only_dashboard_entity"
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("read-only dashboard entity should fail")


def test_async_execute_dashboard_action_rejects_invalid_slider_action() -> None:
    hass = FakeHass(
        states=FakeStates(
            {
                "input_number.target": FakeState(
                    "18",
                    attributes={"min": 15, "max": 20, "step": 1},
                )
            }
        )
    )
    entry = FakeEntry(options={CONF_DASHBOARD_ENTITIES: ["input_number.target"]})

    try:
        run(async_execute_dashboard_action(hass, entry, "input_number.target"))
    except ValueError as err:
        assert str(err) == "invalid_dashboard_slider_action"
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("invalid slider action should fail")


def test_async_execute_dashboard_action_rejects_unavailable_slider() -> None:
    hass = FakeHass()
    entry = FakeEntry(options={CONF_DASHBOARD_ENTITIES: ["input_number.target"]})

    try:
        run(async_execute_dashboard_action(hass, entry, "input_number.target:increment"))
    except ValueError as err:
        assert str(err) == "dashboard_entity_unavailable"
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("unavailable slider should fail")


def test_async_execute_dashboard_action_rejects_invalid_slider_state() -> None:
    hass = FakeHass(
        states=FakeStates({"input_number.target": FakeState("unknown")})
    )
    entry = FakeEntry(options={CONF_DASHBOARD_ENTITIES: ["input_number.target"]})

    try:
        run(async_execute_dashboard_action(hass, entry, "input_number.target:increment"))
    except ValueError as err:
        assert str(err) == "invalid_dashboard_slider_state"
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("invalid slider state should fail")


def test_async_execute_dashboard_action_cycles_choice_without_exact_option() -> None:
    hass = FakeHass()
    entry = FakeEntry(options={CONF_DASHBOARD_ENTITIES: ["select.mode"]})

    result = run(async_execute_dashboard_action(hass, entry, "select.mode:next"))

    assert result == {"ok": True, "action_id": "select.mode"}
    assert hass.services.calls == [
        ("select", "select_next", {"entity_id": "select.mode", "cycle": True}, True)
    ]


def test_async_execute_dashboard_action_rejects_empty_choice_option() -> None:
    hass = FakeHass()
    entry = FakeEntry(options={CONF_DASHBOARD_ENTITIES: ["select.mode"]})

    try:
        run(async_execute_dashboard_action(hass, entry, "select.mode", option=""))
    except ValueError as err:
        assert str(err) == "invalid_dashboard_choice_action"
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("empty choice option should fail")


def test_async_execute_dashboard_action_toggles_answering_machine() -> None:
    hass = FakeHass()
    api = FakeApi(answering_machine_enabled=False)
    entry = FakeEntry(runtime_data=FakeRuntimeData(api=api))

    result = run(
        async_execute_dashboard_action(
            hass,
            entry,
            "answering_machine",
        )
    )

    assert result == {
        "ok": True,
        "action_id": "answering_machine",
        "enabled": True,
    }
    assert api.answering_machine_enabled is True


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
    assert result["alarm_page_entity"] == {
        "kind": "button",
        "domain": "c300x",
        "entity_id": "stair_light",
        "name": "stair_light",
        "name_key": "stair_light",
        "state_label": "",
    }


def test_async_status_uses_configured_alarm_page_entity() -> None:
    hass = FakeHass(
        states=FakeStates(
            {
                "switch.porch": FakeState(
                    "on",
                    attributes={"friendly_name": "Porch"},
                )
            }
        )
    )
    entry = FakeEntry(
        data={
            CONF_DEVICE_UI_ENABLED: True,
            CONF_ALARM_PAGE_ENTITY_ID: "switch.porch",
        }
    )

    result = run(async_status(hass, entry))

    assert configured_alarm_page_entity_id(entry) == "switch.porch"
    assert result["alarm_page_entity"] == {
        "domain": "c300x",
        "entity_id": "switch.porch",
        "name": "Porch",
        "state_label": "Ein",
        "kind": "switch",
        "state": True,
    }


def test_async_execute_dashboard_action_allows_alarm_page_entity() -> None:
    hass = FakeHass(states=FakeStates({"switch.porch": FakeState("off")}))
    entry = FakeEntry(
        options={
            CONF_ALARM_PAGE_ENTITY_ID: "switch.porch",
            CONF_DASHBOARD_ENTITIES: [],
        }
    )

    result = run(async_execute_dashboard_action(hass, entry, "switch.porch"))

    assert result == {"ok": True, "action_id": "switch.porch"}
    assert hass.services.calls == [
        ("switch", "toggle", {"entity_id": "switch.porch"}, True)
    ]


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


def test_async_status_ignores_stale_alarmo_blockers_for_closed_binary_sensors() -> None:
    alarmo_entity = types.SimpleNamespace(
        entity_id="alarm_control_panel.alarmo",
        area_id="area-1",
        _config={
            "code_arm_required": False,
            "code_mode_change_required": False,
            "code_disarm_required": False,
        },
        _ready_to_arm_modes=["armed_away"],
        open_sensors={"binary_sensor.front_door": "open"},
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
                "alarm_control_panel.alarmo": FakeState(
                    "disarmed",
                    attributes={"supported_features": 2},
                ),
                "binary_sensor.front_door": FakeState(
                    "off",
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

    assert "open_sensors" not in result["alarm"]
    assert commands["arm_away"]["ready"] is True
    assert commands["arm_away"]["blocking_sensor_count"] == 0
    assert commands["arm_away"]["blocking_sensors"] == []


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


def test_async_status_prefers_alarmo_delay_remaining() -> None:
    alarmo_entity = types.SimpleNamespace(
        entity_id="alarm_control_panel.alarmo",
        expiration=datetime.now(UTC).replace(year=datetime.now(UTC).year + 1),
    )
    hass = FakeHass(
        states=FakeStates(
            {
                "alarm_control_panel.alarmo": FakeState(
                    "arming",
                    attributes={"delay": 1},
                ),
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

    assert result["alarm"]["delay_remaining"] > 1


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


def test_async_status_uses_alarmo_open_sensors_when_state_has_none() -> None:
    alarmo_entity = types.SimpleNamespace(
        entity_id="alarm_control_panel.alarmo",
        open_sensors={"binary_sensor.window": "open", "group_id": "ignored"},
    )
    hass = FakeHass(
        states=FakeStates(
            {
                "alarm_control_panel.alarmo": FakeState("triggered"),
                "binary_sensor.window": FakeState(
                    "on",
                    attributes={"friendly_name": "Window"},
                ),
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

    assert result["alarm"]["open_sensor_count"] == 1
    assert result["alarm"]["open_sensors"] == [
        {"entity_id": "binary_sensor.window", "name": "Window", "state": "open"}
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


def test_async_status_checks_all_alarmo_areas_for_master_alarm() -> None:
    master_entity = types.SimpleNamespace(
        entity_id="alarm_control_panel.alarmo",
        _config={
            "code_arm_required": False,
            "code_mode_change_required": False,
            "code_disarm_required": False,
        },
    )
    area_done = types.SimpleNamespace(
        entity_id="alarm_control_panel.area_done",
        area_id="done",
        state="armed_away",
    )
    area_open = types.SimpleNamespace(
        entity_id="alarm_control_panel.area_open",
        area_id="open",
        state="disarmed",
    )
    sensor_handler = FakeAlarmoSensorHandler(
        responses={
            ("done", "armed_away"): {"binary_sensor.should_skip": "open"},
            ("open", "armed_away"): {"binary_sensor.front_door": "open"},
        },
        _config={"binary_sensor.front_door": {"type": "door"}},
    )
    hass = FakeHass(
        states=FakeStates(
            {
                "alarm_control_panel.alarmo": FakeState(
                    "disarmed",
                    attributes={"supported_features": 2},
                ),
                "binary_sensor.front_door": FakeState(
                    "on",
                    attributes={"friendly_name": "Front door"},
                ),
            }
        ),
        data={
            "alarmo": {
                "master": master_entity,
                "areas": {"done": area_done, "open": area_open},
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
    command = next(
        command
        for command in result["alarm"]["commands"]
        if command["command"] == "arm_away"
    )

    assert command["ready"] is False
    assert command["blocking_sensors"] == [
        {
            "entity_id": "binary_sensor.front_door",
            "name": "Front door",
            "state": "open",
        }
    ]


def test_async_status_falls_back_to_alarmo_open_sensors_on_validation_error() -> None:
    class FailingSensorHandler:
        def validate_arming_event(self, *_args: Any, **_kwargs: Any) -> None:
            raise KeyError("alarmo not ready")

    alarmo_entity = types.SimpleNamespace(
        entity_id="alarm_control_panel.alarmo",
        area_id="area-1",
        _config={
            "code_arm_required": False,
            "code_mode_change_required": False,
            "code_disarm_required": False,
        },
        open_sensors={"binary_sensor.window": "open"},
    )
    hass = FakeHass(
        states=FakeStates(
            {
                "alarm_control_panel.alarmo": FakeState(
                    "disarmed",
                    attributes={"supported_features": 2},
                ),
                "binary_sensor.window": FakeState(
                    "on",
                    attributes={"friendly_name": "Window"},
                ),
            }
        ),
        data={
            "alarmo": {
                "master": None,
                "areas": {"area-1": alarmo_entity},
                "sensor_handler": FailingSensorHandler(),
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
    command = next(
        command
        for command in result["alarm"]["commands"]
        if command["command"] == "arm_away"
    )

    assert command["ready"] is False
    assert command["blocking_sensors"] == [
        {"entity_id": "binary_sensor.window", "name": "Window", "state": "open"}
    ]


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
    assert hass.bus.events == []


def test_async_trigger_stair_light_uses_default_p_n_address() -> None:
    hass = FakeHass()
    entry = FakeEntry(data={})

    result = run(async_trigger_stair_light(hass, entry))

    assert result == {"ok": True, "action_id": "stair_light", "address": "10"}
    assert entry.runtime_data.api.last_stair_light_address == "10"


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


def test_async_trigger_stair_light_uses_default_p_n_address_with_options() -> None:
    hass = FakeHass()
    entry = FakeEntry(data={}, options={})

    result = run(async_trigger_stair_light(hass, entry))

    assert result == {"ok": True, "action_id": "stair_light", "address": "10"}
    assert entry.runtime_data.api.last_stair_light_address == "10"


def test_async_trigger_stair_light_accepts_override_address() -> None:
    hass = FakeHass()
    entry = FakeEntry(data={})

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
    assert "buttons" not in main_page
    assert "switches" not in main_page
    buttons = pages[""]["items"]
    assert {
        "domain": "c300x",
        "entity_id": "leave_home",
        "kind": "button",
        "name": "leave_home",
        "state_label": "",
    } in buttons


def test_async_dashboard_payload_does_not_build_full_status(monkeypatch: Any) -> None:
    async def fail_status(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("dashboard payload should not build full display status")

    monkeypatch.setattr(executor_module, "async_status", fail_status)
    hass = FakeHass(
        states=FakeStates({"alarm_control_panel.home": FakeState("disarmed")})
    )
    entry = FakeEntry(
        data={
            CONF_ALARM_ENTITY_ID: "alarm_control_panel.home",
            CONF_DEVICE_UI_ENABLED: True,
        },
    )

    result = run(async_dashboard_payload(hass, entry))

    assert result["data"]["pages"][0]["badges"][1] == {"state": "Alarm\nAus"}


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
                        "forecast": [
                            {
                                "datetime": "2026-05-29T14:00:00+00:00",
                                "condition": "rainy",
                                "temperature": 20,
                            },
                            {
                                "datetime": "2026-05-29T18:00:00+00:00",
                                "condition": "cloudy",
                                "temperature": 18,
                            },
                        ],
                    },
                ),
                "sun.sun": FakeState(
                    "above_horizon",
                    datetime(2026, 5, 29, 10, 30, tzinfo=UTC),
                    {
                        "next_rising": "2026-05-30T03:20:00+00:00",
                        "next_setting": "2026-05-29T19:28:00+00:00",
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
        "title": "Wetter",
        "condition": "Sonnig",
        "condition_key": "sunny",
        "temperature": "22 C",
        "humidity": "55%",
        "wind": "12 km/h",
        "forecast": "14:00 Regen 20 C | 18:00 Bewoelkt 18 C",
        "forecast_1": {
            "time": "14:00",
            "condition": "Regen",
            "condition_key": "rainy",
            "temperature": "20 C",
        },
        "forecast_2": {
            "time": "18:00",
            "condition": "Bewoelkt",
            "condition_key": "cloudy",
            "temperature": "18 C",
        },
        "sun": "03:20   19:28",
        "sunrise": "03:20",
        "sunset": "19:28",
        "updated": "10:30",
        "badge": "Sonnig\n22 C",
        "color": "#f1c40f",
    }
    assert "buttons" not in main_page
    assert "switches" not in main_page


def test_async_dashboard_payload_uses_weather_forecast_service() -> None:
    states = FakeStates(
        {
            "weather.home": FakeState(
                "cloudy",
                datetime(2026, 5, 29, 10, 30, tzinfo=UTC),
                {
                    "friendly_name": "Zuhause",
                    "temperature": 19,
                    "temperature_unit": "C",
                },
            ),
            "sun.sun": FakeState(
                "above_horizon",
                datetime(2026, 5, 29, 10, 30, tzinfo=UTC),
                {
                    "next_rising": "2026-05-30T03:20:00+00:00",
                    "next_setting": "2026-05-29T19:28:00+00:00",
                },
            ),
        }
    )
    hass = FakeHass(
        states=states,
        services=FakeServices(
            responses={
                (
                    "weather",
                    "get_forecasts",
                ): {
                    "weather.home": {
                        "forecast": [
                            {
                                "datetime": "2026-05-29T15:00:00+00:00",
                                "condition": "rainy",
                                "temperature": 18,
                            }
                        ]
                    }
                }
            }
        ),
    )
    entry = FakeEntry(
        data={
            CONF_DEVICE_UI_ENABLED: True,
            CONF_WEATHER_ENTITY_ID: "weather.home",
        }
    )

    result = run(async_dashboard_payload(hass, entry))

    main_page = {page["title"]: page for page in result["data"]["pages"]}["C300X"]
    assert main_page["weather"]["forecast"] == "15:00 Regen 18 C"
    assert main_page["weather"]["forecast_1"] == {
        "time": "15:00-16:00",
        "condition": "Regen",
        "condition_key": "rainy",
        "temperature": "18 C",
    }
    assert main_page["weather"]["sun"] == "03:20   19:28"
    assert main_page["weather"]["sunrise"] == "03:20"
    assert main_page["weather"]["sunset"] == "19:28"
    assert hass.services.calls[0] == (
        "weather",
        "get_forecasts",
        {"entity_id": "weather.home", "type": "hourly"},
        True,
    )


def test_async_dashboard_payload_caches_weather_forecast_service() -> None:
    states = FakeStates(
        {
            "weather.home": FakeState(
                "cloudy",
                datetime(2026, 5, 29, 10, 30, tzinfo=UTC),
                {
                    "temperature": 19,
                    "temperature_unit": "C",
                },
                last_updated=datetime(2026, 5, 29, 10, 30, tzinfo=UTC),
            ),
            "sun.sun": FakeState(
                "above_horizon",
                datetime(2026, 5, 29, 10, 30, tzinfo=UTC),
                {
                    "next_rising": "2026-05-30T03:20:00+00:00",
                    "next_setting": "2026-05-29T19:28:00+00:00",
                },
            ),
        }
    )
    hass = FakeHass(
        states=states,
        services=FakeServices(
            responses={
                (
                    "weather",
                    "get_forecasts",
                ): {
                    "weather.home": {
                        "forecast": [
                            {
                                "datetime": "2026-05-29T15:00:00+00:00",
                                "condition": "rainy",
                                "temperature": 18,
                            }
                        ]
                    }
                }
            }
        ),
    )
    entry = FakeEntry(
        data={
            CONF_DEVICE_UI_ENABLED: True,
            CONF_WEATHER_ENTITY_ID: "weather.home",
        }
    )

    first = run(async_dashboard_payload(hass, entry))
    second = run(async_dashboard_payload(hass, entry))

    assert first["data"]["pages"][0]["weather"]["forecast"] == "15:00 Regen 18 C"
    assert second["data"]["pages"][0]["weather"]["forecast"] == "15:00 Regen 18 C"
    assert hass.services.calls == [
        (
            "weather",
            "get_forecasts",
            {"entity_id": "weather.home", "type": "hourly"},
            True,
        )
    ]


def test_async_dashboard_payload_weather_offline_entity() -> None:
    hass = FakeHass()
    entry = FakeEntry(
        data={
            CONF_DEVICE_UI_ENABLED: True,
            CONF_WEATHER_ENTITY_ID: "weather.missing",
        }
    )

    result = run(async_dashboard_payload(hass, entry))

    weather = result["data"]["pages"][0]["weather"]
    assert weather["available"] is False
    assert weather["condition_key"] == "unavailable"
    assert weather["forecast_1"] == {
        "time": "",
        "condition": "",
        "condition_key": "",
        "temperature": "",
    }
    assert weather["badge"] == "Wetter\nOffline"
    assert weather["color"] == "#f1c40f"


def test_async_dashboard_payload_weather_uses_daily_forecast_fallback() -> None:
    class DailyOnlyServices(FakeServices):
        async def async_call(
            self,
            domain: str,
            service: str,
            data: dict[str, Any],
            blocking: bool,
            target: dict[str, Any] | None = None,
            return_response: bool = False,
        ) -> Any:
            self.calls.append((domain, service, data, blocking))
            self.targets.append(target)
            if data["type"] == "hourly":
                return {"weather.home": {"forecast": []}}
            return {
                "forecast": [
                    {
                        "datetime": "2026-05-30T00:00:00+00:00",
                        "condition": "sunny",
                        "templow": 12,
                    },
                    {
                        "datetime": "2026-05-31T00:00:00+00:00",
                        "condition": "rainy",
                        "temperature": 18,
                    },
                ]
            }

    hass = FakeHass(
        states=FakeStates(
            {
                "weather.home": FakeState(
                    "cloudy",
                    datetime(2026, 5, 29, 10, 30, tzinfo=UTC),
                    {
                        "temperature": 19,
                        "temperature_unit": "C",
                    },
                )
            }
        ),
        services=DailyOnlyServices(),
    )
    entry = FakeEntry(
        data={
            CONF_DEVICE_UI_ENABLED: True,
            CONF_WEATHER_ENTITY_ID: "weather.home",
        }
    )

    result = run(async_dashboard_payload(hass, entry))

    weather = result["data"]["pages"][0]["weather"]
    assert weather["forecast_1"] == {
        "time": "30.5.",
        "condition": "Sonnig",
        "condition_key": "sunny",
        "temperature": "12 C",
    }
    assert weather["forecast_2"] == {
        "time": "31.5.",
        "condition": "Regen",
        "condition_key": "rainy",
        "temperature": "18 C",
    }
    assert hass.services.calls == [
        (
            "weather",
            "get_forecasts",
            {"entity_id": "weather.home", "type": "hourly"},
            True,
        ),
        (
            "weather",
            "get_forecasts",
            {"entity_id": "weather.home", "type": "daily"},
            True,
        ),
    ]


def test_async_dashboard_payload_weather_uses_nested_attribute_forecast() -> None:
    hass = FakeHass(
        states=FakeStates(
            {
                "weather.home": FakeState(
                    "pouring",
                    datetime(2026, 5, 29, 10, 30, tzinfo=UTC),
                    {
                        "temperature": 17,
                        "unit_of_measurement": "C",
                        "humidity": "",
                        "wind_speed": "",
                        "forecasts": {
                            "daily": [
                                {
                                    "time": "Tomorrow",
                                    "condition": "cloudy",
                                    "temperature": "",
                                    "templow": 11,
                                },
                                "ignored",
                                {
                                    "time": "Later",
                                    "condition": "sunny",
                                    "temperature": 23,
                                },
                            ]
                        },
                    },
                ),
                "sun.sun": FakeState("unknown", attributes={}),
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

    weather = result["data"]["pages"][0]["weather"]
    assert weather["condition"] == "Starkregen"
    assert weather["humidity"] == ""
    assert weather["wind"] == ""
    assert weather["forecast_1"] == {
        "time": "Tomorrow",
        "condition": "Bewoelkt",
        "condition_key": "cloudy",
        "temperature": "11 C",
    }
    assert weather["forecast_2"] == {
        "time": "Later",
        "condition": "Sonnig",
        "condition_key": "sunny",
        "temperature": "23 C",
    }
    assert weather["sun"] == ""
    assert weather["color"] == "#5dade2"


def test_async_dashboard_payload_weather_handles_forecast_service_errors() -> None:
    hass = FakeHass(
        states=FakeStates(
            {
                "weather.home": FakeState(
                    "unknown",
                    None,
                    {
                        "temperature": "",
                        "forecast": {"forecast": "not-a-list"},
                    },
                )
            }
        ),
        services=FakeServices(error=TypeError("unsupported")),
        config=types.SimpleNamespace(language="xx"),
    )
    entry = FakeEntry(
        data={
            CONF_DEVICE_UI_ENABLED: True,
            CONF_WEATHER_ENTITY_ID: "weather.home",
        }
    )

    result = run(async_dashboard_payload(hass, entry))

    weather = result["data"]["pages"][0]["weather"]
    assert weather["available"] is False
    assert weather["title"] == "Weather"
    assert weather["condition"] == "Unknown"
    assert weather["forecast"] == ""
    assert weather["forecast_1"]["time"] == ""
    assert weather["updated"] == ""


def test_async_dashboard_payload_weather_cache_invalidates_on_state_revision() -> None:
    states = FakeStates(
        {
            "weather.home": FakeState(
                "cloudy",
                datetime(2026, 5, 29, 10, 30, tzinfo=UTC),
                {
                    "temperature": 19,
                    "temperature_unit": "C",
                },
                last_updated=datetime(2026, 5, 29, 10, 30, tzinfo=UTC),
            )
        }
    )
    hass = FakeHass(
        states=states,
        services=FakeServices(
            responses={
                (
                    "weather",
                    "get_forecasts",
                ): {
                    "weather.home": {
                        "forecast": [
                            {
                                "datetime": "2026-05-29T15:00:00+00:00",
                                "condition": "rainy",
                                "temperature": 18,
                            }
                        ]
                    }
                }
            }
        ),
    )
    entry = FakeEntry(
        data={
            CONF_DEVICE_UI_ENABLED: True,
            CONF_WEATHER_ENTITY_ID: "weather.home",
        }
    )

    run(async_dashboard_payload(hass, entry))
    states.values["weather.home"].last_updated = datetime(
        2026,
        5,
        29,
        10,
        31,
        tzinfo=UTC,
    )
    run(async_dashboard_payload(hass, entry))

    assert len(hass.services.calls) == 2


def test_dashboard_weather_payload_handles_non_dict_attributes() -> None:
    hass = FakeHass(
        states=FakeStates(
            {
                "weather.home": FakeState(
                    "windy",
                    datetime(2026, 5, 29, 10, 30, tzinfo=UTC),
                    "not-a-dict",  # type: ignore[arg-type]
                )
            }
        )
    )

    weather = dashboard_weather_payload(hass, "weather.home", "en")

    assert weather is not None
    assert weather["available"] is True
    assert weather["condition"] == "Windy"
    assert weather["temperature"] == ""
    assert weather["humidity"] == ""
    assert weather["wind"] == ""
    assert weather["forecast_1"]["time"] == ""


def test_async_dashboard_payload_weather_replaces_invalid_cache_container() -> None:
    states = FakeStates(
        {
            "weather.home": FakeState(
                "cloudy",
                datetime(2026, 5, 29, 10, 30, tzinfo=UTC),
                {
                    "temperature": 19,
                    "temperature_unit": "C",
                },
                last_updated=datetime(2026, 5, 29, 10, 30, tzinfo=UTC),
            )
        }
    )
    hass = FakeHass(
        states=states,
        data={"bticino_c300x_dashboard_weather_forecast": "stale"},
        services=FakeServices(
            responses={
                (
                    "weather",
                    "get_forecasts",
                ): {
                    "weather.home": {
                        "forecast": [
                            {
                                "datetime": "2026-05-29T15:00:00+00:00",
                                "condition": "rainy",
                                "temperature": 18,
                            }
                        ]
                    }
                }
            }
        ),
    )
    entry = FakeEntry(
        data={
            CONF_DEVICE_UI_ENABLED: True,
            CONF_WEATHER_ENTITY_ID: "weather.home",
        }
    )

    result = run(async_dashboard_payload(hass, entry))

    assert result["data"]["pages"][0]["weather"]["forecast"] == "15:00 Regen 18 C"
    assert isinstance(hass.data["bticino_c300x_dashboard_weather_forecast"], dict)
    assert len(hass.services.calls) == 1


def test_dashboard_weather_cache_helpers_handle_unusable_cache() -> None:
    hass = types.SimpleNamespace(data="not-a-dict")

    assert _weather_forecast_cache(hass) == {}
    assert (
        _cached_weather_forecast(
            {("weather.home", "hourly"): {"expires_at": 0.0}},
            "weather.home",
            "hourly",
            "",
        )
        is None
    )


def test_dashboard_weather_private_helpers_cover_sun_and_truncation() -> None:
    hass = FakeHass(
        states=FakeStates(
            {
                "sun.sun": FakeState(
                    "above_horizon",
                    attributes={"next_rising": "2026-05-30T03:20:00+00:00"},
                )
            }
        )
    )
    long_forecast = [
        {
            "time": "very-long-unparseable-weather-time-label",
            "condition": "unknown_condition_with_a_long_name",
            "temperature": 123,
            "temperature_unit": "C",
        },
        {
            "time": "second-long-unparseable-weather-time-label",
            "condition": "another_unknown_condition_with_a_long_name",
            "temperature": 456,
            "temperature_unit": "C",
        },
    ]

    assert _weather_sun(hass, "en") == "03:20"
    assert _weather_forecast_time_label(None, "hourly") == ""
    assert _weather_forecast_temperature({}, "C") == ""
    assert _weather_forecast({}, "en", forecast_items=long_forecast).endswith("...")


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
    assert pages["Licht"]["items"] == [
        {
            "domain": "c300x",
            "entity_id": "entry_light",
            "kind": "switch",
            "name": "Diele",
            "state": True,
            "state_label": "Ein",
        }
    ]
    assert pages["Kamera"]["items"] == [
        {
            "kind": "image",
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
    page = pages[""]
    assert [item["entity_id"] for item in page["items"]] == [
        "switch.entry",
        "sensor.temperature",
        "binary_sensor.window",
        "button.restart",
        "input_number.target",
        "select.forwarding",
        "input_select.scene",
    ]
    assert page["items"] == [
        {
            "domain": "c300x",
            "entity_id": "switch.entry",
            "kind": "switch",
            "name": "Entry",
            "state": True,
            "state_label": "Ein",
        },
        {
            "domain": "c300x",
            "entity_id": "sensor.temperature",
            "kind": "entity",
            "name": "Temperature",
            "state": False,
            "state_label": "21.5 C",
        },
        {
            "domain": "c300x",
            "entity_id": "binary_sensor.window",
            "kind": "entity",
            "name": "Window",
            "state": True,
            "state_label": "Offen",
            "color": "#ff6b6b",
        },
        {
            "domain": "c300x",
            "entity_id": "button.restart",
            "kind": "button",
            "name": "Restart",
            "state_label": "",
        },
        {
            "domain": "c300x",
            "entity_id": "input_number.target",
            "kind": "slider",
            "max": 23.0,
            "min": 15.0,
            "name": "Target",
            "state_label": "18 C",
            "step": 0.5,
            "value": 18.0,
        },
        {
            "domain": "c300x",
            "entity_id": "select.forwarding",
            "kind": "choice",
            "name": "Forwarding",
            "options": [
                {"label": "Smartphone", "value": "Smartphone"},
                {"label": "Home Assistant", "value": "Home Assistant"},
                {"label": "Blocked", "value": "Blocked"},
            ],
            "state_label": "Home Assistant",
            "value": "Home Assistant",
        },
        {
            "domain": "c300x",
            "entity_id": "input_select.scene",
            "kind": "choice",
            "name": "Scene",
            "options": [
                {"label": "Day", "value": "Day"},
                {"label": "Night", "value": "Night"},
            ],
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

    page = {page["title"]: page for page in result["data"]["pages"]}[""]
    labels_by_entity = {item["entity_id"]: item["state_label"] for item in page["items"]}
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

        page = {page["title"]: page for page in result["data"]["pages"]}[""]
        by_entity = {item["entity_id"]: item for item in page["items"]}
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

        page = {page["title"]: page for page in result["data"]["pages"]}[""]
        assert page["items"][0]["state_label"] == "Unsafe"
        assert page["items"][0]["color"] == "#ff6b6b"


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
            CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: {
                "switch.entry": {"name": "entity_id", "secondary": "entity_id"},
                "sensor.temperature": {"name": "entity_id", "secondary": "entity_id"},
                "button.restart": {"name": "entity_id", "secondary": "entity_id"},
                "input_number.target": {
                    "name": "entity_id",
                    "secondary": "entity_id",
                },
                "select.forwarding": {"name": "entity_id", "secondary": "entity_id"},
            },
        },
    )

    result = run(async_dashboard_payload(hass, entry))

    page = {page["title"]: page for page in result["data"]["pages"]}[""]
    assert [item["entity_id"] for item in page["items"]] == [
        "switch.entry",
        "sensor.temperature",
        "button.restart",
        "input_number.target",
        "select.forwarding",
    ]
    assert page["items"][0]["name"] == "switch.entry"
    assert page["items"][0]["state_label"] == "switch.entry"
    assert page["items"][1]["name"] == "sensor.temperature"
    assert page["items"][1]["state_label"] == "sensor.temperature"
    assert page["items"][2]["name"] == "button.restart"
    assert page["items"][2]["state_label"] == "button.restart"
    assert page["items"][3]["name"] == "input_number.target"
    assert page["items"][3]["state_label"] == "input_number.target"
    assert page["items"][4]["name"] == "select.forwarding"
    assert page["items"][4]["state_label"] == "select.forwarding"


def test_async_dashboard_payload_uses_per_entity_display_overrides() -> None:
    hass = FakeHass(
        states=FakeStates(
            {
                "sensor.temperature": FakeState(
                    "21.5",
                    attributes={
                        "friendly_name": "Temperature",
                        "unit_of_measurement": "C",
                    },
                ),
                "switch.entry": FakeState("on", attributes={"friendly_name": "Entry"}),
            }
        )
    )
    entry = FakeEntry(
        options={
            CONF_DASHBOARD_ENTITIES: ["sensor.temperature", "switch.entry"],
            CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: {
                "sensor.temperature": {
                    "name": "entity_id",
                    "secondary": "none",
                },
                "switch.entry": {
                    "secondary": "entity_id",
                },
            },
        },
    )

    result = run(async_dashboard_payload(hass, entry))

    page = {page["title"]: page for page in result["data"]["pages"]}[""]
    assert [item["entity_id"] for item in page["items"]] == [
        "sensor.temperature",
        "switch.entry",
    ]
    assert page["items"][0]["name"] == "sensor.temperature"
    assert page["items"][0]["state_label"] == ""
    assert page["items"][1]["name"] == "Entry"
    assert page["items"][1]["state_label"] == "switch.entry"


def test_async_dashboard_payload_uses_custom_entity_display_name() -> None:
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
            CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: {
                "sensor.temperature": {
                    "name": "custom",
                    "custom_name": "Outside",
                },
            },
        },
    )

    result = run(async_dashboard_payload(hass, entry))

    page = {page["title"]: page for page in result["data"]["pages"]}[""]
    assert page["items"][0]["name"] == "Outside"


def test_dashboard_entity_display_config_fields_drive_payload() -> None:
    entity_ids = ["sensor.temperature", "button.restart"]
    overrides = dashboard_entity_display_overrides_from_fields(
        {
            "1. Temperature - Name": "custom",
            "1. Temperature - Custom name": "Outside",
            "1. Temperature - Secondary line": "entity_id",
            "2. Restart - Name": "entity_id",
            "2. Restart - Custom name": "",
            "2. Restart - Secondary line": "state",
        },
        entity_ids,
    )
    hass = FakeHass(
        states=FakeStates(
            {
                "sensor.temperature": FakeState(
                    "21.5",
                    attributes={"friendly_name": "Temperature"},
                ),
                "button.restart": FakeState(
                    "unknown",
                    attributes={"friendly_name": "Restart"},
                ),
            }
        )
    )
    entry = FakeEntry(
        options={
            CONF_DASHBOARD_ENTITIES: entity_ids,
            CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: overrides,
        },
    )

    result = run(async_dashboard_payload(hass, entry))

    page = {page["title"]: page for page in result["data"]["pages"]}[""]
    assert page["items"][0]["name"] == "Outside"
    assert page["items"][0]["state_label"] == "sensor.temperature"
    assert page["items"][1]["name"] == "button.restart"
    assert page["items"][1]["state_label"] == ""


def test_async_dashboard_payload_preserves_exact_choice_option_values() -> None:
    long_option = "Home   Assistant  " + ("manual " * 20)
    states = {
        "select.forwarding": FakeState(
            long_option,
            attributes={
                "friendly_name": "Forwarding",
                "options": [long_option],
            },
        )
    }
    hass = FakeHass(states=states)
    entry = FakeEntry(options={CONF_DASHBOARD_ENTITIES: ["select.forwarding"]})

    result = run(
        async_dashboard_payload(
            hass,
            entry,
        )
    )
    page = {page["title"]: page for page in result["data"]["pages"]}[""]

    choice = page["items"][0]
    assert choice["domain"] == "c300x"
    assert choice["entity_id"] == "select.forwarding"
    assert choice["name"] == "Forwarding"
    assert choice["value"] == long_option
    assert choice["state_label"] != long_option
    assert choice["state_label"].startswith("Home Assistant manual")
    assert choice["options"][0]["value"] == long_option
    assert choice["options"][0]["label"] != long_option
    assert choice["options"][0]["label"].startswith("Home Assistant manual")


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
            CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: {
                "sensor.temperature": {"secondary": "last_changed"}
            },
        },
    )

    result = run(async_dashboard_payload(hass, entry))

    page = {page["title"]: page for page in result["data"]["pages"]}[""]
    assert page["items"][0]["name"] == "Temperature"
    assert page["items"][0]["state_label"] == "14.06. 12:34"


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
            CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: {
                "sensor.temperature": {"secondary": "none"}
            },
        },
    )

    result = run(async_dashboard_payload(hass, entry))

    page = {page["title"]: page for page in result["data"]["pages"]}[""]
    assert page["items"][0]["name"] == "Temperature"
    assert page["items"][0]["state_label"] == ""


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

    assert "buttons" not in result["data"]["pages"][0]
