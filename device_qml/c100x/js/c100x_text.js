.pragma library

function label(language, key) {
    var labels = {
        en: {status: "Status messages"},
        de: {status: "Statusmeldungen"},
        it: {status: "Messaggi di stato"},
        fr: {status: "Messages d\u0027\u00e9tat"},
        es: {status: "Mensajes de estado"}
    }
    var code = String(language).slice(0, 2).toLowerCase()
    return (labels[code] || labels.en)[key] || key
}
