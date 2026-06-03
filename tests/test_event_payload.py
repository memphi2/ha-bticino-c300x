from __future__ import annotations

from custom_components.bticino_c300x.event_payload import (
    action_event_display_data,
    action_event_key,
    agent_event_display_data,
    agent_event_key,
    agent_event_name,
)


def test_agent_event_display_data_keeps_key_separate_from_value() -> None:
    data = agent_event_display_data(
        {
            "event": "doorbell_view_requested",
            "event_type": "doorbell_view_requested",
        }
    )

    assert data["event"] == "Doorbell view requested"
    assert data["event_type"] == "Doorbell view requested"
    assert data["event_type_key"] == "doorbell_view_requested"
    assert data["event_value"] == "Doorbell view requested"
    assert data["event_key"] == "doorbell_view_requested"


def test_agent_event_key_prefers_stable_machine_key() -> None:
    data = {
        "event": "Türklingel gedrückt",
        "event_type": "Türklingel gedrückt",
        "event_key": "doorbell_pressed",
    }

    assert agent_event_key(data) == "doorbell_pressed"
    assert agent_event_name(data, "de") == "Türklingel gedrückt"


def test_agent_event_key_does_not_treat_display_label_as_machine_key() -> None:
    data = {
        "event": "Türöffner gestartet",
        "event_type": "Türöffner gestartet",
    }

    assert agent_event_key(data) is None


def test_agent_event_display_data_translates_technical_event_value() -> None:
    data = agent_event_display_data(
        {
            "event_key": "door_unlock_started",
            "event_value": "door_unlock_started",
        },
        "de",
    )

    assert data["event_key"] == "door_unlock_started"
    assert data["event_value"] == "Türöffner gestartet"
    assert data["event"] == "Türöffner gestartet"


def test_agent_event_display_data_translates_technical_event_value_to_french() -> None:
    data = agent_event_display_data(
        {
            "event_key": "door_unlock_started",
            "event_value": "door_unlock_started",
        },
        "fr",
    )

    assert data["event_key"] == "door_unlock_started"
    assert data["event_value"] == "Ouverture porte demarree"
    assert data["event"] == "Ouverture porte demarree"


def test_agent_event_key_converts_dot_notation() -> None:
    data = {
        "event_type": "door_unlock.started",
    }

    assert agent_event_key(data) == "door_unlock_started"
    assert agent_event_name(data, "de") == "Türöffner gestartet"


def test_action_event_display_data_maps_stair_light_action() -> None:
    data = action_event_display_data(
        {"entry_id": "entry-1", "action_id": "stair_light", "address": "10"},
        "de",
    )

    assert data["event_key"] == "stair_light_activated"
    assert data["event_value"] == "Treppenlicht aktiviert"
    assert data["address"] == "10"
    assert "event_at" in data


def test_action_event_key_maps_door_unlock_action() -> None:
    assert action_event_key({"action_id": "door_unlock"}) == "door_unlock_started"
