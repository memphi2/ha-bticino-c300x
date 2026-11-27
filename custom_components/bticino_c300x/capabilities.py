"""Capability helpers for the BTicino C300X integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .const import CONF_DEVICE_UI_ENABLED
from .display_activation import display_activation_confirmed
from .display_support import entry_display_supported
from .event_types import (
    ACTIVATION_EVENTS,
    ALWAYS_REGISTERED_EVENTS,
    ANSWERING_MACHINE_EVENTS,
    CALL_EVENTS,
    DIAGNOSTICS_EVENTS,
    DOOR_UNLOCK_EVENTS,
    DOORBELL_EVENTS,
    DOORBELL_VIDEO_EVENTS,
    HA_EVENT_TYPES,
    HOME_CALL_EVENTS,
    MEMO_EVENTS,
    OUTDOOR_UNIT_EVENTS,
    RINGER_EVENTS,
    SMARTPHONE_FORWARDING_EVENTS,
    STAIR_LIGHT_EVENTS,
    SYSTEM_METRICS_EVENTS,
    TOUCH_TONE_EVENTS,
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
        "stair_light_released": "Stair light released",
        "activation_executed": "Device activation executed",
        "call_caller_identified": "Calling unit identified",
        "call_answered": "Call answered",
        "call_view_started": "Outdoor unit view started",
        "call_ended": "Call ended",
        "outdoor_units_changed": "Outdoor units changed",
        "home_call_started": "Home call started",
        "home_call_answered": "Home call answered",
        "home_call_ended": "Home call ended",
        "ringer_muted": "Ringer muted",
        "display_touch_tone_changed": "Touch tone changed",
        "ringer_unmuted": "Ringer unmuted",
        "ringer_volume_changed": "Ringer volume changed",
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
        "stair_light_released": "Treppenlicht freigegeben",
        "activation_executed": "Geräteaktion ausgeführt",
        "call_caller_identified": "Rufende Außenstelle erkannt",
        "call_answered": "Anruf angenommen",
        "call_view_started": "Außenstellen-Ansicht gestartet",
        "call_ended": "Anruf beendet",
        "outdoor_units_changed": "Außenstellen geändert",
        "home_call_started": "Zuhause-Anruf gestartet",
        "home_call_answered": "Zuhause-Anruf angenommen",
        "home_call_ended": "Zuhause-Anruf beendet",
        "ringer_muted": "Klingelton stummgeschaltet",
        "display_touch_tone_changed": "Tastenton geändert",
        "ringer_unmuted": "Klingelton aktiviert",
        "ringer_volume_changed": "Klingel-Lautstärke geändert",
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
        "stair_light_released": "Luce scale rilasciata",
        "activation_executed": "Attivazione dispositivo eseguita",
        "call_caller_identified": "Posto esterno chiamante riconosciuto",
        "call_answered": "Chiamata risposta",
        "call_view_started": "Vista del posto esterno avviata",
        "call_ended": "Chiamata terminata",
        "outdoor_units_changed": "Posti esterni modificati",
        "home_call_started": "Chiamata casa avviata",
        "home_call_answered": "Chiamata casa risposta",
        "home_call_ended": "Chiamata casa terminata",
        "ringer_muted": "Suoneria disattivata",
        "display_touch_tone_changed": "Suono dei tasti modificato",
        "ringer_unmuted": "Suoneria attivata",
        "ringer_volume_changed": "Volume suoneria modificato",
        "smartphone_forwarding_changed": "Inoltro smartphone modificato",
        "answering_machine_messages_changed": "Messaggi video aggiornati",
        "memos_changed": "Memo aggiornati",
        "system_metrics_changed": "Metriche di sistema aggiornate",
        "agent_diagnostics_changed": "Diagnostica scritture agent aggiornata",
        "agent_restarted": "Device-Agent riavviato",
    },
    "fr": {
        "doorbell_pressed": "Sonnette appuyée",
        "doorbell_view_requested": "Vue caméra de la sonnette demandée",
        "doorbell_media_closed": "Flux caméra de la sonnette terminé",
        "door_unlock_started": "Ouverture de la porte démarrée",
        "door_unlock_ended": "Ouverture de la porte terminée",
        "stair_light_activated": "Lumière d'escalier activée",
        "stair_light_released": "Lumière d'escalier relâchée",
        "activation_executed": "Activation de l'appareil exécutée",
        "call_caller_identified": "Platine de rue appelante identifiée",
        "call_answered": "Appel décroché",
        "call_view_started": "Vue de la platine de rue démarrée",
        "call_ended": "Appel terminé",
        "outdoor_units_changed": "Platines de rue modifiées",
        "home_call_started": "Appel domicile démarré",
        "home_call_answered": "Appel domicile décroché",
        "home_call_ended": "Appel domicile terminé",
        "ringer_muted": "Sonnerie coupée",
        "display_touch_tone_changed": "Son des touches modifié",
        "ringer_unmuted": "Sonnerie activée",
        "ringer_volume_changed": "Volume de la sonnerie modifié",
        "smartphone_forwarding_changed": "Renvoi vers le smartphone modifié",
        "answering_machine_messages_changed": "Messages vidéo mis à jour",
        "memos_changed": "Mémos mis à jour",
        "system_metrics_changed": "Métriques système mises à jour",
        "agent_diagnostics_changed": "Diagnostic des écritures de l'agent mis à jour",
        "agent_restarted": "Agent redémarré",
    },
    "es": {
        "doorbell_pressed": "Timbre pulsado",
        "doorbell_view_requested": "Vista del timbre solicitada",
        "doorbell_media_closed": "Transmisión de la cámara del timbre finalizada",
        "door_unlock_started": "Apertura de puerta iniciada",
        "door_unlock_ended": "Apertura de puerta finalizada",
        "stair_light_activated": "Luz de escalera activada",
        "stair_light_released": "Luz de escalera liberada",
        "activation_executed": "Activación del dispositivo ejecutada",
        "call_caller_identified": "Placa exterior que llama identificada",
        "call_answered": "Llamada respondida",
        "call_view_started": "Vista de la placa exterior iniciada",
        "call_ended": "Llamada finalizada",
        "outdoor_units_changed": "Placas exteriores cambiadas",
        "home_call_started": "Home Call iniciada",
        "home_call_answered": "Home Call respondida",
        "home_call_ended": "Home Call finalizada",
        "ringer_muted": "Timbre silenciado",
        "display_touch_tone_changed": "Tono de teclas cambiado",
        "ringer_unmuted": "Sonido del timbre activado",
        "ringer_volume_changed": "Volumen del timbre cambiado",
        "smartphone_forwarding_changed": "Desvío al smartphone cambiado",
        "answering_machine_messages_changed": "Mensajes de vídeo cambiados",
        "memos_changed": "Notas cambiadas",
        "system_metrics_changed": "Métricas del sistema actualizadas",
        "agent_diagnostics_changed": "Diagnóstico de escrituras del agente actualizado",
        "agent_restarted": "Agente reiniciado",
    },
}
_CAPABILITY_EVENT_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("doorbell_events", DOORBELL_EVENTS),
    ("doorbell_video", DOORBELL_VIDEO_EVENTS),
    ("locks", DOOR_UNLOCK_EVENTS),
    ("stair_light", STAIR_LIGHT_EVENTS),
    ("activations", ACTIVATION_EVENTS),
    ("calls", CALL_EVENTS),
    ("outdoor_units", OUTDOOR_UNIT_EVENTS),
    ("home_call", HOME_CALL_EVENTS),
    ("ringer", RINGER_EVENTS),
    ("touch_tone", TOUCH_TONE_EVENTS),
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
    if language_code.startswith("fr"):
        return "fr"
    if language_code.startswith("es"):
        return "es"
    return "en"


def capability_is_supported(capabilities: Mapping[str, Any], capability: str) -> bool:
    """Return true when the device agent reports support for a capability."""

    value = capabilities.get(capability) if isinstance(capabilities, Mapping) else None
    if isinstance(value, dict):
        return bool(value.get("supported"))
    return bool(value)


def gate_capabilities(
    capabilities: dict[str, Any],
    *,
    doorbell_video_enabled: bool,
    c100x: bool = False,
) -> dict[str, Any]:
    """Apply HA config gates to device-agent capabilities."""

    result = dict(capabilities) if isinstance(capabilities, dict) else {}
    if c100x:
        # The station has no page for text memos and records no voice memos:
        # no memo sensor, no memo event and no memo service on a C100X.
        memos = result.get("memos")
        result["memos"] = {**memos, "supported": False} if isinstance(memos, dict) else False
    if not doorbell_video_enabled:
        for capability in ("doorbell_video", "home_call"):
            video = result.get(capability)
            if isinstance(video, dict):
                result[capability] = {**video, "supported": False}
            else:
                result[capability] = False
    return result


def ringer_mute_supported(capabilities: Mapping[str, Any]) -> bool:
    """Keep legacy read/mute support, but honor an explicit mute exclusion."""

    ringer = capabilities.get("ringer")
    return capability_is_supported(capabilities, "ringer") and (
        not isinstance(ringer, Mapping) or ringer.get("mute", True) is True
    )


def entry_gui_function_patch_active(entry: Any) -> bool:
    """Return true when the loaded entry reports the full C300X Display patch."""

    runtime_data = getattr(entry, "runtime_data", None)
    status = getattr(runtime_data, "qml_patch_status", {})
    return entry_display_supported(entry) and qml_patch_status_is_active(status)


def entry_device_ui_configured(entry: Any) -> bool | None:
    """Return the explicit HA device-UI setting or ``None`` when it is unknown."""

    # Mapping, not dict: a real ConfigEntry exposes data/options as
    # MappingProxyType, so a dict check answers "unknown" for every production
    # entry -- which made the device-UI setting unreadable.
    options = getattr(entry, "options", {})
    if isinstance(options, Mapping) and CONF_DEVICE_UI_ENABLED in options:
        return bool(options[CONF_DEVICE_UI_ENABLED])
    data = getattr(entry, "data", {})
    if isinstance(data, Mapping) and CONF_DEVICE_UI_ENABLED in data:
        return bool(data[CONF_DEVICE_UI_ENABLED])
    return None


def entry_device_ui_enabled(entry: Any) -> bool:
    """Return the effective HA setting for C300X device UI integration."""

    return entry_display_supported(entry) and bool(entry_device_ui_configured(entry))


def entry_device_ui_effective(entry: Any) -> bool | None:
    """Prefer an explicit choice; only a confirmed patch state resolves a legacy entry."""

    if not entry_display_supported(entry):
        return False
    configured = entry_device_ui_configured(entry)
    if configured is not None:
        return configured
    status = getattr(getattr(entry, "runtime_data", None), "qml_patch_status", None)
    patched = status.get("patched") if isinstance(status, dict) else None
    return patched if isinstance(patched, bool) else None


def entry_device_ui_enabled_or_patch_active(entry: Any) -> bool:
    """Return true when device UI is enabled or an older entry has an active patch."""
    return entry_device_ui_effective(entry) is True


def qml_patch_status_is_active(status: Any) -> bool:
    """Return true only for a complete, active C300X Display patch."""

    return (
        isinstance(status, dict)
        and status.get("patched") is True
        and display_activation_confirmed(status)
    )


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
    capabilities: Mapping[str, Any],
    action: str,
) -> bool:
    """Return true when the device agent advertises a maintenance action."""

    maintenance = (
        capabilities.get("maintenance") if isinstance(capabilities, Mapping) else None
    )
    return bool(
        isinstance(maintenance, dict)
        and maintenance.get("supported")
        and maintenance.get(action)
    )


def entry_maintenance_action_is_advertised(entry: Any, action: str) -> bool:
    """Return true when a config entry advertises a maintenance action."""

    capabilities = getattr(entry.runtime_data, "capabilities", {})
    return maintenance_action_is_advertised(capabilities, action)


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


def voice_memos_supported(capabilities: dict[str, Any]) -> bool:
    """Return true when the agent offers voice memos.

    A C100X agent reports ``voice: false``; agents before the field always
    offered them, so only an explicit false hides them.
    """

    if not memos_supported(capabilities):
        return False
    memos = capabilities.get("memos")
    return not (isinstance(memos, dict) and memos.get("voice") is False)


def stored_media_offered(capabilities: Any, kind: str) -> bool:
    """Return false when the agent reports no video messages or voice memos.

    Only a reported capability counts: capabilities that name neither keep
    the earlier behaviour of asking the agent.
    """

    if not isinstance(capabilities, dict):
        return True
    if kind == "video":
        return "answering_machine" not in capabilities or answering_machine_messages_supported(capabilities)
    return "memos" not in capabilities or voice_memos_supported(capabilities)


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


def memo_text_write_supported(capabilities: dict[str, Any]) -> bool:
    """Return true when the agent can create manual text memos."""

    value = capabilities.get("memos") if isinstance(capabilities, dict) else None
    if not isinstance(value, dict):
        return False
    return bool(value.get("supported") and value.get("write_text"))
