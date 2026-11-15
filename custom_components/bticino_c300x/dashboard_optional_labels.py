"""Compact native-display labels for Agenda and Leave home."""

_LABELS = {
    "en": ("Agenda", "No events in the next seven days", "Calendar unavailable", "All day",
           "Leave home", "Open", "Closed", "On", "Off", "Unavailable", "Alarm", "Ready", "Not ready", "No checks selected"),
    "de": ("Termine", "Keine Termine in den n\u00e4chsten sieben Tagen", "Kalender nicht verf\u00fcgbar", "Ganzt\u00e4gig",
           "Haus verlassen", "Offen", "Geschlossen", "An", "Aus", "Nicht verf\u00fcgbar", "Alarm", "Bereit", "Nicht bereit", "Keine Pr\u00fcfungen ausgew\u00e4hlt"),
    "fr": ("Agenda", "Aucun rendez-vous dans les sept prochains jours", "Calendrier indisponible", "Toute la journ\u00e9e",
           "Quitter la maison", "Ouvert", "Ferm\u00e9", "Allum\u00e9", "\u00c9teint", "Indisponible", "Alarme", "Pr\u00eat", "Pas pr\u00eat", "Aucune v\u00e9rification s\u00e9lectionn\u00e9e"),
    "it": ("Agenda", "Nessun evento nei prossimi sette giorni", "Calendario non disponibile", "Tutto il giorno",
           "Esci di casa", "Aperto", "Chiuso", "Acceso", "Spento", "Non disponibile", "Allarme", "Pronto", "Non pronto", "Nessun controllo selezionato"),
}
_KEYS = ("agenda", "empty", "calendar_error", "all_day", "leave_home", "open", "closed",
         "on", "off", "unavailable", "alarm", "ready", "not_ready", "no_checks")


def optional_labels(language: str) -> dict[str, str]:
    labels = dict(zip(_KEYS, _LABELS.get(language, _LABELS["en"]), strict=True))
    labels["confirm"] = {"de": "Best\u00e4tigen", "fr": "Confirmer", "it": "Conferma"}.get(language, "Confirm")
    labels["cancel"] = {"de": "Abbrechen", "fr": "Annuler", "it": "Annulla"}.get(language, "Cancel")
    labels["loading"] = {"de": "Termine werden geladen", "fr": "Chargement des rendez-vous", "it": "Caricamento eventi"}.get(language, "Loading events")
    return labels
