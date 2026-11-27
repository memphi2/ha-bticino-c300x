from __future__ import annotations

from custom_components.bticino_c300x.event_payload import agent_event_key


def test_agent_event_key_reads_the_stable_event_type() -> None:
    assert agent_event_key({"event_type": "doorbell_pressed"}) == "doorbell_pressed"
    assert agent_event_key({"event_type": "door_unlock_started"}) == "door_unlock_started"
    # The bus carries the stable key only; the agent's dotted name is not one.
    assert agent_event_key({"event_type": "door_unlock.started"}) is None


def test_agent_event_key_does_not_treat_display_label_as_machine_key() -> None:
    data = {"event_type": "Türöffner gestartet"}

    assert agent_event_key(data) is None


def test_every_event_has_a_label_in_every_language() -> None:
    from custom_components.bticino_c300x.capabilities import EVENT_LABELS

    assert set(EVENT_LABELS) == {"en", "de", "it", "fr", "es"}
    for labels in EVENT_LABELS.values():
        assert set(labels) == set(EVENT_LABELS["en"])
