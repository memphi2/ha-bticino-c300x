.pragma library

function label(language, key) {
    var labels = {
        en: {settings: "Settings", tone: "Key tone", memos: "Text memos", refresh: "Refresh",
             loading: "Loading", loadFailed: "Loading failed", unavailable: "Unavailable", noMemos: "No text memos", truncated: "Truncated"},
        de: {settings: "Einstellungen", tone: "Tastenton", memos: "Textmemos", refresh: "Aktualisieren",
             loading: "Laden", loadFailed: "Laden fehlgeschlagen", unavailable: "Nicht verfuegbar", noMemos: "Keine Textmemos", truncated: "Gekuerzt"},
        it: {settings: "Impostazioni", tone: "Suono tasti", memos: "Memo di testo", refresh: "Aggiorna",
             loading: "Caricamento", loadFailed: "Caricamento fallito", unavailable: "Non disponibile", noMemos: "Nessun memo di testo", truncated: "Troncato"},
        fr: {settings: "Parametres", tone: "Son des touches", memos: "Memos texte", refresh: "Actualiser",
             loading: "Chargement", loadFailed: "Echec du chargement", unavailable: "Indisponible", noMemos: "Aucun memo texte", truncated: "Tronque"}
    }
    var code = String(language).slice(0, 2).toLowerCase()
    return (labels[code] || labels.en)[key] || key
}
