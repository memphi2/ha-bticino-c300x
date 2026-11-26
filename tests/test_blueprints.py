from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT_DIR = ROOT / "blueprints" / "automation" / "bticino_c300x"
PACKAGED_BLUEPRINT_DIR = (
    ROOT
    / "custom_components"
    / "bticino_c300x"
    / "blueprints"
    / "automation"
    / "bticino_c300x"
)


class BlueprintLoader(yaml.SafeLoader):
    """YAML loader that accepts Home Assistant blueprint tags."""


def _construct_ha_tag(
    loader: BlueprintLoader, _tag_suffix: str, node: yaml.Node
) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return None


BlueprintLoader.add_multi_constructor("!", _construct_ha_tag)


def _blueprint(filename: str) -> dict[str, Any]:
    return yaml.load(
        (BLUEPRINT_DIR / filename).read_text(encoding="utf-8"),
        Loader=BlueprintLoader,
    )


# Call actions name the unit and the call they belong to (docs/dev/multi-outdoor-units.md).
CALL_TARGET = {"entity_id": "{{ doorbell_event }}"}
CALL_DATA = {"call_id": "{{ call_id }}"}
# A hang-up after the call ended has nothing to do and must not fail the run.
HANGUP = {
    "service": "bticino_c300x.hangup_call", "continue_on_error": True,
    "target": CALL_TARGET, "data": CALL_DATA,
}


def test_blueprints_are_valid_automation_blueprints() -> None:
    expected = {
        "calendar_display_reminder.yaml",
        "doorbell_notification.yaml",
        "doorbell_call_android.yaml",
        "doorbell_call_ios.yaml",
        "ring_capture.yaml",
        "ring_capture_wyoming.yaml",
        "strict_phrase_decision.yaml",
    }

    assert {path.name for path in BLUEPRINT_DIR.glob("*.yaml")} == expected
    for filename in expected:
        data = _blueprint(filename)
        assert data["blueprint"]["domain"] == "automation"
        assert data["blueprint"]["source_url"].endswith(filename)
        assert data["mode"] in {"restart", "single", "queued"}


def test_packaged_blueprints_match_repo_blueprints() -> None:
    repo_files = {path.name for path in BLUEPRINT_DIR.glob("*.yaml")}
    package_files = {path.name for path in PACKAGED_BLUEPRINT_DIR.glob("*.yaml")}

    assert package_files == repo_files
    for filename in repo_files:
        assert (PACKAGED_BLUEPRINT_DIR / filename).read_text(
            encoding="utf-8"
        ) == (BLUEPRINT_DIR / filename).read_text(encoding="utf-8")


def test_calendar_blueprint_ha_schema_inputs_and_templates(tmp_path: Path) -> None:
    import asyncio

    from homeassistant.components.blueprint import BLUEPRINT_SCHEMA
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import config_validation as cv
    from homeassistant.helpers.template import Template
    from homeassistant.util import yaml as ha_yaml

    async def run() -> None:
        source = ha_yaml.load_yaml(str(BLUEPRINT_DIR / "calendar_display_reminder.yaml"))
        validated = BLUEPRINT_SCHEMA(source)
        inputs = {key: item["default"] for key, item in validated["blueprint"]["input"].items() if "default" in item}
        inputs.update(calendar="calendar.home", station="device")
        rendered = ha_yaml.substitute(source, inputs)
        assert cv.time_period(rendered["trigger"][0]["offset"]).total_seconds() == -900
        assert rendered["mode"] == "queued"
        hass = HomeAssistant(str(tmp_path))
        variables = {"trigger": {"entity_id": "calendar.home", "calendar_event": {"summary": "Visit", "start": "2026-11-10T12:00:00+00:00"}}}
        for key, value in rendered["variables"].items():
            variables[key] = Template(value, hass).async_render(variables)
        assert rendered["action"][0]["target"] == {"device_id": "device"}
        data = {key: Template(value, hass).async_render(variables) if isinstance(value, str) else value for key, value in rendered["action"][0]["data"].items()}
        from custom_components.bticino_c300x.display_notifications import SHOW_SCHEMA
        checked = SHOW_SCHEMA(data)
        assert len(checked["notification_id"]) == 64
        assert checked["title"] == "Visit"
        assert "12:00" in checked["message"]

    asyncio.run(run())


DOORBELL_BLUEPRINTS = (
    "doorbell_notification.yaml",
    "doorbell_call_android.yaml",
    "doorbell_call_ios.yaml",
    "ring_capture.yaml",
    "ring_capture_wyoming.yaml",
)


def test_doorbell_blueprints_trigger_on_a_doorbell_event_entity() -> None:
    """A ring blueprint reacts to the doorbell event of one outdoor unit.

    The unit's event fires once per call, with its call id; the station's ring
    event has the same shape and is the faster choice (docs/blueprints.md).
    """

    for filename in DOORBELL_BLUEPRINTS:
        data = _blueprint(filename)
        selector = data["blueprint"]["input"]["doorbell_event"]["selector"]
        assert selector == {"entity": {"filter": [{
            "integration": "bticino_c300x", "domain": "event", "device_class": "doorbell",
        }]}}, filename
        assert "c300x_device" not in data["blueprint"]["input"], filename
        assert "entry_id" not in data["blueprint"]["input"], filename
        # Restoring the entity after a restart is no ring.
        assert data["trigger"] == [{
            "platform": "state", "entity_id": "doorbell_event",
            "not_from": ["unavailable"], "not_to": ["unavailable", "unknown"],
        }], filename
        variables = data["variables"]
        assert variables["call_id"] == "{{ trigger.to_state.attributes.call_id | default('', true) if trigger.to_state else '' }}"
        assert variables["entry_id"] == "{{ config_entry_id(doorbell_event) or '' }}"
        if "capture" not in filename:
            assert variables["camera_entity"] == "{{ state_attr(doorbell_event, 'camera_entity_id') or '' }}"
        assert data["condition"][0] == {
            "condition": "template", "value_template": "{{ entry_id not in ['', none] and call_id not in ['', none] }}",
        }, filename
        assert "event_camera_entity" not in str(data), filename
        assert "bticino_c300x_agent_event_received" not in str(data["trigger"]), filename


def test_doorbell_blueprints_find_the_station_sensors_through_the_unit() -> None:
    for filename in ("doorbell_call_android.yaml", "doorbell_call_ios.yaml",
                     "ring_capture.yaml", "ring_capture_wyoming.yaml"):
        variables = _blueprint(filename)["variables"]
        assert variables["doorbell_device"] == "{{ device_id(doorbell_event) }}"
        assert variables["c300x_device"] == "{{ device_attr(doorbell_device, 'via_device_id') or doorbell_device }}"
        assert "device_entities(c300x_device)" in variables["c300x_entities"]


@pytest.mark.parametrize("filename", DOORBELL_BLUEPRINTS)
def test_doorbell_blueprint_condition_needs_a_station_and_a_call(tmp_path: Path, filename: str) -> None:
    # Evaluated like Home Assistant does: a template condition passes only when
    # it renders "true", not when it renders some other truthy text.
    import asyncio

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.condition import async_template
    from homeassistant.helpers.template import Template

    async def run() -> None:
        hass = HomeAssistant(str(tmp_path))
        template = Template(_blueprint(filename)["condition"][0]["value_template"], hass)
        for entry_id, call_id, expected in (
            ("01JENTRY", "0badc0de-7", True), ("", "0badc0de-7", False),
            ("01JENTRY", "", False), (None, "0badc0de-7", False), ("01JENTRY", None, False),
        ):
            variables = {"entry_id": entry_id, "call_id": call_id}
            assert async_template(hass, template, variables, trace_result=False) is expected, variables
        await hass.async_stop(force=True)

    asyncio.run(run())


def test_doorbell_notification_offers_the_call_to_the_action() -> None:
    variables = _blueprint("doorbell_notification.yaml")["variables"]

    assert variables["unit_name"] == "{{ trigger.to_state.attributes.unit_name | default('', true) if trigger.to_state else '' }}"
    assert {"call_id", "camera_entity", "unit_name"} <= set(variables)


def test_android_ring_call_blueprint_opens_dashboard_from_notification() -> None:
    data = _blueprint("doorbell_call_android.yaml")
    inputs = data["blueprint"]["input"]
    # Only local action-ID initialization precedes the ringing notification.
    assert set(data["action"][0]) == {"variables"}
    action = data["action"][1]
    wake_action = data["action"][2]
    notify_data = action["data"]["data"]
    templates = "\n".join(condition["value_template"] for condition in data["condition"])
    services = [
        item["service"]
        for item in data["action"]
        if isinstance(item, dict) and "service" in item
    ]
    answer_sequence = data["action"][4]["choose"][0]["sequence"]
    hangup_sequence = data["action"][4]["choose"][1]["sequence"]
    answer_services = [
        item["service"]
        for item in answer_sequence
        if isinstance(item, dict) and "service" in item
    ]

    assert "doorbell_event" in inputs
    assert "entry_id" not in inputs
    assert "forwarding_entity" not in inputs
    assert "media_readiness_entity" not in inputs
    assert "camera_entity" not in inputs
    assert inputs["notification_channel"]["default"] == "alarm_stream"
    # The channel name is the channel's identity on the phone: a new default would give
    # existing users a second channel without their sound and priority settings.
    assert inputs["active_call_channel"]["default"] == "C300X Call"
    assert inputs["notification_media_stream"]["default"] == "alarm_stream"
    assert "'Home Assistant'" not in data["variables"]["forwarding_entity"]
    assert "'homeassistant' in options and 'blocked' in options" in data["variables"]["forwarding_entity"]
    assert "media_user_ok" in data["variables"]["media_readiness_entity"]
    assert "ring_call_supported" in data["variables"]["media_readiness_entity"]
    assert "this.entity_id" in data["variables"]["action_scope"]
    assert data["action"][0]["variables"]["answer_action"].startswith(
        "{{ 'C300X_ANDROID_RING_ANSWER_'"
    )
    assert data["action"][0]["variables"]["hangup_action"].startswith(
        "{{ 'C300X_ANDROID_RING_HANGUP_'"
    )
    assert "dashboard_path.split('#', 1)" in data["variables"]["answer_dashboard_path"]
    assert "launch_target = camera_entity" in data["variables"]["answer_dashboard_path"]
    assert "'c300x_ring_answer='" in data["variables"]["answer_dashboard_path"]
    assert "launch_target | urlencode" in data["variables"]["answer_dashboard_path"]
    assert "~ fragment" in data["variables"]["answer_dashboard_path"]
    assert wake_action["service"] == "notify_service"
    assert wake_action["data"]["message"] == "command_screen_on"
    assert wake_action["data"]["data"]["command"] == "keep_screen_on"
    assert action["service"] == "notify_service"
    assert notify_data["url"] == "{{ dashboard_path }}"
    assert notify_data["clickAction"] == "{{ dashboard_path }}"
    assert notify_data["entity_id"] == "{{ camera_entity }}"
    assert notify_data["tag"] == "{{ ring_tag }}"
    assert notify_data["channel"] == "{{ notification_channel }}"
    assert notify_data["media_stream"] == "{{ notification_media_stream }}"
    assert notify_data["importance"] == "max"
    assert "push" not in notify_data
    assert notify_data["persistent"] is True
    assert notify_data["sticky"] == "true"
    assert notify_data["actions"] == [
        {"action": "{{ answer_action }}", "title": "{{ answer_title }}"},
        {
            "action": "{{ hangup_action }}",
            "title": "{{ hangup_title }}",
            "destructive": True,
        },
        {"action": "URI", "title": "{{ open_title }}", "uri": "{{ dashboard_path }}"},
    ]
    assert data["action"][3]["wait_for_trigger"] == [
        {
            "platform": "event",
            "event_type": "mobile_app_notification_action",
            "event_data": {"action": "{{ answer_action }}"},
        },
        {
            "platform": "event",
            "event_type": "mobile_app_notification_action",
            "event_data": {"action": "{{ hangup_action }}"},
        },
        {
            "id": "door_unlock",
            "platform": "event",
            "event_type": "bticino_c300x_agent_event_received",
            "event_data": {
                "event_key": "door_unlock_started",
                "entry_id": "{{ entry_id }}",
            },
        },
        {
            "id": "door_unlock_action",
            "platform": "event",
            "event_type": "bticino_c300x_action_received",
            "event_data": {
                "action_id": "door_unlock",
                "entry_id": "{{ entry_id }}",
            },
        },
    ]
    assert services == ["notify_service", "notify_service"]
    assert answer_services[:3] == [
        "bticino_c300x.answer_call",
        "notify_service",
        "notify_service",
    ]
    assert answer_sequence[0]["target"] == CALL_TARGET
    assert answer_sequence[0]["data"] == CALL_DATA
    assert answer_sequence[1]["data"]["message"] == "clear_notification"
    assert answer_sequence[1]["data"]["data"]["tag"] == "{{ ring_tag }}"
    assert answer_sequence[2]["data"]["data"]["tag"] == "{{ active_tag }}"
    assert answer_sequence[2]["data"]["data"]["importance"] == "low"
    assert answer_sequence[3]["data"]["message"] == "command_webview"
    assert answer_sequence[3]["data"]["data"]["command"] == "{{ answer_dashboard_path }}"
    assert answer_sequence[4]["wait_for_trigger"] == [
        {
            "platform": "event",
            "event_type": "mobile_app_notification_action",
            "event_data": {"action": "{{ hangup_action }}"},
        }
    ]
    assert answer_sequence[5]["then"][0] == HANGUP
    assert hangup_sequence[0] == HANGUP
    assert "homeassistant" in templates
    assert "ready" in templates
    assert "warning" in templates


def test_ios_ring_call_blueprint_uses_unique_actions_and_event_entry_id() -> None:
    data = _blueprint("doorbell_call_ios.yaml")
    inputs = data["blueprint"]["input"]
    notify_data = data["action"][1]["data"]["data"]
    wait_triggers = data["action"][2]["wait_for_trigger"]
    answer_sequence = data["action"][3]["choose"][0]["sequence"]
    hangup_sequence = data["action"][3]["choose"][1]["sequence"]
    templates = "\n".join(condition["value_template"] for condition in data["condition"])

    assert "entry_id" not in inputs
    assert inputs["notify_service"]["name"] == "iOS notify service"
    assert "'homeassistant' in options and 'blocked' in options" in data["variables"]["forwarding_entity"]
    assert "media_user_ok" in data["variables"]["media_readiness_entity"]
    assert "this.entity_id" in data["variables"]["action_scope"]
    assert data["action"][0]["variables"]["answer_action"].startswith(
        "{{ 'C300X_IOS_RING_ANSWER_'"
    )
    assert data["action"][0]["variables"]["hangup_action"].startswith(
        "{{ 'C300X_IOS_RING_HANGUP_'"
    )
    assert "dashboard_path.split('#', 1)" in data["variables"]["answer_dashboard_path"]
    assert "launch_target = camera_entity" in data["variables"]["answer_dashboard_path"]
    assert "'c300x_ring_answer='" in data["variables"]["answer_dashboard_path"]
    assert "launch_target | urlencode" in data["variables"]["answer_dashboard_path"]
    assert "~ fragment" in data["variables"]["answer_dashboard_path"]
    assert notify_data["push"]["sound"] == {
        "name": "{{ critical_sound }}",
        "critical": 1,
        "volume": "{{ critical_volume | float(1) }}",
    }
    assert notify_data["push"]["interruption-level"] == "critical"
    assert notify_data["actions"][0] == {
        "action": "{{ answer_action }}",
        "title": "{{ answer_title }}",
        "uri": "{{ answer_dashboard_path }}",
        "activationMode": "foreground",
        "authenticationRequired": False,
    }
    assert notify_data["actions"][1]["action"] == "{{ hangup_action }}"
    assert notify_data["actions"][2] == {
        "action": "URI",
        "title": "{{ open_title }}",
        "uri": "{{ dashboard_path }}",
    }
    assert wait_triggers == [
        {
            "platform": "event",
            "event_type": "mobile_app_notification_action",
            "event_data": {"action": "{{ answer_action }}"},
        },
        {
            "platform": "event",
            "event_type": "mobile_app_notification_action",
            "event_data": {"action": "{{ hangup_action }}"},
        },
        {
            "id": "door_unlock",
            "platform": "event",
            "event_type": "bticino_c300x_agent_event_received",
            "event_data": {
                "event_key": "door_unlock_started",
                "entry_id": "{{ entry_id }}",
            },
        },
        {
            "id": "door_unlock_action",
            "platform": "event",
            "event_type": "bticino_c300x_action_received",
            "event_data": {
                "action_id": "door_unlock",
                "entry_id": "{{ entry_id }}",
            },
        },
    ]
    assert answer_sequence[1] == {
        "service": "bticino_c300x.answer_call", "target": CALL_TARGET, "data": CALL_DATA,
    }
    assert answer_sequence[3]["wait_for_trigger"] == [
        {
            "platform": "event",
            "event_type": "mobile_app_notification_action",
            "event_data": {"action": "{{ hangup_action }}"},
        }
    ]
    assert hangup_sequence[0] == HANGUP
    assert "homeassistant" in templates
    assert "ready" in templates
    assert "warning" in templates


def test_ring_capture_blueprint_calls_capture_without_analysis() -> None:
    data = _blueprint("ring_capture.yaml")
    inputs = data["blueprint"]["input"]
    action = data["action"]

    assert "media_readiness_entity" not in inputs
    assert "media_user_ok" in data["variables"]["media_readiness_entity"]
    assert len(action) == 1
    assert action[0]["service"] == "bticino_c300x.capture_doorbell_call"
    assert action[0]["target"] == CALL_TARGET
    assert action[0]["data"]["wav_output_dir"] == "{{ capture_file_dir }}"
    assert "output_path" not in action[0]["data"]


def test_wyoming_blueprint_captures_then_transcribes_latest_files() -> None:
    data = _blueprint("ring_capture_wyoming.yaml")
    inputs = data["blueprint"]["input"]
    services = [action["service"] for action in data["action"]]
    capture_data = data["action"][0]["data"]
    analysis_data = data["action"][1]["data"]

    assert "media_readiness_entity" not in inputs
    assert "media_user_ok" in data["variables"]["media_readiness_entity"]
    assert data["action"][0]["target"] == CALL_TARGET
    assert services == [
        "bticino_c300x.capture_doorbell_call",
        "bticino_c300x.run_ring_wyoming_analysis",
    ]
    assert "include_audio" not in data["blueprint"]["input"]
    assert capture_data["include_audio"] is True
    assert data["action"][0]["response_variable"] == "capture"
    assert analysis_data["capture_path"] == "{{ capture.metadata_path }}"
    assert analysis_data["wav_path"] == "{{ capture.raw_wav_path }}"
    assert analysis_data["result_path"] == "{{ result_path }}"


def test_strict_phrase_blueprint_uses_existing_guardrail_service() -> None:
    data = _blueprint("strict_phrase_decision.yaml")
    trigger = data["trigger"][0]
    action = data["action"][0]

    assert trigger == {"platform": "state", "entity_id": "decision_trigger"}
    assert action["service"] == "bticino_c300x.evaluate_ring_analysis"
    assert action["data"]["result_path"] == "result_path"
    assert action["data"]["capture_path"] == "capture_path"
    assert action["data"]["unlock_on_match"] == "unlock_on_match"
    # The station opens the door of the unit that called; a unit opens its own.
    assert action["target"] == {"device_id": "door"}
    assert data["blueprint"]["input"]["door"]["selector"] == {"device": {"integration": "bticino_c300x"}}
    assert "lock_id" not in str(data) and "entry_id" not in str(data)


def test_ring_call_blueprints_stop_the_phone_ringing_when_the_door_opens() -> None:
    """Letting the visitor in ends the reason to keep ringing. The ring wait has
    to end on the door-unlock event; the timeout branch then clears the
    notification -- without hanging up, which is a separate decision the
    blueprint must not make."""

    for filename, choose_index in (
        ("doorbell_call_android.yaml", 4),
        ("doorbell_call_ios.yaml", 3),
    ):
        data = _blueprint(filename)
        wait_triggers = data["action"][choose_index - 1]["wait_for_trigger"]
        door_triggers = [
            trigger for trigger in wait_triggers if trigger.get("id") == "door_unlock"
        ]
        default_sequence = data["action"][choose_index]["default"]

        assert door_triggers == [
            {
                "id": "door_unlock",
                "platform": "event",
                "event_type": "bticino_c300x_agent_event_received",
                "event_data": {
                    "event_key": "door_unlock_started",
                    "entry_id": "{{ entry_id }}",
                },
            }
        ], filename

        # Home Assistant's own unlock is heard directly as well, so the alert
        # stops even when the device's event arrives late or not at all.
        assert [
            trigger
            for trigger in wait_triggers
            if trigger.get("id") == "door_unlock_action"
        ] == [
            {
                "id": "door_unlock_action",
                "platform": "event",
                "event_type": "bticino_c300x_action_received",
                "event_data": {
                    "action_id": "door_unlock",
                    "entry_id": "{{ entry_id }}",
                },
            }
        ], filename

        # No branch matches a door-unlock trigger, so it lands here.
        assert [step["service"] for step in default_sequence] == [
            "notify_service"
        ], filename
        assert default_sequence[0]["data"]["message"] == "clear_notification"
        assert default_sequence[0]["data"]["data"]["tag"] == "{{ ring_tag }}"

        branch_conditions = [
            branch["conditions"][0]["value_template"]
            for branch in data["action"][choose_index]["choose"]
        ]
        assert not any("door_unlock" in condition for condition in branch_conditions), (
            filename
        )
        # The Ring Call keeps running: opening the door does not decide whether
        # someone still wants to talk to the visitor.
        assert "hangup_call" not in str(default_sequence), filename


def test_android_ring_call_commands_are_sent_as_urgent_messages() -> None:
    """A command is a data message. Android holds a normal-priority one back
    while the phone dozes, so the phone keeps ringing after the door opened and
    the screen wakes late. Every command has to ask for high priority and
    immediate delivery, like the ringing notification itself."""

    data = _blueprint("doorbell_call_android.yaml")
    commands = []

    def collect(node: object) -> None:
        if isinstance(node, dict):
            payload = node.get("data")
            if (
                "service" in node
                and isinstance(payload, dict)
                and str(payload.get("message", "")).startswith(
                    ("command_", "clear_notification")
                )
            ):
                commands.append(payload)
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    collect(data["action"])

    assert sorted(command["message"] for command in commands) == [
        "clear_notification",
        "clear_notification",
        "clear_notification",
        "clear_notification",
        "command_screen_on",
        "command_webview",
    ]
    for command in commands:
        assert command["data"]["priority"] == "high", command["message"]
        assert command["data"]["ttl"] == 0, command["message"]


def test_phone_action_ids_use_real_script_run_contexts(tmp_path):
    """Delayed actions must miss both notification waits and command branches."""
    import asyncio

    from homeassistant.core import Context, HomeAssistant, callback
    from homeassistant.helpers import config_validation as cv
    from homeassistant.helpers.script import Script
    from homeassistant.helpers.template import Template

    async def run():
        hass = HomeAssistant(str(tmp_path))
        emitted = []

        @callback
        def collect(event):
            emitted.append(dict(event.data))

        unsubscribe = hass.bus.async_listen("c300x_test_action_ids", collect)
        try:
            for platform in ("android", "ios"):
                data = _blueprint(f"doorbell_call_{platform}.yaml")
                assert "answer_action" not in data["variables"]
                assert "hangup_action" not in data["variables"]
                # Execute the production initialization step in HA, not a template
                # environment that invents context availability before actions.
                sequence = cv.SCRIPT_SCHEMA([
                    data["action"][0],
                    {"event": "c300x_test_action_ids", "event_data": {
                        "answer_action": "{{ answer_action }}",
                        "hangup_action": "{{ hangup_action }}",
                    }},
                ])
                script = Script(hass, sequence, f"test_{platform}", "automation")
                contexts = [Context(), Context()]
                for context in contexts:
                    await script.async_run({"action_scope": "AUTOMATION_FRONT_DOOR"}, context)
                    await hass.async_block_till_done()
                old, current = emitted[-2:]
                for key in ("answer_action", "hangup_action"):
                    assert old[key] != current[key]
                    assert old[key].endswith(contexts[0].id)
                    assert current[key].endswith(contexts[1].id)

                waits = []
                conditions = []

                def collect_contracts(node, waits, conditions):
                    if isinstance(node, dict):
                        for trigger in node.get("wait_for_trigger", []):
                            if trigger.get("event_type") == "mobile_app_notification_action":
                                waits.append(trigger["event_data"]["action"])
                        if "value_template" in node:
                            conditions.append(node["value_template"])
                        for value in node.values():
                            collect_contracts(value, waits, conditions)
                    elif isinstance(node, list):
                        for value in node:
                            collect_contracts(value, waits, conditions)

                collect_contracts(data["action"], waits, conditions)
                assert len(waits) == 3  # Answer, ring Hang Up, active-call Hang Up.
                expected = [Template(text, hass).async_render(current) for text in waits]
                assert set(expected) == set(current.values())
                assert set(expected).isdisjoint(old.values())
                assert len(conditions) == 3
                for key in ("answer_action", "hangup_action"):
                    for actions, accepted in ((old, False), (current, True)):
                        variables = {**current, "wait": {"trigger": {
                            "event": {"data": {"action": actions[key]}},
                        }}}
                        results = [bool(Template(text, hass).async_render(variables)) for text in conditions]
                        assert any(results) is accepted
                # Notification replacement/cleanup still uses stable tags.
                for key in ("ring_tag", "active_tag"):
                    template = Template(data["variables"][key], hass)
                    assert template.async_render({"action_scope": "FRONT", "context": contexts[0]}) == template.async_render({"action_scope": "FRONT", "context": contexts[1]})
        finally:
            unsubscribe()

    asyncio.run(run())


def test_blueprint_texts_fit_both_station_models() -> None:
    """A blueprint serves a C300X and a C100X: its shown texts name no model.

    Only the integration name "BTicino C300X" stays, and the released default of the Android
    active-call channel: that value identifies the channel on the phone and is no label.
    """

    for directory in (BLUEPRINT_DIR, PACKAGED_BLUEPRINT_DIR):
        for path in directory.glob("*.yaml"):
            blueprint = yaml.load(path.read_text(encoding="utf-8"), Loader=BlueprintLoader)["blueprint"]
            texts = [blueprint["name"], blueprint.get("description", "")]
            for key, field in blueprint.get("input", {}).items():
                texts += [str(field.get("name", "")), str(field.get("description", ""))]
                if key != "active_call_channel":
                    texts.append(str(field.get("default", "")))
            shown = " ".join(texts).replace("BTicino C300X", "")
            assert "C300X" not in shown and "C100X" not in shown, path.name


@pytest.mark.parametrize("filename", DOORBELL_BLUEPRINTS)
def test_doorbell_blueprint_runs_for_a_ring_not_for_a_reload(tmp_path: Path, filename: str) -> None:
    """The blueprint's trigger, variables and condition run by Home Assistant itself.

    A reload of the event entity, with or without a previous state, a restart
    and the removal of the entity are no ring; only a new event time is.
    """

    import asyncio

    from homeassistant import bootstrap, config_entries, core, loader
    from homeassistant.helpers.condition import async_template
    from homeassistant.helpers.template import Template
    from homeassistant.helpers.trigger import (
        async_initialize_triggers,
        async_validate_trigger_config,
    )

    entity_id = "event.gate_doorbell_ring_event"
    ring_1, ring_2 = "2026-11-26T10:00:00.000+00:00", "2026-11-26T10:05:00.000+00:00"
    blueprint = _blueprint(filename)

    async def run() -> None:
        hass = core.HomeAssistant(str(tmp_path))
        hass.config.skip_pip = True
        loader.async_setup(hass)
        hass.config_entries = config_entries.ConfigEntries(hass, {})
        await bootstrap.async_load_base_functionality(hass)
        trigger = [
            {key: entity_id if value == "doorbell_event" else value for key, value in item.items()}
            for item in blueprint["trigger"]
        ]
        triggered: list[dict[str, Any]] = []

        async def action(run_variables: dict[str, Any], context: Any = None) -> None:
            triggered.append(run_variables["trigger"])

        hass.states.async_set(entity_id, ring_1, {"call_id": "0badc0de-1"})
        remove = await async_initialize_triggers(
            hass, await async_validate_trigger_config(hass, trigger), action,
            "automation", "doorbell", lambda *args, **kwargs: None,
        )

        async def states(*values: str | None) -> None:
            for value in values:
                if value is None:
                    hass.states.async_remove(entity_id)
                else:
                    hass.states.async_set(entity_id, value, {"call_id": "0badc0de-2"})
                await hass.async_block_till_done()

        def runs() -> list[str]:
            # The automation runs when its condition passes with the variables
            # the blueprint takes from the trigger (the entry id is known here).
            # A variable that fails to render fails the run with an error.
            condition = Template(blueprint["condition"][0]["value_template"], hass)
            started = []
            for item in triggered:
                variables = {
                    name: Template(template, hass).async_render({"trigger": item})
                    for name, template in blueprint["variables"].items() if "trigger." in str(template)
                }
                variables["entry_id"] = "01JENTRY"
                if async_template(hass, condition, variables, trace_result=False):
                    started.append(item["to_state"].state)
            return started

        # A reload or restart: unavailable, then without a previous state or
        # with the restored one.
        await states("unavailable", "unknown")
        await states("unavailable", ring_1)
        await states("unavailable", "unknown", "unavailable", ring_1)
        # The entity is deleted (its stale unit device was removed) and comes
        # back: Home Assistant's state trigger fires for the removed state.
        await states(None, "unknown", None, "unavailable", ring_1)
        assert runs() == [], filename
        # A ring is a new event time.
        await states(ring_2)
        assert runs() == [ring_2], filename
        assert remove is not None
        remove()
        await hass.async_stop(force=True)

    asyncio.run(run())
