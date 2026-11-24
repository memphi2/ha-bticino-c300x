.pragma library

function label(language, key) {
    var labels = {
        en: {status: "Status messages", memos: "Text memos", refresh: "Refresh",
             loading: "Loading", loadFailed: "Loading failed", unavailable: "Unavailable", noMemos: "No text memos", truncated: "Truncated"},
        de: {status: "Statusmeldungen", memos: "Textmemos", refresh: "Aktualisieren",
             loading: "Laden", loadFailed: "Laden fehlgeschlagen", unavailable: "Nicht verfuegbar", noMemos: "Keine Textmemos", truncated: "Gekuerzt"},
        it: {status: "Messaggi di stato", memos: "Memo di testo", refresh: "Aggiorna",
             loading: "Caricamento", loadFailed: "Caricamento fallito", unavailable: "Non disponibile", noMemos: "Nessun memo di testo", truncated: "Troncato"},
        fr: {status: "Messages d\u0027\u00e9tat", memos: "Memos texte", refresh: "Actualiser",
             loading: "Chargement", loadFailed: "Echec du chargement", unavailable: "Indisponible", noMemos: "Aucun memo texte", truncated: "Tronque"}
    }
    var code = String(language).slice(0, 2).toLowerCase()
    return (labels[code] || labels.en)[key] || key
}
