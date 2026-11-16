export const C300X_MEDIA_TRANSLATIONS = {
  en: {
    previous: "Older media", next: "Newer media", current: "Current view", history: "Media history",
    play: "Play", pause: "Pause", mute: "Mute", unmute: "Unmute", volume: "Volume",
    fullscreen: "Full screen", exit_fullscreen: "Exit full screen", seek: "Playback position",
    image: "Snapshot", video: "Recording", live: "Live", preview: "Preview",
    loading: "Loading media", empty: "No saved media", unavailable: "Media unavailable",
    controls: "Media controls",
  },
  de: {
    previous: "\u00c4ltere Medien", next: "Neuere Medien", current: "Aktuelle Ansicht", history: "Medienverlauf",
    play: "Wiedergabe", pause: "Pause", mute: "Stummschalten", unmute: "Ton einschalten", volume: "Lautst\u00e4rke",
    fullscreen: "Vollbild", exit_fullscreen: "Vollbild beenden", seek: "Wiedergabeposition",
    image: "Schnappschuss", video: "Aufnahme", live: "Live", preview: "Vorschau",
    loading: "Medien werden geladen", empty: "Keine gespeicherten Medien", unavailable: "Medien nicht verf\u00fcgbar",
    controls: "Mediensteuerung",
  },
  fr: {
    previous: "M\u00e9dias plus anciens", next: "M\u00e9dias plus r\u00e9cents", current: "Vue actuelle", history: "Historique des m\u00e9dias",
    play: "Lire", pause: "Pause", mute: "Couper le son", unmute: "Activer le son", volume: "Volume",
    fullscreen: "Plein \u00e9cran", exit_fullscreen: "Quitter le plein \u00e9cran", seek: "Position de lecture",
    image: "Instantan\u00e9", video: "Enregistrement", live: "Direct", preview: "Aper\u00e7u",
    loading: "Chargement du m\u00e9dia", empty: "Aucun m\u00e9dia enregistr\u00e9", unavailable: "M\u00e9dia indisponible",
    controls: "Commandes multim\u00e9dias",
  },
  it: {
    previous: "Media precedenti", next: "Media successivi", current: "Vista attuale", history: "Cronologia media",
    play: "Riproduci", pause: "Pausa", mute: "Disattiva audio", unmute: "Attiva audio", volume: "Volume",
    fullscreen: "Schermo intero", exit_fullscreen: "Esci da schermo intero", seek: "Posizione di riproduzione",
    image: "Istantanea", video: "Registrazione", live: "Diretta", preview: "Anteprima",
    loading: "Caricamento media", empty: "Nessun media salvato", unavailable: "Media non disponibili",
    controls: "Controlli multimediali",
  },
};

export function mediaLanguage(hass) {
  return String(hass?.language || hass?.locale?.language || "en").toLowerCase().split("-")[0];
}

export function mediaLocalize(hass, key) {
  return C300X_MEDIA_TRANSLATIONS[mediaLanguage(hass)]?.[key] || C300X_MEDIA_TRANSLATIONS.en[key] || key;
}

export function mediaDate(hass, at) {
  const date = new Date(at * 1000);
  const language = hass?.language || hass?.locale?.language || "en";
  try { return date.toLocaleString(language); } catch { return date.toLocaleString("en"); }
}
