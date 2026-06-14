from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.bticino_c300x import (
    _async_configure_device_activations,
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
    memo_text_write_supported,
)
from custom_components.bticino_c300x.const import (
    CONF_AGENT_HOST,
    CONF_AGENT_TOKEN,
    CONF_DEVICE_ACTIVATION_MODE,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_ADDRESS,
    CONF_EVENT_WEBHOOK_ID,
    CONF_EVENT_WEBHOOK_TOKEN,
    CONF_MAINTENANCE_TOKEN,
    CONF_SHARED_SECRET,
    CONF_VIDEO_ENABLED,
    CONF_WEBHOOK_ID,
    DEVICE_ACTIVATION_MODE_MANUAL,
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


def test_events_for_capabilities_registers_device_activations() -> None:
    assert events_for_capabilities({"activations": {"supported": True}}) == [
        "activation.executed",
        "agent.restarted",
    ]
    assert ha_event_types_for_capabilities({"activations": {"supported": True}}) == [
        "activation_executed",
        "agent_restarted",
    ]


def test_events_for_capabilities_registers_home_call_state_push() -> None:
    capabilities = {"home_call": {"supported": True, "audio_codec": "speex/8000"}}

    assert events_for_capabilities(capabilities) == [
        "home_call.started",
        "home_call.answered",
        "home_call.ended",
        "agent.restarted",
    ]
    assert ha_event_types_for_capabilities(capabilities) == [
        "home_call_started",
        "home_call_answered",
        "home_call_ended",
        "agent_restarted",
    ]


def test_memo_text_write_support_requires_agent_capability() -> None:
    assert memo_text_write_supported({"memos": {"supported": True, "write_text": True}})
    assert not memo_text_write_supported({"memos": {"supported": True}})
    assert not memo_text_write_supported({"memos": False})


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
            "activations": True,
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
        "activation_executed",
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
    assert event_label("activation_executed", "de") == "Geräteaktion ausgeführt"
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
    assert event_label("door_unlock_started", "fr") == "Ouverture porte demarree"


def test_gate_capabilities_disables_doorbell_video_when_ha_option_is_off() -> None:
    capabilities = {
        "doorbell_events": True,
        "doorbell_video": {"supported": True, "stream_path": "/doorbell-video"},
        "home_call": {"supported": True, "rtp_proxy_supported": True},
    }

    gated = gate_capabilities(capabilities, doorbell_video_enabled=False)

    assert gated["doorbell_events"] is True
    assert gated["doorbell_video"] == {
        "supported": False,
        "stream_path": "/doorbell-video",
    }
    assert gated["home_call"] == {
        "supported": False,
        "rtp_proxy_supported": True,
    }
    assert capabilities["doorbell_video"]["supported"] is True
    assert capabilities["home_call"]["supported"] is True
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


def test_configure_device_activations_writes_only_on_mismatch() -> None:
    api = _FakeActivationConfigApi(
        {
            "activations_enabled": True,
            "activations_auto_discover": True,
            "activation_stair_light_address": "",
        }
    )
    entry = SimpleNamespace(
        data={
            CONF_DEVICE_ACTIVATION_MODE: DEVICE_ACTIVATION_MODE_MANUAL,
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_ADDRESS: "12",
        },
        options={},
    )

    asyncio.run(_async_configure_device_activations(entry, api))  # type: ignore[arg-type]
    asyncio.run(_async_configure_device_activations(entry, api))  # type: ignore[arg-type]

    assert api.calls == [
        ("status",),
        ("configure", True, False, "12"),
        ("status",),
    ]


class _FakeActivationConfigApi:
    def __init__(self, status: dict[str, object]) -> None:
        self.status = dict(status)
        self.calls: list[tuple[object, ...]] = []

    async def async_auth_config_status(self) -> dict[str, object]:
        self.calls.append(("status",))
        return dict(self.status)

    async def async_configure_device_activations(
        self,
        *,
        enabled: bool,
        auto_discover: bool,
        stair_light_address: str,
    ) -> dict[str, object]:
        self.calls.append(("configure", enabled, auto_discover, stair_light_address))
        self.status.update(
            {
                "activations_enabled": enabled,
                "activations_auto_discover": auto_discover,
                "activation_stair_light_address": (
                    "" if auto_discover else stair_light_address
                ),
            }
        )
        return dict(self.status)
