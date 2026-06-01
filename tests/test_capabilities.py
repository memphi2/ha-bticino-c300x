from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.bticino_c300x import (
    _entry_config_value,
    _entry_platforms,
    async_migrate_entry,
)
from custom_components.bticino_c300x.capabilities import (
    auth_config_supported,
    event_label,
    events_for_capabilities,
    gate_capabilities,
    ha_event_types_for_capabilities,
)
from custom_components.bticino_c300x.const import (
    CONF_AGENT_HOST,
    CONF_AGENT_TOKEN,
    CONF_EVENT_WEBHOOK_ID,
    CONF_EVENT_WEBHOOK_TOKEN,
    CONF_MAINTENANCE_TOKEN,
    CONF_SHARED_SECRET,
    CONF_VIDEO_ENABLED,
    CONF_WEBHOOK_ID,
)


def test_events_for_capabilities_keeps_only_supported_event_groups() -> None:
    assert events_for_capabilities(
        {
            "doorbell_events": True,
            "doorbell_video": {"supported": True},
            "locks": False,
            "call_events": {"supported": False},
        }
    ) == [
        "doorbell.pressed",
        "doorbell.view_requested",
        "doorbell.media.closed",
        "agent.restarted",
    ]


def test_events_for_capabilities_includes_future_real_capabilities() -> None:
    assert events_for_capabilities(
        {
            "locks": {"supported": True},
            "stair_light": {"supported": True},
            "call_events": True,
            "ringer": True,
            "smartphone_forwarding": {"supported": True},
        }
    ) == [
        "door_unlock.started",
        "door_unlock.ended",
        "stair_light.activated",
        "call.started",
        "call.ended",
        "ringer.muted",
        "ringer.unmuted",
        "smartphone_forwarding.changed",
        "agent.restarted",
    ]


def test_events_for_capabilities_includes_voicemail_message_changes() -> None:
    assert events_for_capabilities(
        {
            "answering_machine": {
                "supported": True,
                "messages": {"supported": True},
            },
        }
    ) == [
        "answering_machine.messages_changed",
        "agent.restarted",
    ]


def test_events_for_capabilities_includes_manual_memo_changes() -> None:
    assert events_for_capabilities({"memos": {"supported": True}}) == [
        "memos.changed",
        "agent.restarted",
    ]


def test_events_for_capabilities_registers_system_metrics_push() -> None:
    assert events_for_capabilities({"system_metrics": {"supported": True}}) == [
        "system.metrics_changed",
        "agent.restarted",
    ]


def test_events_for_capabilities_registers_internal_diagnostics_push() -> None:
    capabilities = {"diagnostics": {"supported": True, "writes": True}}

    assert events_for_capabilities(capabilities) == [
        "agent.diagnostics_changed",
        "agent.restarted",
    ]
    assert ha_event_types_for_capabilities(capabilities) == ["agent_restarted"]


def test_entry_config_value_honors_blank_option_override() -> None:
    entry = SimpleNamespace(
        data={CONF_MAINTENANCE_TOKEN: "old-token"},
        options={CONF_MAINTENANCE_TOKEN: ""},
    )

    assert _entry_config_value(entry, CONF_MAINTENANCE_TOKEN, "") == ""


def test_migrate_entry_repairs_update_shape_without_overwriting_optional_blanks() -> None:
    class FakeConfigEntries:
        def __init__(self) -> None:
            self.update_kwargs = None

        def async_update_entry(self, entry, **kwargs):  # noqa: ANN001
            self.update_kwargs = kwargs
            for key, value in kwargs.items():
                setattr(entry, key, value)

    hass = SimpleNamespace(config_entries=FakeConfigEntries())
    entry = SimpleNamespace(
        data={
            CONF_AGENT_HOST: "c300x.local",
            CONF_AGENT_TOKEN: "stored-token",
        },
        options={
            CONF_AGENT_HOST: "",
            CONF_AGENT_TOKEN: "",
            CONF_MAINTENANCE_TOKEN: "",
        },
        minor_version=1,
    )

    assert asyncio.run(async_migrate_entry(hass, entry)) is True

    update = hass.config_entries.update_kwargs
    assert update is not None
    assert update["minor_version"] == 2
    assert update["data"][CONF_AGENT_HOST] == "c300x.local"
    assert update["data"][CONF_AGENT_TOKEN] == "stored-token"
    assert update["data"][CONF_WEBHOOK_ID]
    assert update["data"][CONF_SHARED_SECRET]
    assert update["data"][CONF_EVENT_WEBHOOK_ID]
    assert update["data"][CONF_EVENT_WEBHOOK_TOKEN]
    assert CONF_AGENT_HOST not in update["options"]
    assert CONF_AGENT_TOKEN not in update["options"]
    assert update["options"][CONF_MAINTENANCE_TOKEN] == ""


def test_ha_event_types_for_capabilities_uses_supported_agent_events() -> None:
    assert ha_event_types_for_capabilities(
        {
            "doorbell_events": True,
            "doorbell_video": True,
            "locks": True,
            "call_events": True,
            "answering_machine": {
                "supported": True,
                "messages": {"supported": True},
            },
            "ringer": True,
            "smartphone_forwarding": True,
            "stair_light": True,
            "memos": True,
            "system_metrics": True,
            "diagnostics": True,
        }
    ) == [
        "doorbell_pressed",
        "doorbell_view_requested",
        "doorbell_media_closed",
        "door_unlock_started",
        "door_unlock_ended",
        "stair_light_activated",
        "call_started",
        "call_ended",
        "ringer_muted",
        "ringer_unmuted",
        "smartphone_forwarding_changed",
        "answering_machine_messages_changed",
        "memos_changed",
        "agent_restarted",
    ]


def test_event_label_returns_localized_event_names() -> None:
    assert event_label("door_unlock_started", "en") == "Door unlock started"
    assert event_label("door_unlock_started", "de") == "Türöffner gestartet"
    assert event_label("door_unlock_started", "it") == "Apertura porta avviata"
    assert event_label("stair_light_activated", "de") == "Treppenlicht aktiviert"
    assert event_label("ringer_unmuted", "de") == "Klingelton aktiviert"
    assert event_label("smartphone_forwarding_changed", "it") == (
        "Inoltro smartphone modificato"
    )
    assert event_label("doorbell_media_closed", "de") == "Türkamera-Stream beendet"
    assert event_label("memos_changed", "de") == "Memos aktualisiert"
    assert event_label("answering_machine_messages_changed", "de") == (
        "Video-Nachrichten aktualisiert"
    )
    assert event_label("door_unlock_started", "de-DE") == "Türöffner gestartet"
    assert event_label("door_unlock_started", "it-IT") == "Apertura porta avviata"
    assert event_label("door_unlock_started", "fr") == "Door unlock started"


def test_gate_capabilities_disables_doorbell_video_when_ha_option_is_off() -> None:
    capabilities = {
        "doorbell_events": True,
        "doorbell_video": {"supported": True, "stream_path": "/doorbell-video"},
    }

    gated = gate_capabilities(capabilities, doorbell_video_enabled=False)

    assert gated["doorbell_events"] is True
    assert gated["doorbell_video"] == {
        "supported": False,
        "stream_path": "/doorbell-video",
    }
    assert capabilities["doorbell_video"]["supported"] is True
    assert events_for_capabilities(gated) == [
        "doorbell.pressed",
        "doorbell.view_requested",
        "agent.restarted",
    ]


def test_gate_capabilities_keeps_doorbell_video_when_ha_option_is_on() -> None:
    capabilities = {"doorbell_video": True}

    assert gate_capabilities(capabilities, doorbell_video_enabled=True) == capabilities


def test_auth_config_supported_requires_configurable_agent_capability() -> None:
    assert auth_config_supported({"auth": {"supported": True, "configurable": True}})
    assert not auth_config_supported({"auth": {"supported": True, "configurable": False}})


def test_entry_platforms_allow_options_to_disable_setup_video() -> None:
    entry = SimpleNamespace(
        data={CONF_VIDEO_ENABLED: True},
        options={CONF_VIDEO_ENABLED: False},
    )

    assert "camera" not in _entry_platforms(entry, {"doorbell_video": {"supported": True}})


def test_entry_platforms_include_camera_when_effective_video_is_enabled() -> None:
    entry = SimpleNamespace(
        data={CONF_VIDEO_ENABLED: False},
        options={CONF_VIDEO_ENABLED: True},
        runtime_data=None,
    )

    assert "camera" in _entry_platforms(entry, {"doorbell_video": {"supported": True}})


def test_entry_platforms_only_include_camera_if_capability_supported() -> None:
    entry = SimpleNamespace(
        data={CONF_VIDEO_ENABLED: True},
        options={},
    )

    assert "camera" not in _entry_platforms(entry, {"doorbell_video": {"supported": False}})
