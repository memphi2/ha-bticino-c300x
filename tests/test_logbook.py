"""Logbook lines of the bus events: the device's name and the event in HA's language."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.bticino_c300x import logbook
from custom_components.bticino_c300x.const import (
    DOMAIN,
    EVENT_ACTION_RECEIVED,
    EVENT_AGENT_EVENT_RECEIVED,
)

DEVICES = {
    "device-gate": SimpleNamespace(name="Gate", name_by_user=None),
    "device-station": SimpleNamespace(name="Door station", name_by_user="Hallway"),
}


def _describers(monkeypatch: pytest.MonkeyPatch, language: str) -> dict[str, Any]:
    monkeypatch.setattr(logbook.dr, "async_get", lambda _hass: SimpleNamespace(async_get=DEVICES.get))
    hass = SimpleNamespace(
        config=SimpleNamespace(language=language),
        config_entries=SimpleNamespace(
            async_get_entry=lambda entry_id: SimpleNamespace(title="C300X") if entry_id == "entry-1" else None,
        ),
    )
    described: dict[str, Any] = {}

    def describe(domain: str, event_type: str, describer: Any) -> None:
        assert domain == DOMAIN
        described[event_type] = describer

    logbook.async_describe_events(hass, describe)  # type: ignore[arg-type]
    return described


def _event(**data: Any) -> Any:
    return SimpleNamespace(data=data)


def test_a_station_event_is_named_by_its_device_in_the_home_assistant_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    describe = _describers(monkeypatch, "de")[EVENT_AGENT_EVENT_RECEIVED]
    assert describe(_event(event_type="door_unlock_started", entry_id="entry-1", device_id="device-gate")) == {
        "name": "Gate", "message": "Türöffner gestartet",
    }
    # The name the user gave the station; the entry title without a device.
    assert describe(_event(event_type="ringer_muted", entry_id="entry-1", device_id="device-station")) == {
        "name": "Hallway", "message": "Klingelton stummgeschaltet",
    }
    assert describe(_event(event_type="agent_restarted", entry_id="entry-1", device_id=None)) == {
        "name": "C300X", "message": "Device-Agent neu gestartet",
    }
    french = _describers(monkeypatch, "fr")[EVENT_AGENT_EVENT_RECEIVED]
    assert french(_event(event_type="stair_light_activated", entry_id="entry-1", device_id="device-station"))[
        "message"
    ] == "Lumière d'escalier activée"
    english = _describers(monkeypatch, "en-GB")[EVENT_AGENT_EVENT_RECEIVED]
    assert english(_event(event_type="call_answered", entry_id="gone", device_id="gone")) == {
        "name": "BTicino", "message": "Call answered",
    }


def test_an_action_home_assistant_ran_is_logged_on_the_station(monkeypatch: pytest.MonkeyPatch) -> None:
    for language, message in (
        ("en", "Action run: garage"), ("de", "Aktion ausgeführt: garage"), ("it", "Azione eseguita: garage"),
        ("fr", "Action exécutée : garage"), ("es-ES", "Acción ejecutada: garage"), ("pt", "Action run: garage"),
    ):
        describe = _describers(monkeypatch, language)[EVENT_ACTION_RECEIVED]
        assert describe(_event(entry_id="entry-1", device_id="device-station", action_id="garage")) == {
            "name": "Hallway", "message": message,
        }
