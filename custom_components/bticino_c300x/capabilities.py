"""Capability helpers for the BTicino C300X integration."""

from __future__ import annotations

from typing import Any

from .const import CONF_DEVICE_UI_ENABLED
from .event_types import (
    ALWAYS_REGISTERED_EVENTS,
    ANSWERING_MACHINE_EVENTS,
    CALL_EVENTS,
    DIAGNOSTICS_EVENTS,
    DOOR_UNLOCK_EVENTS,
    DOORBELL_EVENTS,
    DOORBELL_VIDEO_EVENTS,
    HA_EVENT_TYPES,
    MEMO_EVENTS,
    RINGER_EVENTS,
    SMARTPHONE_FORWARDING_EVENTS,
    STAIR_LIGHT_EVENTS,
    SYSTEM_METRICS_EVENTS,
)

LOCAL_ACTION_EVENT_TYPES = {
    "stair_light": "stair_light_activated",
}
EVENT_ENTITY_EXCLUDED_TYPES = {"agent_diagnostics_changed", "system_metrics_changed"}
EVENT_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "doorbell_pressed": "Doorbell pressed",
        "doorbell_view_requested": "Doorbell view requested",
        "doorbell_media_closed": "Doorbell camera stream ended",
        "door_unlock_started": "Door unlock started",
        "door_unlock_ended": "Door unlock ended",
        "stair_light_activated": "Stair light activated",
        "call_started": "Call started",
        "call_ended": "Call ended",
        "ringer_muted": "Ringer muted",
        "ringer_unmuted": "Ringer unmuted",
        "smartphone_forwarding_changed": "Smartphone forwarding changed",
        "answering_machine_messages_changed": "Video messages changed",
        "memos_changed": "Memos changed",
        "system_metrics_changed": "System metrics updated",
        "agent_diagnostics_changed": "Agent write diagnostics updated",
        "agent_restarted": "Agent restarted",
    },
    "de": {
        "doorbell_pressed": "Türklingel gedrückt",
        "doorbell_view_requested": "Türkamera-Ansicht gestartet",
        "doorbell_media_closed": "Türkamera-Stream beendet",
        "door_unlock_started": "Türöffner gestartet",
        "door_unlock_ended": "Türöffner beendet",
        "stair_light_activated": "Treppenlicht aktiviert",
        "call_started": "Anruf gestartet",
        "call_ended": "Anruf beendet",
        "ringer_muted": "Klingelton stummgeschaltet",
        "ringer_unmuted": "Klingelton aktiviert",
        "smartphone_forwarding_changed": "Smartphone-Weiterleitung geändert",
        "answering_machine_messages_changed": "Video-Nachrichten aktualisiert",
        "memos_changed": "Memos aktualisiert",
        "system_metrics_changed": "Systemwerte aktualisiert",
        "agent_diagnostics_changed": "Agent-Schreibdiagnose aktualisiert",
        "agent_restarted": "Device-Agent neu gestartet",
    },
    "it": {
        "doorbell_pressed": "Campanello premuto",
        "doorbell_view_requested": "Vista videocitofono avviata",
        "doorbell_media_closed": "Stream videocitofono terminato",
        "door_unlock_started": "Apertura porta avviata",
        "door_unlock_ended": "Apertura porta terminata",
        "stair_light_activated": "Luce scale attivata",
        "call_started": "Chiamata avviata",
        "call_ended": "Chiamata terminata",
        "ringer_muted": "Suoneria disattivata",
        "ringer_unmuted": "Suoneria attivata",
        "smartphone_forwarding_changed": "Inoltro smartphone modificato",
        "answering_machine_messages_changed": "Messaggi video aggiornati",
        "memos_changed": "Memo aggiornati",
        "system_metrics_changed": "Metriche di sistema aggiornate",
        "agent_diagnostics_changed": "Diagnostica scritture agent aggiornata",
        "agent_restarted": "Device-Agent riavviato",
    },
}
_CAPABILITY_EVENT_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("doorbell_events", DOORBELL_EVENTS),
    ("doorbell_video", DOORBELL_VIDEO_EVENTS),
    ("locks", DOOR_UNLOCK_EVENTS),
    ("stair_light", STAIR_LIGHT_EVENTS),
    ("call_events", CALL_EVENTS),
    ("ringer", RINGER_EVENTS),
    ("smartphone_forwarding", SMARTPHONE_FORWARDING_EVENTS),
    ("system_metrics", SYSTEM_METRICS_EVENTS),
    ("diagnostics", DIAGNOSTICS_EVENTS),
)


def event_label(event_type: str | None, language: str | None = None) -> str | None:
    """Return a human-readable label for a HA event type."""

    if event_type is None:
        return None
    labels = EVENT_LABELS[_event_label_language(language)]
    return labels.get(event_type) or EVENT_LABELS["en"].get(event_type)


def _event_label_language(language: str | None) -> str:
    language_code = str(language or "").lower()
    if language_code.startswith("de"):
        return "de"
    if language_code.startswith("it"):
        return "it"
    return "en"


def capability_is_supported(capabilities: dict[str, Any], capability: str) -> bool:
    """Return true when the device agent reports support for a capability."""

    value = capabilities.get(capability) if isinstance(capabilities, dict) else None
    if isinstance(value, dict):
        return bool(value.get("supported"))
    return bool(value)


def gate_capabilities(
    capabilities: dict[str, Any],
    *,
    doorbell_video_enabled: bool,
) -> dict[str, Any]:
    """Apply HA config gates to device-agent capabilities."""

    result = dict(capabilities) if isinstance(capabilities, dict) else {}
    if not doorbell_video_enabled:
        video = result.get("doorbell_video")
        if isinstance(video, dict):
            result["doorbell_video"] = {**video, "supported": False}
        else:
            result["doorbell_video"] = False
    return result


def entry_gui_function_patch_active(entry: Any) -> bool:
    """Return true when the loaded entry reports the full C300X GUI function patch."""

    runtime_data = getattr(entry, "runtime_data", None)
    status = getattr(runtime_data, "qml_patch_status", {})
    return qml_patch_status_is_active(status)


def entry_gui_dependent_features_active(entry: Any) -> bool:
    """Return true when HA and the device both allow GUI-coupled features."""

    return entry_device_ui_enabled(entry) and entry_gui_function_patch_active(entry)


def entry_device_ui_configured(entry: Any) -> bool | None:
    """Return the explicit HA device-UI setting or ``None`` when it is unknown."""

    options = getattr(entry, "options", {})
    if isinstance(options, dict) and CONF_DEVICE_UI_ENABLED in options:
        return bool(options[CONF_DEVICE_UI_ENABLED])
    data = getattr(entry, "data", {})
    if isinstance(data, dict) and CONF_DEVICE_UI_ENABLED in data:
        return bool(data[CONF_DEVICE_UI_ENABLED])
    return None


def entry_device_ui_enabled(entry: Any) -> bool:
    """Return the effective HA setting for C300X device UI integration."""

    return bool(entry_device_ui_configured(entry))


def entry_device_ui_enabled_or_patch_active(entry: Any) -> bool:
    """Return true when device UI is enabled or an older entry has an active patch."""

    configured = entry_device_ui_configured(entry)
    if configured is not None:
        return configured
    return entry_gui_function_patch_active(entry)


def qml_patch_status_is_active(status: Any) -> bool:
    """Return true only for a complete, active C300X GUI function patch."""

    return isinstance(status, dict) and status.get("patched") is True


def events_for_capabilities(capabilities: dict[str, Any]) -> list[str]:
    """Return device-agent push events that should be registered for HA."""

    events: list[str] = []
    for capability, capability_events in _CAPABILITY_EVENT_GROUPS:
        if capability_is_supported(capabilities, capability):
            events.extend(capability_events)
    if answering_machine_messages_supported(capabilities):
        events.extend(ANSWERING_MACHINE_EVENTS)
    if memos_supported(capabilities):
        events.extend(MEMO_EVENTS)
    events.extend(ALWAYS_REGISTERED_EVENTS)
    return events


def ha_event_types_for_capabilities(capabilities: dict[str, Any]) -> list[str]:
    """Return HA event entity event types for supported agent event groups."""

    event_types = [
        event_type
        for event_type in (
            HA_EVENT_TYPES[event] for event in events_for_capabilities(capabilities)
        )
        if event_type not in EVENT_ENTITY_EXCLUDED_TYPES
    ]
    if (
        capability_is_supported(capabilities, "stair_light")
        and LOCAL_ACTION_EVENT_TYPES["stair_light"] not in event_types
    ):
        event_types.append(LOCAL_ACTION_EVENT_TYPES["stair_light"])
    return event_types


def locks_for_capabilities(capabilities: dict[str, Any]) -> list[dict[str, str]]:
    """Return lock metadata reported by the device agent."""

    value = capabilities.get("locks") if isinstance(capabilities, dict) else None
    if not isinstance(value, dict) or not value.get("supported"):
        return []
    locks = value.get("locks")
    if not isinstance(locks, list):
        default_id = str(value.get("default_id") or "default")
        return [{"id": default_id, "name": default_id}]

    result: list[dict[str, str]] = []
    for lock in locks:
        if not isinstance(lock, dict):
            continue
        lock_id = str(lock.get("id") or "").strip()
        if not lock_id:
            continue
        result.append(
            {
                "id": lock_id,
                "name": str(lock.get("name") or lock_id).strip() or lock_id,
            }
        )
    return result


def maintenance_action_is_supported(
    capabilities: dict[str, Any],
    action: str,
    maintenance_token: str | None,
) -> bool:
    """Return true when a maintenance action is supported and authorized."""

    return bool(
        maintenance_action_is_advertised(capabilities, action)
        and str(maintenance_token or "").strip()
    )


def maintenance_action_is_advertised(
    capabilities: dict[str, Any],
    action: str,
) -> bool:
    """Return true when the device agent advertises a maintenance action."""

    maintenance = capabilities.get("maintenance") if isinstance(capabilities, dict) else None
    return bool(
        isinstance(maintenance, dict)
        and maintenance.get("supported")
        and maintenance.get(action)
    )


def answering_machine_messages_supported(capabilities: dict[str, Any]) -> bool:
    """Return true when answering-machine video message metadata is supported."""

    answering_machine = (
        capabilities.get("answering_machine")
        if isinstance(capabilities, dict)
        else None
    )
    if not isinstance(answering_machine, dict) or not answering_machine.get("supported"):
        return False
    messages = answering_machine.get("messages")
    if isinstance(messages, dict):
        return bool(messages.get("supported"))
    return bool(messages)


def answering_machine_message_delete_supported(capabilities: dict[str, Any]) -> bool:
    """Return true when the agent can delete stored video messages."""

    messages = _answering_machine_messages_capability(capabilities)
    return bool(messages and messages.get("delete"))


def answering_machine_message_media_supported(capabilities: dict[str, Any]) -> bool:
    """Return true when the agent can serve stored video messages."""

    messages = _answering_machine_messages_capability(capabilities)
    return bool(messages and messages.get("media"))


def _answering_machine_messages_capability(
    capabilities: dict[str, Any],
) -> dict[str, Any] | None:
    answering_machine = (
        capabilities.get("answering_machine")
        if isinstance(capabilities, dict)
        else None
    )
    if not isinstance(answering_machine, dict) or not answering_machine.get("supported"):
        return None
    messages = answering_machine.get("messages")
    if not isinstance(messages, dict) or not messages.get("supported"):
        return None
    return messages


def memos_supported(capabilities: dict[str, Any]) -> bool:
    """Return true when local manual memo metadata is supported."""

    return capability_is_supported(capabilities, "memos")


def diagnostics_supported(capabilities: dict[str, Any]) -> bool:
    """Return true when non-sensitive agent diagnostics are supported."""

    return capability_is_supported(capabilities, "diagnostics")


def auth_config_supported(capabilities: dict[str, Any]) -> bool:
    """Return true when the agent exposes bootstrap/auth configuration control."""

    auth = capabilities.get("auth") if isinstance(capabilities, dict) else None
    return bool(
        isinstance(auth, dict)
        and auth.get("supported")
        and auth.get("configurable")
    )


def memo_delete_supported(capabilities: dict[str, Any]) -> bool:
    """Return true when the agent can delete manual memos."""

    value = capabilities.get("memos") if isinstance(capabilities, dict) else None
    if not isinstance(value, dict):
        return False
    return bool(value.get("supported") and value.get("delete"))
