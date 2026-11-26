"""Display texts are spelled properly: umlauts and accents, no ASCII stand-ins.

The station's Qt 4.8 reads QML and JavaScript files as UTF-8 and its Ubuntu
font has these letters, so "fuer", "Umidita" or "echouee" are plain spelling
mistakes on the screen.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEVICE = ROOT / "device_qml"
# Letters the firmware font was checked to draw (Qt 4.8.7 probe, Ubuntu Light).
# The Spanish ones have a glyph in the cmap of Ubuntu-L.ttf on 1.7.19, 2.0.2,
# 3.0.6 and the C100X 1.5.8, and the vendor's own Spanish texts use them.
LETTERS = set("äöüÄÖÜßàèéìòùâêîôûçœÀÈÉáíóúñÁÍÓÚÑ¿¡")

DUMP = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({});
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8').replace(/^\.pragma library\s*/, '')
    + ';this.out = {CONTROL_LABELS: CONTROL_LABELS, DETAIL_LABELS: DETAIL_LABELS}', context);
const result = {};
for (const language of ['de', 'en', 'it', 'fr', 'es']) {
    result[language] = Object.assign({}, context.catalog(language));
    for (const [key, value] of Object.entries(context.weatherCatalog(language))) result[language]['weather.' + key] = value;
    for (const table of ['CONTROL_LABELS', 'DETAIL_LABELS']) {
        for (const [key, value] of Object.entries(context.out[table][language])) result[language][table + '.' + key] = value;
    }
}
console.log(JSON.stringify(result));
"""


@pytest.fixture(scope="module")
def texts():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    result = subprocess.run([node, "-e", DUMP, str(DEVICE / "js/c300x_i18n.js")],
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_texts_use_umlauts_and_accents(texts):
    expected = {
        "de": {
            "pin_required": "PIN benötigt", "checking": "Prüfe", "execute": "Ausführen",
            "display_settings_error": "Einstellung nicht verfügbar", "invalid_action": "Ungültige Aktion",
            "status_checking": "wird geprüft", "alert_ack_retry": "Nicht bestätigt - erneut versuchen",
            "weather.cloudy": "Bewölkt", "CONTROL_LABELS.saturation": "Sättigung",
            "DETAIL_LABELS.white_mode": "Weiß", "DETAIL_LABELS.close_valve": "Schließen",
            "DETAIL_LABELS.open": "Öffnen", "DETAIL_LABELS.color_green": "Grün",
            "DETAIL_LABELS.mode_reverse": "Rückwärts", "DETAIL_LABELS.volume_level": "Lautstärke",
        },
        "it": {
            "humidity": "Umidità", "CONTROL_LABELS.brightness": "Luminosità", "CONTROL_LABELS.hvac_mode": "Modalità",
            "DETAIL_LABELS.percentage": "Velocità", "DETAIL_LABELS.activity_unknown": "Attività sconosciuta",
            "bridge_not_registered": "Home Assistant non si è registrato dall'avvio dell'agente.",
        },
        "fr": {
            "ha_feedback_colors": "Messages d'état", "maintenance_reboot": "Redémarrer",
            "maintenance_timeout": "Délai dépassé", "disarmed": "Désarmé", "ready_to_arm": "Prêt",
            "off": "Arrêt", "weather": "Météo", "weather.hail": "Grêle", "execute": "Exécuter",
            "status_loaded": "chargée", "contact_now": "à l'instant", "CONTROL_LABELS.brightness": "Luminosité",
            "DETAIL_LABELS.current_state": "État actuel", "DETAIL_LABELS.activity_closed": "Fermé",
            "DETAIL_LABELS.confirm": "Sûr ?", "DETAIL_LABELS.start": "Démarrer",
        },
        "es": {
            "maintenance_confirm_reboot": "¿Reiniciar el videoportero ahora?\nNo estará accesible durante un minuto aproximadamente.",
            "status_contact": "Último contacto", "status_address": "Dirección", "contact_days": "hace %1 días",
            "setting_nav": "Cambio de página", "action": "Acción", "humidity": "Humedad", "more": "Más",
            "offline": "Sin conexión", "weather.partlycloudy": "Parcialmente nublado",
            "CONTROL_LABELS.saturation": "Saturación", "CONTROL_LABELS.target_temp_low": "Consigna mínima",
            "DETAIL_LABELS.battery_level": "Batería", "DETAIL_LABELS.confirm": "¿Seguro?",
            "DETAIL_LABELS.mode_auto": "Automático", "DETAIL_LABELS.mode_reverse": "Atrás",
        },
    }
    for language, pairs in expected.items():
        for key, value in pairs.items():
            assert texts[language][key] == value, (language, key)
    assert texts["de"]["bridge_unreachable"] == (
        "Home Assistant antwortet nicht. Adresse von Home Assistant für das C300X prüfen: "
        "http, oder https mit gültigem Zertifikat."
    )


# The stand-ins that were in use, as whole words.
FORMER = {
    "it": ["sara", "Umidita", "Luminosita", "Tonalita", "Modalita", "Velocita", "Attivita"],
    "fr": ["Redemarrer", "retires", "retabli", "Delai", "depasse", "acceptee", "confirme", "reessayer", "etat",
           "Etat", "repond", "Verifier", "verifier", "enregistre", "demarrage", "verification", "Verification",
           "fleches", "Reglage", "Reglages", "echouee", "envoyee", "configuree", "Present", "charge", "element",
           "Desarme", "Executer", "connecte", "Humidite", "configure", "pret", "Pret", "Arret", "Lumiere",
           "echoue", "Meteo", "Grele", "Luminosite", "Temperature", "Prereglage", "Eclairement", "Aleatoire",
           "Repeter", "Deverrouiller", "Demarrer", "Deshumidification", "Degivrage", "Prechauffage", "Activite",
           "Ferme", "Deshumidifier"],
}
GERMAN_STAND_IN = re.compile(r"ae|oe|(?<![aeqQ])ue|Ae|Oe|Ue|(?<=[Ww]ei)ss|(?<=[Ss]chlie)ss")


def test_no_ascii_stand_in_comes_back(texts):
    for key, value in texts["de"].items():
        # "aktuell" is the one word here with a real "ue".
        assert not GERMAN_STAND_IN.search(value.replace("Aktuell", "")), (key, value)
    for language, words in FORMER.items():
        for key, value in texts[language].items():
            found = [word for word in words if re.search(rf"(?<![^\W\d_]){re.escape(word)}(?![^\W\d_])", value)]
            assert not found, (language, key, value)
    script = (ROOT / "native_agent/scripts/qml_patch.sh").read_text(encoding="utf-8")
    assert "Appels renvoyés vers Home Assistant" in script and "renvoyes" not in script
    # English stays plain ASCII.
    assert all(value.isascii() for value in texts["en"].values())


def test_device_files_only_use_letters_the_station_font_has():
    seen = set()
    for path in sorted(DEVICE.rglob("*")):
        if path.suffix in {".qml", ".js"}:
            seen |= {char for char in path.read_bytes().decode("utf-8") if not char.isascii()}
    assert seen, "the display texts carry umlauts and accents"
    assert seen <= LETTERS, sorted(seen - LETTERS)


# Labels Home Assistant builds and sends to the station pages.
HA_FORMER_FR = ["Arrete", "Bloque", "Connecte", "Deconnecte", "Deverrouillage", "Deverrouille", "Ensoleille",
                "Ferme", "Fumee", "detectee", "detecte", "Grele", "Mise a jour", "Occupe", "Present", "Pret",
                "Probleme", "Sur", "Verrouille", "Energie", "Reseau", "Decharge", "Cout"]


def _label_tables():
    tables = {}
    for name in ("dashboard_labels", "dashboard_optional_labels", "dashboard_situations"):
        path = ROOT / "custom_components/bticino_c300x" / f"{name}.py"
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"^(_?[A-Z][A-Z0-9_]*_(DE|FR|IT|ES))\b[^\n]*= [{(]\n(.*?)^[})]", source, re.M | re.S):
            body = match.group(3).encode("utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8") \
                if "\\u" in match.group(3) and match.group(3).isascii() else match.group(3)
            values = [value for value in re.findall(r'"((?:[^"\\]|\\.)*)"', body)
                      if not re.fullmatch(r"[a-z0-9_.{}-]*", value)]
            tables[f"{name}.{match.group(1)}"] = (match.group(2), values)
    return tables


def test_home_assistant_side_labels_use_umlauts_and_accents():
    tables = _label_tables()
    languages = {language for language, _values in tables.values()}
    assert languages == {"DE", "FR", "IT", "ES"} and len(tables) >= 12
    source = (ROOT / "custom_components/bticino_c300x/dashboard_labels.py").read_text(encoding="utf-8")
    for proper in ("Öffnet", "Schließt", "Fährt zurück", "Lädt", "Heiß", "Läuft", "Geräusch", "Bewölkt",
                   "Verrouillé", "Déverrouillé", "Bloqué", "Fermé", "Arrêté", "Présent", "Problème",
                   "Fumée détectée", "Prêt", "Sûr", "Mise à jour",
                   "Húmedo", "Frío", "Sin conexión", "Manipulación", "Actualización", "Sin vibración"):
        assert f'"{proper}"' in source, proper
    for name, (language, values) in tables.items():
        for value in values:
            if language == "DE":
                assert not GERMAN_STAND_IN.search(value.replace("Aktuell", "")), (name, value)
            if language == "FR":
                # "charge" is a real word here ("Ne charge pas").
                found = [word for word in HA_FORMER_FR + [word for word in FORMER["fr"] if word != "charge"]
                         if re.search(rf"(?<![^\W\d_]){re.escape(word)}(?![^\W\d_])", value)]
                assert not found, (name, value)
            if language == "IT":
                found = [word for word in FORMER["it"] if re.search(rf"(?<![^\W\d_]){re.escape(word)}(?![^\W\d_])", value)]
                assert not found, (name, value)
