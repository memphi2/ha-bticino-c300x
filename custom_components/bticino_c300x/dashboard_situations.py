"""Read-only selected household issues; no discovery, service calls or templates."""

from typing import Any

from .dashboard_optional_config import SITUATION_DOMAINS, configured_situations_page
from .dashboard_optional_labels import optional_labels

_LABELS = {
    "en": ("Situations", "No active issues in selected entities", "No entities selected", "Unknown", "Unsupported", "Opening", "Closing", "Pending: {count}"),
    "de": ("Situationen", "Keine aktiven Hinweise in der Auswahl", "Keine Entit\u00e4ten ausgew\u00e4hlt", "Unbekannt", "Nicht unterst\u00fctzt", "\u00d6ffnet", "Schlie\u00dft", "Offen: {count}"),
    "fr": ("Situations", "Aucun probl\u00e8me actif dans la s\u00e9lection", "Aucune entit\u00e9 s\u00e9lectionn\u00e9e", "Inconnu", "Non pris en charge", "Ouverture", "Fermeture", "En attente : {count}"),
    "it": ("Situazioni", "Nessun problema attivo nella selezione", "Nessuna entit\u00e0 selezionata", "Sconosciuto", "Non supportato", "Apertura", "Chiusura", "Da fare: {count}"),
}


def situations_entity_ids(entry: Any) -> tuple[str, ...]:
    settings = configured_situations_page(entry)
    return tuple(entity for field in SITUATION_DOMAINS for entity in settings[field]) if settings["enabled"] else ()


def situation_state(kind: str, state: Any) -> tuple[str, int | None]:
    """Only known inactive states clear a row; motion is not a closed garage."""
    raw = state.state if state is not None else "unavailable"
    if raw in ("unknown", "unavailable"):
        return raw, None
    if kind == "contacts":
        if state.attributes.get("device_class") not in {"door", "window", "opening", "garage_door"}:
            return "unsupported", None
        return {"on": "open", "off": "clear"}.get(raw, "unknown"), None
    if kind == "garages":
        if state.attributes.get("device_class") != "garage":
            return "unsupported", None
        return {"open": "open", "opening": "opening", "closing": "closing", "closed": "clear"}.get(raw, "unknown"), None
    if kind == "lights":
        return {"on": "on", "off": "clear"}.get(raw, "unknown"), None
    # HA todo state is the number of incomplete items. Do not interpret sensors,
    # strings containing expressions, negative values or fractional counts.
    if kind == "tasks" and isinstance(raw, str) and raw.isascii() and raw.isdecimal() and len(raw) <= 15:
        count = int(raw)
        return ("pending" if count else "clear"), count
    return "unknown", None


def situations_dashboard_page(hass: Any, entry: Any, language: str = "en") -> dict[str, Any] | None:
    settings = configured_situations_page(entry)
    if not settings["enabled"]:
        return None
    labels = optional_labels(language)
    labels.update(zip(("title", "clear", "empty", "unknown", "unsupported", "opening", "closing", "pending"),
                      _LABELS.get(language, _LABELS["en"]), strict=True))
    checks = []
    selected = 0
    for kind in SITUATION_DOMAINS:
        for entity_id in settings[kind]:
            selected += 1
            state = hass.states.get(entity_id)
            status, count = situation_state(kind, state)
            if status == "clear":
                continue
            uncertain = status in ("unknown", "unavailable", "unsupported")
            name = state.attributes.get("friendly_name") if state is not None else None
            checks.append({"name": " ".join(str(name or entity_id).split())[:80],
                           "state_label": labels[status].format(count=count),
                           "color": "#ffd166" if uncertain else "#ff6b6b"})
    return {"title": labels["title"], "situations": {
        "checks": checks, "empty_text": labels["clear" if selected else "empty"],
    }}
