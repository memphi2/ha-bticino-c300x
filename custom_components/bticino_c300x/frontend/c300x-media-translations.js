export const C300X_MEDIA_TRANSLATIONS = {
  en: {
    picture: "Adjust camera picture", brightness: "Brightness", contrast: "Contrast", saturation: "Colour saturation",
    picture_unavailable: "Picture controls unavailable. Check that the station is showing a video call and the updated GUI patch is active.",
    previous: "Older media", next: "Newer media", history: "Media history",
    play: "Play", pause: "Pause", mute: "Mute", unmute: "Unmute", volume: "Volume",
    fullscreen: "Full screen", exit_fullscreen: "Exit full screen", seek: "Playback position",
    image: "Snapshot", video: "Recording", live: "Live",
    loading: "Loading media", empty: "No saved media", unavailable: "Media unavailable",
    controls: "Media controls", expand: "Open large view", close: "Close",
  },
  de: {
    picture: "Kamerabild einstellen", brightness: "Helligkeit", contrast: "Kontrast", saturation: "Farbsättigung",
    picture_unavailable: "Bildregler nicht verfügbar. Prüfe, ob die Station einen Videoanruf zeigt und der aktuelle GUI-Patch aktiv ist.",
    previous: "\u00c4ltere Medien", next: "Neuere Medien", history: "Medienverlauf",
    play: "Wiedergabe", pause: "Pause", mute: "Stummschalten", unmute: "Ton einschalten", volume: "Lautst\u00e4rke",
    fullscreen: "Vollbild", exit_fullscreen: "Vollbild beenden", seek: "Wiedergabeposition",
    image: "Schnappschuss", video: "Aufnahme", live: "Live",
    loading: "Medien werden geladen", empty: "Keine gespeicherten Medien", unavailable: "Medien nicht verf\u00fcgbar",
    controls: "Mediensteuerung", expand: "Gro\u00dfe Ansicht \u00f6ffnen", close: "Schlie\u00dfen",
  },
  fr: {
    picture: "Régler l’image", brightness: "Luminosité", contrast: "Contraste", saturation: "Saturation",
    picture_unavailable: "Réglages indisponibles. Vérifiez que la platine affiche un appel vidéo et que le correctif graphique est à jour.",
    previous: "M\u00e9dias plus anciens", next: "M\u00e9dias plus r\u00e9cents", history: "Historique des m\u00e9dias",
    play: "Lire", pause: "Pause", mute: "Couper le son", unmute: "Activer le son", volume: "Volume",
    fullscreen: "Plein \u00e9cran", exit_fullscreen: "Quitter le plein \u00e9cran", seek: "Position de lecture",
    image: "Instantan\u00e9", video: "Enregistrement", live: "Direct",
    loading: "Chargement du m\u00e9dia", empty: "Aucun m\u00e9dia enregistr\u00e9", unavailable: "M\u00e9dia indisponible",
    controls: "Commandes multim\u00e9dias", expand: "Ouvrir la vue agrandie", close: "Fermer",
  },
  it: {
    picture: "Regola immagine", brightness: "Luminosità", contrast: "Contrasto", saturation: "Saturazione",
    picture_unavailable: "Controlli non disponibili. Verifica che sia visualizzata una videochiamata e che la patch grafica sia aggiornata.",
    previous: "Media precedenti", next: "Media successivi", history: "Cronologia media",
    play: "Riproduci", pause: "Pausa", mute: "Disattiva audio", unmute: "Attiva audio", volume: "Volume",
    fullscreen: "Schermo intero", exit_fullscreen: "Esci da schermo intero", seek: "Posizione di riproduzione",
    image: "Istantanea", video: "Registrazione", live: "Diretta",
    loading: "Caricamento media", empty: "Nessun media salvato", unavailable: "Media non disponibili",
    controls: "Controlli multimediali", expand: "Apri la vista ingrandita", close: "Chiudi",
  },
};

export function mediaLanguage(hass) {
  return String(hass?.language || hass?.locale?.language || "en").toLowerCase().split("-")[0];
}

export function mediaLocalize(hass, key) {
  return C300X_MEDIA_TRANSLATIONS[mediaLanguage(hass)]?.[key] || C300X_MEDIA_TRANSLATIONS.en[key] || key;
}

// The time as it is written into an image: date and time in the zone of Home Assistant.
export function mediaStamp(hass, at) {
  const date = new Date(at * 1000), options = { hourCycle: "h23", year: "numeric", month: "2-digit",
    day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" };
  let parts;
  if (!Number.isFinite(date.getTime())) return "";
  try { parts = new Intl.DateTimeFormat("en-CA", { ...options, timeZone: hass?.config?.time_zone }).formatToParts(date); }
  catch { parts = new Intl.DateTimeFormat("en-CA", options).formatToParts(date); }
  const part = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
  return `${part.year}-${part.month}-${part.day} ${part.hour}:${part.minute}:${part.second}`;
}
