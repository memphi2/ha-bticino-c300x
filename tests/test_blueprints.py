from __future__ import annotations

from pathlib import Path
from typing import Any

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
        "doorbell_notification.yaml",
        "doorbell_call_notification.yaml",
        "doorbell_call_mobile_dashboard.yaml",
        "ring_capture.yaml",
        "ring_capture_wyoming.yaml",
        "strict_phrase_decision.yaml",
    }

    assert {path.name for path in BLUEPRINT_DIR.glob("*.yaml")} == expected
    for filename in expected:
        data = _blueprint(filename)
        assert data["blueprint"]["domain"] == "automation"
        assert data["blueprint"]["source_url"].endswith(filename)
        assert data["mode"] in {"restart", "single"}


def test_packaged_blueprints_match_repo_blueprints() -> None:
    repo_files = {path.name for path in BLUEPRINT_DIR.glob("*.yaml")}
    package_files = {path.name for path in PACKAGED_BLUEPRINT_DIR.glob("*.yaml")}

    assert package_files == repo_files
    for filename in repo_files:
        assert (PACKAGED_BLUEPRINT_DIR / filename).read_text(
            encoding="utf-8"
        ) == (BLUEPRINT_DIR / filename).read_text(encoding="utf-8")


def test_doorbell_blueprints_trigger_on_doorbell_event() -> None:
    for filename in {
        "doorbell_notification.yaml",
        "doorbell_call_notification.yaml",
        "doorbell_call_mobile_dashboard.yaml",
        "ring_capture.yaml",
        "ring_capture_wyoming.yaml",
    }:
        trigger = _blueprint(filename)["trigger"][0]
        assert trigger == {
            "platform": "event",
            "event_type": "bticino_c300x_agent_event_received",
            "event_data": {"event_key": "doorbell_pressed"},
        }


def test_doorbell_notification_derives_camera_from_device() -> None:
    data = _blueprint("doorbell_notification.yaml")
    inputs = data["blueprint"]["input"]

    assert inputs["c300x_device"]["selector"] == {
        "device": {"integration": "bticino_c300x"}
    }
    assert "camera_entity" not in inputs
    assert "device_entities(c300x_device)" in data["variables"]["c300x_entities"]
    assert "entity_id.startswith('camera.')" in data["variables"]["camera_entity"]


def test_doorbell_call_notification_gates_on_media_readiness_and_forwarding() -> None:
    data = _blueprint("doorbell_call_notification.yaml")
    inputs = data["blueprint"]["input"]
    conditions = data["condition"]
    templates = "\n".join(condition["value_template"] for condition in conditions)

    assert inputs["c300x_device"]["selector"] == {
        "device": {"integration": "bticino_c300x"}
    }
    assert "forwarding_entity" not in inputs
    assert "media_readiness_entity" not in inputs
    assert "camera_entity" not in inputs
    assert "device_entities(c300x_device)" in data["variables"]["c300x_entities"]
    assert "'Home Assistant' in options" in data["variables"]["forwarding_entity"]
    assert "media_user_ok" in data["variables"]["media_readiness_entity"]
    assert "entity_id.startswith('camera.')" in data["variables"]["camera_entity"]
    assert "Home Assistant" in templates
    assert "homeassistant" in templates
    assert "ready" in templates
    assert "warning" in templates
    assert data["variables"]["dashboard_path"] == "dashboard_path"


def test_mobile_dashboard_blueprint_opens_dashboard_from_notification() -> None:
    data = _blueprint("doorbell_call_mobile_dashboard.yaml")
    inputs = data["blueprint"]["input"]
    wake_action = data["action"][0]
    action = data["action"][1]
    notify_data = action["data"]["data"]
    templates = "\n".join(condition["value_template"] for condition in data["condition"])
    services = [
        item["service"]
        for item in data["action"]
        if isinstance(item, dict) and "service" in item
    ]
    answer_sequence = data["action"][3]["choose"][0]["sequence"]
    hangup_sequence = data["action"][3]["choose"][1]["sequence"]
    answer_services = [
        item["service"]
        for item in answer_sequence
        if isinstance(item, dict) and "service" in item
    ]

    assert "c300x_device" in inputs
    assert "forwarding_entity" not in inputs
    assert "media_readiness_entity" not in inputs
    assert "camera_entity" not in inputs
    assert inputs["notification_channel"]["default"] == "alarm_stream"
    assert inputs["notification_media_stream"]["default"] == "alarm_stream"
    assert inputs["c300x_device"]["selector"] == {
        "device": {"integration": "bticino_c300x"}
    }
    assert data["variables"]["c300x_device"] == "c300x_device"
    assert "device_entities(c300x_device)" in data["variables"]["c300x_entities"]
    assert "'Home Assistant' in options" in data["variables"]["forwarding_entity"]
    assert "'Blocked' in options" in data["variables"]["forwarding_entity"]
    assert "media_user_ok" in data["variables"]["media_readiness_entity"]
    assert "ring_call_supported" in data["variables"]["media_readiness_entity"]
    assert "entity_id.startswith('camera.')" in data["variables"]["camera_entity"]
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
    assert notify_data["push"]["sound"] == {
        "name": "default",
        "critical": 1,
        "volume": 1,
    }
    assert notify_data["push"]["interruption-level"] == "critical"
    assert notify_data["push"]["category"] == "camera"
    assert notify_data["persistent"] is True
    assert notify_data["sticky"] == "true"
    assert notify_data["actions"] == [
        {"action": "C300X_RING_ANSWER", "title": "{{ answer_title }}"},
        {
            "action": "C300X_RING_HANGUP",
            "title": "{{ hangup_title }}",
            "destructive": True,
        },
        {"action": "URI", "title": "{{ open_title }}", "uri": "{{ dashboard_path }}"},
    ]
    assert services == ["notify_service", "notify_service"]
    assert answer_services[:3] == [
        "notify_service",
        "notify_service",
        "bticino_c300x.answer_doorbell_call",
    ]
    assert answer_sequence[0]["data"]["message"] == "clear_notification"
    assert answer_sequence[1]["data"]["message"] == "command_webview"
    assert answer_sequence[1]["data"]["data"]["command"] == "{{ dashboard_path }}"
    assert answer_sequence[3]["data"]["data"]["tag"] == "{{ active_tag }}"
    assert answer_sequence[3]["data"]["data"]["importance"] == "low"
    assert hangup_sequence[0]["service"] == "bticino_c300x.hangup_doorbell_call"
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
    assert analysis_data["capture_path"] == "{{ capture_dir }}/latest.capture.json"
    assert analysis_data["wav_path"] == "{{ capture_dir }}/latest.raw.wav"
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
