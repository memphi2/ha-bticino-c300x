from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

pytestmark = pytest.mark.usefixtures("entity_ha_boundary")

from custom_components.bticino_c300x.binary_sensor import (  # noqa: E402
    C300XHomeCallActiveBinarySensor,
    _optional_int,
)


@dataclass
class _FakeRuntimeData:
    connection_state: Any = field(
        default_factory=lambda: SimpleNamespace(available=True)
    )
    api: Any = None


@dataclass
class _FakeEntry:
    entry_id: str = "entry-1"
    title: str = "C300X"
    runtime_data: _FakeRuntimeData = field(default_factory=_FakeRuntimeData)


def test_home_call_active_tracks_agent_state_events() -> None:
    entity = C300XHomeCallActiveBinarySensor(_FakeEntry())  # type: ignore[arg-type]
    entity.hass = SimpleNamespace()

    entity._handle_agent_event(
        SimpleNamespace(
            data={
                "entry_id": "entry-1",
                "event_key": "home_call_started",
                "data": {
                    "home_call": {
                        "running": True,
                        "active": True,
                        "answered": False,
                    }
                },
            }
        )
    )

    assert entity.is_on is True
    assert entity.extra_state_attributes["phase"] == "ringing"
    assert entity.extra_state_attributes["answered"] is False

    entity._handle_agent_event(
        SimpleNamespace(
            data={
                "entry_id": "entry-1",
                "event_key": "home_call_answered",
                "data": {
                    "home_call": {
                        "running": True,
                        "active": True,
                        "answered": True,
                        "rtp_proxy": True,
                        "target_audio_port": 41528,
                    }
                },
            }
        )
    )

    assert entity.is_on is True
    assert entity.extra_state_attributes["phase"] == "answered"
    assert entity.extra_state_attributes["answered"] is True
    assert entity.extra_state_attributes["rtp_proxy"] is True
    assert entity.extra_state_attributes["target_audio_port"] == 41528

    entity._handle_agent_event(
        SimpleNamespace(
            data={
                "entry_id": "entry-1",
                "event_key": "home_call_ended",
                "data": {"home_call": {"rtp_packets": 3, "rtcp_packets": 1}},
            }
        )
    )

    assert entity.is_on is False
    assert entity.extra_state_attributes == {
        "phase": "idle",
        "answered": False,
        "rtp_proxy": False,
        "rtp_packets": 3,
        "rtcp_packets": 1,
        "target_audio_port": 0,
    }


def test_home_call_active_ignores_unrelated_events_and_reports_errors() -> None:
    entity = C300XHomeCallActiveBinarySensor(_FakeEntry())  # type: ignore[arg-type]

    entity._handle_agent_event(
        SimpleNamespace(
            data={
                "entry_id": "other-entry",
                "event_key": "home_call_started",
                "data": {"home_call": {"running": True}},
            }
        )
    )
    entity._handle_agent_event(
        SimpleNamespace(
            data={
                "entry_id": "entry-1",
                "event_key": "doorbell_pressed",
                "data": {"home_call": {"running": True}},
            }
        )
    )

    assert entity.is_on is False
    assert not hasattr(entity, "wrote_state")

    entity._apply_status(
        {
            "running": True,
            "active": False,
            "answered": False,
            "rtp_packets": "bad",
            "rtcp_packets": "2",
            "target_audio_port": "",
            "last_error": 503,
        }
    )

    assert entity.is_on is True
    assert entity.extra_state_attributes["phase"] == "ringing"
    assert entity.extra_state_attributes["rtp_packets"] == 0
    assert entity.extra_state_attributes["rtcp_packets"] == 2
    assert entity.extra_state_attributes["last_error"] == "503"


def test_home_call_optional_int_falls_back_for_invalid_values() -> None:
    assert _optional_int("123") == 123
    assert _optional_int(None, 7) == 7
    assert _optional_int("bad", 5) == 5
