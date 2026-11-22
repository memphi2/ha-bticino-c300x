.pragma library

function label(language, key) {
    var labels = {
        en: {settings: "Settings", tone: "Key tone"},
        de: {settings: "Einstellungen", tone: "Tastenton"},
        it: {settings: "Impostazioni", tone: "Suono tasti"},
        fr: {settings: "Parametres", tone: "Son des touches"}
    }
    var code = String(language).slice(0, 2).toLowerCase()
    return (labels[code] || labels.en)[key] || key
}
