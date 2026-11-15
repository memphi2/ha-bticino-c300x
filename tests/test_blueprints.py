from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

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
        inputs.update(calendar="calendar.home", entry_id="entry")
        rendered = ha_yaml.substitute(source, inputs)
        assert cv.time_period(rendered["trigger"][0]["offset"]).total_seconds() == -900
        assert rendered["mode"] == "queued"
        hass = HomeAssistant(str(tmp_path))
        variables = {"trigger": {"entity_id": "calendar.home", "calendar_event": {"summary": "Visit", "start": "2026-11-10T12:00:00+00:00"}}}
        for key, value in rendered["variables"].items():
            variables[key] = Template(value, hass).async_render(variables)
        data = {key: Template(value, hass).async_render(variables) if isinstance(value, str) else value for key, value in rendered["action"][0]["data"].items()}
        from custom_components.bticino_c300x.display_notifications import SHOW_SCHEMA
        checked = SHOW_SCHEMA(data)
        assert len(checked["notification_id"]) == 64
        assert checked["title"] == "Visit"
        assert "12:00" in checked["message"]

    asyncio.run(run())


def test_doorbell_blueprints_trigger_on_doorbell_event() -> None:
    for filename in {
        "doorbell_notification.yaml",
        "doorbell_call_android.yaml",
        "doorbell_call_ios.yaml",
        "ring_capture.yaml",
        "ring_capture_wyoming.yaml",
    }:
        trigger = _blueprint(filename)["trigger"][0]
        assert trigger == {
            "platform": "event",
            "event_type": "bticino_c300x_agent_event_received",
            "event_data": {"event_key": "doorbell_pressed"},
        }


def test_doorbell_blueprints_use_event_entry_and_selected_device() -> None:
    for filename in {
        "doorbell_call_android.yaml",
        "doorbell_call_ios.yaml",
        "ring_capture.yaml",
        "ring_capture_wyoming.yaml",
    }:
        data = _blueprint(filename)
        inputs = data["blueprint"]["input"]
        first_condition = data["condition"][0]

        assert "entry_id" not in inputs
        assert (
            data["variables"]["entry_id"]
            == "{{ trigger.event.data.entry_id | default('', true) }}"
        )
        assert (
            data["variables"]["event_camera_entity"]
            == "{{ trigger.event.data.camera_entity_id | default('', true) }}"
        )
        assert first_condition == {
            "condition": "template",
            "value_template": (
                "{{ entry_id and event_camera_entity in c300x_entities }}"
            ),
        }


def test_doorbell_notification_allows_camera_less_events() -> None:
    import asyncio

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import frame
    from homeassistant.helpers.device_registry import DeviceEntry
    from homeassistant.helpers.template import Template

    data = _blueprint("doorbell_notification.yaml")
    assert "entry_id" not in data["blueprint"]["input"]

    async def run() -> None:
        hass = HomeAssistant(str(ROOT))
        selected = DeviceEntry(config_entry_id="entry_a", id="device_a")
        composite = DeviceEntry(
            config_entry_id="entry_a", id="composite",
            composite_subentries={"entry_a": {None}, "entry_b": {None}},
        )
        devices = {selected.id: selected, composite.id: composite}
        registry = SimpleNamespace(async_get=devices.get)
        template = Template(data["condition"][0]["value_template"], hass)
        # DeviceEntry compatibility properties use HA's frame reporting helper.
        # Restore its global HA reference when this isolated event loop exits.
        with (
            patch.object(frame._hass, "hass", None),
            patch("homeassistant.helpers.device_registry.async_get", return_value=registry),
        ):
            frame.async_setup(hass)
            for entry_id, camera, device, expected in (
                ("entry_a", "", "device_a", True),
                ("entry_b", "", "device_a", False),
                ("entry_a", "camera.a", "device_a", True),
                ("entry_b", "camera.b", "device_a", False),
                ("entry_b", "camera.a", "device_a", False),
                ("entry_a", "camera.b", "device_a", False),
                ("", "", "device_a", False),
                ("entry_a", "", "removed_device", False),
                ("entry_a", "", "composite", True),
                ("entry_b", "", "composite", True),
                ("entry_c", "", "composite", False),
                ("entry_b", "camera.b", "composite", True),
                ("entry_c", "camera.b", "composite", False),
            ):
                assert bool(template.async_render({
                    "entry_id": entry_id,
                    "event_camera_entity": camera,
                    "c300x_device": device,
                    "c300x_entities": ["camera.a", "camera.b"] if device == "composite" else ["camera.a"],
                })) is expected, (entry_id, camera, device)

    asyncio.run(run())


def test_doorbell_notification_derives_camera_from_device() -> None:
    data = _blueprint("doorbell_notification.yaml")
    inputs = data["blueprint"]["input"]

    assert inputs["c300x_device"]["selector"] == {
        "device": {"integration": "bticino_c300x"}
    }
    assert "camera_entity" not in inputs
    assert "entry_id" not in inputs
    assert (
        data["variables"]["entry_id"]
        == "{{ trigger.event.data.entry_id | default('', true) }}"
    )
    assert "device_entities(c300x_device)" in data["variables"]["c300x_entities"]
    assert "entity_id.startswith('camera.')" in data["variables"]["camera_entity"]


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

    assert "c300x_device" in inputs
    assert "entry_id" not in inputs
    assert "forwarding_entity" not in inputs
    assert "media_readiness_entity" not in inputs
    assert "camera_entity" not in inputs
    assert inputs["notification_channel"]["default"] == "alarm_stream"
    assert inputs["notification_media_stream"]["default"] == "alarm_stream"
    assert inputs["c300x_device"]["selector"] == {
        "device": {"integration": "bticino_c300x"}
    }
    assert data["variables"]["c300x_device"] == "c300x_device"
    assert (
        data["variables"]["entry_id"]
        == "{{ trigger.event.data.entry_id | default('', true) }}"
    )
    assert "device_entities(c300x_device)" in data["variables"]["c300x_entities"]
    assert "'Home Assistant'" not in data["variables"]["forwarding_entity"]
    assert "'homeassistant' in options and 'blocked' in options" in data["variables"]["forwarding_entity"]
    assert "media_user_ok" in data["variables"]["media_readiness_entity"]
    assert "ring_call_supported" in data["variables"]["media_readiness_entity"]
    assert "entity_id.startswith('camera.')" in data["variables"]["camera_entity"]
    assert "this.entity_id" in data["variables"]["action_scope"]
    assert data["action"][0]["variables"]["answer_action"].startswith(
        "{{ 'C300X_ANDROID_RING_ANSWER_'"
    )
    assert data["action"][0]["variables"]["hangup_action"].startswith(
        "{{ 'C300X_ANDROID_RING_HANGUP_'"
    )
    assert "dashboard_path.split('#', 1)" in data["variables"]["answer_dashboard_path"]
    assert "launch_target = event_camera_entity or camera_entity" in data["variables"]["answer_dashboard_path"]
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
        "bticino_c300x.answer_doorbell_call",
        "notify_service",
        "notify_service",
    ]
    assert answer_sequence[0]["data"] == {"entry_id": "{{ entry_id }}"}
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
    assert answer_sequence[5]["then"][0] == {
        "service": "bticino_c300x.hangup_doorbell_call",
        "data": {"entry_id": "{{ entry_id }}"},
    }
    assert hangup_sequence[0]["service"] == "bticino_c300x.hangup_doorbell_call"
    assert hangup_sequence[0]["data"] == {"entry_id": "{{ entry_id }}"}
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

    assert inputs["c300x_device"]["selector"] == {
        "device": {"integration": "bticino_c300x"}
    }
    assert "entry_id" not in inputs
    assert inputs["notify_service"]["name"] == "iOS notify service"
    assert (
        data["variables"]["entry_id"]
        == "{{ trigger.event.data.entry_id | default('', true) }}"
    )
    assert "device_entities(c300x_device)" in data["variables"]["c300x_entities"]
    assert "'homeassistant' in options and 'blocked' in options" in data["variables"]["forwarding_entity"]
    assert "media_user_ok" in data["variables"]["media_readiness_entity"]
    assert "entity_id.startswith('camera.')" in data["variables"]["camera_entity"]
    assert "this.entity_id" in data["variables"]["action_scope"]
    assert data["action"][0]["variables"]["answer_action"].startswith(
        "{{ 'C300X_IOS_RING_ANSWER_'"
    )
    assert data["action"][0]["variables"]["hangup_action"].startswith(
        "{{ 'C300X_IOS_RING_HANGUP_'"
    )
    assert "dashboard_path.split('#', 1)" in data["variables"]["answer_dashboard_path"]
    assert "launch_target = event_camera_entity or camera_entity" in data["variables"]["answer_dashboard_path"]
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
        "service": "bticino_c300x.answer_doorbell_call",
        "data": {"entry_id": "{{ entry_id }}"},
    }
    assert answer_sequence[3]["wait_for_trigger"] == [
        {
            "platform": "event",
            "event_type": "mobile_app_notification_action",
            "event_data": {"action": "{{ hangup_action }}"},
        }
    ]
    assert hangup_sequence[0] == {
        "service": "bticino_c300x.hangup_doorbell_call",
        "data": {"entry_id": "{{ entry_id }}"},
    }
    assert "homeassistant" in templates
    assert "ready" in templates
    assert "warning" in templates


def test_ring_capture_blueprint_calls_capture_without_analysis() -> None:
    data = _blueprint("ring_capture.yaml")
    inputs = data["blueprint"]["input"]
    action = data["action"]

    assert inputs["c300x_device"]["selector"] == {
        "device": {"integration": "bticino_c300x"}
    }
    assert "media_readiness_entity" not in inputs
    assert "device_entities(c300x_device)" in data["variables"]["c300x_entities"]
    assert "media_user_ok" in data["variables"]["media_readiness_entity"]
    assert len(action) == 1
    assert action[0]["service"] == "bticino_c300x.capture_doorbell_call"
    assert action[0]["data"]["wav_output_dir"] == "{{ capture_file_dir }}"
    assert "output_path" not in action[0]["data"]


def test_wyoming_blueprint_captures_then_transcribes_latest_files() -> None:
    data = _blueprint("ring_capture_wyoming.yaml")
    inputs = data["blueprint"]["input"]
    services = [action["service"] for action in data["action"]]
    capture_data = data["action"][0]["data"]
    analysis_data = data["action"][1]["data"]

    assert inputs["c300x_device"]["selector"] == {
        "device": {"integration": "bticino_c300x"}
    }
    assert "media_readiness_entity" not in inputs
    assert "device_entities(c300x_device)" in data["variables"]["c300x_entities"]
    assert "media_user_ok" in data["variables"]["media_readiness_entity"]
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
        assert "hangup_doorbell_call" not in str(default_sequence), filename


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
