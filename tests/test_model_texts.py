"""A C300X keeps every text it had; a C100X reads its own model name.

The texts name the model through ``{model}``. Rendered for a C300X, each area
must stay byte-identical to the texts before the change; the pinned digests
were taken from the translations of 04a99ea6, the exceptions with the
"station_busy" message of release 2.9.2 and the
"device_display_timeout" texts of the fixes after it added.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from homeassistant import config_entries
from homeassistant.exceptions import ServiceValidationError

from custom_components.bticino_c300x.config_flow import (
    BticinoC300XConfigFlow,
    BticinoC300XOptionsFlow,
)
from custom_components.bticino_c300x.model_names import EITHER

INTEGRATION = Path(__file__).resolve().parents[1] / "custom_components" / "bticino_c300x"
LANGUAGES = {
    "base": INTEGRATION / "strings.json",
    **{lang: INTEGRATION / "translations" / f"{lang}.json" for lang in ("en", "de", "it", "fr")},
}


def _reconfigure(path: tuple[str, ...]) -> bool:
    if path[0] == "options":
        return True
    return path[0] == "config" and (
        (path[1] == "step" and path[2].startswith("reconfigure"))
        or path[:3] == ("config", "abort", "reconfigure_successful")
    )


AREAS = {
    "setup": lambda path: path[0] == "config" and not _reconfigure(path),
    "reconfigure": _reconfigure,
    "repairs": lambda path: path[0] == "issues",
    "exceptions": lambda path: path[0] == "exceptions",
}


def _leaves(value: object, path: tuple[str, ...] = ()) -> dict[tuple[str, ...], str]:
    if isinstance(value, str):
        return {path: value}
    found: dict[tuple[str, ...], str] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            found.update(_leaves(child, (*path, key)))
    return found


def _load(lang: str) -> dict:
    return json.loads(LANGUAGES[lang].read_text(encoding="utf-8"))


def text(lang: str, *path: str, model: str) -> str:
    value: object = _load(lang)
    for key in path:
        value = value[key]  # type: ignore[index]
    assert isinstance(value, str)
    return value.replace("{model}", model)


def c300x_digest(lang: str, area: str) -> str:
    """Every text of an area as a C300X reads it; the C100X twins are not his."""

    texts = {
        "/".join(path): value.replace("{model}", "C300X")
        for path, value in _leaves(_load(lang)).items()
        if AREAS[area](path) and not any(key.endswith("_c100x") for key in path)
    }
    return hashlib.sha256(json.dumps(texts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


HEAD_DIGESTS = {
    "setup": {
        "base": "ee8bbdcaeed7a396d914cb89434052e8610c2d4e1cfb49b039d9896a0819870d",
        "en": "ee8bbdcaeed7a396d914cb89434052e8610c2d4e1cfb49b039d9896a0819870d",
        "de": "26ef6e5549d11f42a755c280f03a03c1e3a5c64697a7cbb3d34a40e08ec956df",
        "it": "8d669738eac667722a490f1f6dad94c709ba75730cea9a9ff89c72960c5d56a7",
        "fr": "efcf0e32be661c23658cf42a4eea87cb6748ccea4d8784d63f7c86ba93880a1d",
    },
    "reconfigure": {
        "base": "eb919185d61b32f7d46b3491e3338277a36b4ce309196ec8db83f307d1f14985",
        "en": "eb919185d61b32f7d46b3491e3338277a36b4ce309196ec8db83f307d1f14985",
        "de": "9a9f59087b53b0a2bfdc6801a53a98f8228e950dc98851d906b318a3709265e0",
        "it": "590bd5171cf24d8b0848bd9109bf37b2eae32a71afa19de1e340f2d1446bac7f",
        "fr": "15ba9bfbfdac812fedb6933627f0de149147a01290ffd48c5312d71b9424052f",
    },
    "repairs": {
        "base": "9cedea8a6a95514e60b9306551dd27c1d445f8788e2551973cd528276ce2f07e",
        "en": "9cedea8a6a95514e60b9306551dd27c1d445f8788e2551973cd528276ce2f07e",
        "de": "b3583647b21d9ece2d971be18b22072bce436c52537334293d9c7c795eb4fe4d",
        "it": "086eab017ffc0d02a9ff5badb6aaf9633d097ae88535f57509a6bacdc48c1478",
        "fr": "866da3f59a13d7a408422153e14eb2219b0799391e15fa1729072876450892c3",
    },
    "exceptions": {
        "base": "d1682fd87a2f26b1065134323ba5f007cd87bbb75d9ee2f18573248b1f1b4f78",
        "en": "d1682fd87a2f26b1065134323ba5f007cd87bbb75d9ee2f18573248b1f1b4f78",
        "de": "1f8a1c0dae39b26c8d961e0a8d7cd4c42035661732b792d0bd97b312667ed70a",
        "it": "51f5849a371e5d84961ab9a1a4878d06102942ae3636b518719767365fc6d047",
        "fr": "08f03d522233fe816dc5452fdee1231ae425cf240b9758c4fa410641b47efc7b",
    },
}


def assert_c300x_unchanged(area: str) -> None:
    for lang in LANGUAGES:
        assert c300x_digest(lang, area) == HEAD_DIGESTS[area][lang], (area, lang)


def _setup_flow(monkeypatch, info=None, hint=""):
    monkeypatch.setattr(config_entries.ConfigFlow, "async_show_form", lambda self, **values: values)
    monkeypatch.setattr(config_entries.ConfigFlow, "async_abort", lambda self, **values: values)
    flow = BticinoC300XConfigFlow()
    flow._setup_connection = {"agent_host": "station.invalid"}
    flow._setup_agent_info = dict(info or {})
    flow._model_hint = hint
    return flow


def test_setup_texts_name_the_model_the_device_reported(monkeypatch):
    assert_c300x_unchanged("setup")
    for info, hint, model in (
        ({"model": "C300X"}, "", "C300X"),
        ({"model": "C100X"}, "", "C100X"),
        ({"display_kind": "qt5_ondisk"}, "", "C100X"),
        ({}, "C100X", "C100X"),
        ({}, "", EITHER),
    ):
        flow = _setup_flow(monkeypatch, info, hint)
        form = flow.async_show_form(step_id="user_features", errors={"base": "cannot_connect"})
        assert form["description_placeholders"] == {"model": model}, (info, hint)
        assert flow.async_abort(reason="cannot_connect")["description_placeholders"] == {"model": model}
    # A placeholder of the step itself stays.
    form = _setup_flow(monkeypatch).async_show_form(step_id="user", description_placeholders={"x": "1"})
    assert form["description_placeholders"] == {"model": EITHER, "x": "1"}

    assert text("en", "config", "step", "user_features", "title", model="C100X") == "BTicino C100X features"
    assert text("de", "config", "step", "user_features", "title", model="C100X") == "BTicino C100X Funktionen"
    assert text("en", "config", "step", "bootstrap_install", "data", "bootstrap_ssh_username", model="C100X") == (
        "C100X SSH user"
    )
    assert text("de", "config", "error", "invalid_auth", model="C100X") == (
        "Der C100X hat den Zugriffsschlüssel abgelehnt. Gib den aktuellen Schlüssel ein."
    )
    assert text("en", "config", "step", "user", "data", "agent_host", model=EITHER) == "Address of the C300X/C100X"


def test_a_new_c100x_entry_is_titled_after_its_model(monkeypatch):
    created = []
    monkeypatch.setattr(config_entries.ConfigFlow, "async_create_entry", lambda self, **values: created.append(values))
    for info, title, expected in (
        ({"model": "C100X"}, "BTicino C300X", "BTicino C100X"),
        ({"model": "C300X"}, "BTicino C300X", "BTicino C300X"),
        ({"model": "C100X"}, "Front door", "Front door"),
    ):
        _setup_flow(monkeypatch, info).async_create_entry(title=title, data={})
        assert created.pop()["title"] == expected


def test_reauth_and_reconfigure_name_the_model_of_their_entry(monkeypatch):
    c100x = SimpleNamespace(runtime_data=SimpleNamespace(agent_info={"model": "C100X"}))
    for source in ("reauth", "reconfigure"):
        flow = _setup_flow(monkeypatch)
        flow.context = {"source": source}
        monkeypatch.setattr(flow, "_get_reauth_entry", lambda: c100x, raising=False)
        monkeypatch.setattr(flow, "_get_reconfigure_entry", lambda: c100x, raising=False)
        assert flow.async_show_form(step_id="x")["description_placeholders"] == {"model": "C100X"}
        # An entry that is not loaded keeps the C300X text.
        monkeypatch.setattr(flow, "_get_reconfigure_entry", lambda: SimpleNamespace(), raising=False)
        monkeypatch.setattr(flow, "_get_reauth_entry", lambda: SimpleNamespace(), raising=False)
        assert flow.async_show_form(step_id="x")["description_placeholders"] == {"model": "C300X"}


C100X_ENTRY = SimpleNamespace(runtime_data=SimpleNamespace(agent_info={"model": "C100X"}), data={}, options={})
C300X_ENTRY = SimpleNamespace(runtime_data=SimpleNamespace(agent_info={"model": "C300X"}), data={}, options={})


def test_options_and_reconfigure_texts_name_the_model_of_the_entry(monkeypatch):
    assert_c300x_unchanged("reconfigure")
    for method in ("async_show_form", "async_show_menu", "async_abort"):
        monkeypatch.setattr(config_entries.OptionsFlow, method, lambda self, **values: values)
    for entry, model in ((C100X_ENTRY, "C100X"), (C300X_ENTRY, "C300X"), (SimpleNamespace(), "C300X")):
        flow = BticinoC300XOptionsFlow(entry)
        assert flow.async_show_form(step_id="connection")["description_placeholders"] == {"model": model}
        assert flow.async_show_menu(step_id="x", menu_options=[])["description_placeholders"] == {"model": model}
        assert flow.async_abort(reason="unsupported_display")["description_placeholders"] == {"model": model}

    assert text("en", "options", "step", "connection", "title", model="C100X") == "Connection to the C100X"
    assert text("de", "options", "step", "connection", "title", model="C100X") == "Verbindung zum C100X"
    assert text("en", "options", "error", "camera_quality_unsupported", model="C100X") == (
        "This C100X does not offer the camera quality setting."
    )
    assert text("en", "config", "step", "reconfigure", "title", model="C100X") == "Reconfigure BTicino C100X"
    assert text("de", "config", "step", "reconfigure_features", "data", "create_homeassistant_user", model="C100X") == (
        "Zugang für Video und Ton auf dem C100X einrichten"
    )


def test_repairs_name_the_model_of_their_entry(monkeypatch):
    from custom_components.bticino_c300x import repair_issues

    assert_c300x_unchanged("repairs")
    created = []
    monkeypatch.setattr(repair_issues.ir, "async_create_issue", lambda **values: created.append(values))
    for entry, model in ((C100X_ENTRY, "C100X"), (C300X_ENTRY, "C300X")):
        entry = SimpleNamespace(**vars(entry), entry_id="e1", title="Front door")
        repair_issues._create_issue(
            None, entry, "device_user_required", severity=repair_issues.ir.IssueSeverity.WARNING,
        )
        assert created.pop()["translation_placeholders"] == {"entry_title": "Front door", "model": model}

    assert text("en", "issues", "device_user_required", "title", model="C100X") == "C100X media user setup required"
    assert text("de", "issues", "device_user_required", "title", model="C100X") == "C100X Media-User-Setup erforderlich"
    assert text("en", "issues", "frontend_card_setup_hint", "title", model="C100X") == "Add the C100X Lovelace card"
    assert text(
        "en", "issues", "device_user_required", "fix_flow", "error", "device_not_registered", model="C100X",
    ).startswith("The C100X has not been added in the BTicino Door Entry app yet.")


def test_exceptions_name_the_model_of_their_entry():
    from custom_components.bticino_c300x.exceptions import (
        home_assistant_error,
        service_validation_error,
    )
    from custom_components.bticino_c300x.use_cases.common import (
        ensure_text_memo_write_supported,
    )

    assert_c300x_unchanged("exceptions")
    for entry, model in ((C100X_ENTRY, "C100X"), (C300X_ENTRY, "C300X"), (None, "C300X")):
        err = service_validation_error("ring_capture_busy", entry=entry)
        assert err.translation_placeholders == {"model": model}
        err = home_assistant_error("agent_command_failed", {"x": "1"}, entry=entry)
        assert err.translation_placeholders == {"model": model, "x": "1"}
    entry = SimpleNamespace(**vars(C100X_ENTRY))
    entry.runtime_data = SimpleNamespace(agent_info={"model": "C100X"}, capabilities={})
    with pytest.raises(ServiceValidationError) as raised:
        ensure_text_memo_write_supported(entry)
    assert raised.value.translation_placeholders == {"model": "C100X"}
    # A C100X is refused in its own words, whatever its agent reports.
    assert raised.value.translation_key == "text_memo_write_not_supported_c100x"
    entry.runtime_data.capabilities = {"memos": {"supported": True, "write_text": True}}
    with pytest.raises(ServiceValidationError) as raised:
        ensure_text_memo_write_supported(entry)
    assert raised.value.translation_key == "text_memo_write_not_supported_c100x"
    c300x = SimpleNamespace(**vars(C300X_ENTRY))
    c300x.runtime_data = SimpleNamespace(agent_info={"model": "C300X"}, capabilities=entry.runtime_data.capabilities)
    ensure_text_memo_write_supported(c300x)
    for lang, word in (("en", "text memos"), ("de", "Text-Memos"), ("it", "memo testuali"), ("fr", "mémos texte")):
        message = text(lang, "exceptions", "text_memo_write_not_supported_c100x", "message", model="C100X")
        assert word in message and "C100X" in message and "agent" not in message.lower()
    assert _load("en")["exceptions"]["text_memo_write_not_supported_c100x"] == json.loads(
        LANGUAGES["base"].read_text())["exceptions"]["text_memo_write_not_supported_c100x"]


def test_a_c100x_has_no_memo_capability_left():
    from c100x_answering_capabilities import C100X, C300X

    from custom_components.bticino_c300x.capabilities import (
        events_for_capabilities,
        gate_capabilities,
        memo_text_write_supported,
        memos_supported,
    )

    c100x = gate_capabilities(dict(C100X), doorbell_video_enabled=True, c100x=True)
    assert not memos_supported(c100x) and not memo_text_write_supported(c100x)
    assert "memos.changed" not in events_for_capabilities(c100x)
    assert C100X["memos"]["supported"] is True, "the gate must not edit the agent's answer"
    c300x = gate_capabilities(dict(C300X), doorbell_video_enabled=True, c100x=False)
    assert c300x["memos"] == C300X["memos"] and "memos.changed" in events_for_capabilities(c300x)

    assert text("en", "exceptions", "text_memo_write_not_supported", "message", model="C100X") == (
        "Writing a text memo is not supported by the installed C100X device agent."
    )
    assert text("de", "exceptions", "agent_command_failed", "message", model="C100X").count("C100X") == 1
    # The integration's own name stays.
    assert text("en", "exceptions", "entry_not_loaded", "message", model="C100X").startswith("The BTicino C300X entry")


def test_the_c100x_reads_its_own_display_mechanism(monkeypatch):
    """The C100X has no Display patch and no screen reload: its pages come with one reboot."""

    from custom_components.bticino_c300x.config_flow_dashboard import dashboard_schema
    from custom_components.bticino_c300x.exceptions import service_validation_error

    for method in ("async_show_form", "async_show_menu"):
        monkeypatch.setattr(config_entries.OptionsFlow, method, lambda self, **values: values)
    for step in ("dashboard", "display", "init", "connection"):
        c100x = BticinoC300XOptionsFlow(C100X_ENTRY).async_show_form(step_id=step)["step_id"]
        assert c100x == (step if step == "connection" else f"{step}_c100x")
        assert BticinoC300XOptionsFlow(C300X_ENTRY).async_show_menu(step_id=step, menu_options=[])["step_id"] == step
    for step in ("user_dashboard", "reconfigure_dashboard"):
        assert _setup_flow(monkeypatch, {"model": "C100X"}).async_show_form(step_id=step)["step_id"] == f"{step}_c100x"
        assert _setup_flow(monkeypatch, {"model": "C300X"}).async_show_form(step_id=step)["step_id"] == step
    # A submitted twin form lands in the step that showed it.
    for flow, twin, step in (
        (BticinoC300XConfigFlow(), "user_dashboard_c100x", "user_dashboard"),
        (BticinoC300XConfigFlow(), "reconfigure_dashboard_c100x", "reconfigure_dashboard"),
        (BticinoC300XOptionsFlow(C100X_ENTRY), "dashboard_c100x", "dashboard"),
    ):
        async def original(user_input, step=step):
            return (step, user_input)

        monkeypatch.setattr(flow, f"async_step_{step}", original)
        assert asyncio.run(getattr(flow, f"async_step_{twin}")({"a": 1})) == (step, {"a": 1})

    # Alarmo: the C100X opens it from an item of the station's main menu, not from a home page button.
    for step in ("dashboard_alarm",):
        assert BticinoC300XOptionsFlow(C100X_ENTRY).async_show_form(step_id=step)["step_id"] == f"{step}_c100x"
        assert BticinoC300XOptionsFlow(C300X_ENTRY).async_show_form(step_id=step)["step_id"] == step
    for step in ("user_dashboard_alarm", "reconfigure_dashboard_alarm"):
        assert _setup_flow(monkeypatch, {"model": "C100X"}).async_show_form(step_id=step)["step_id"] == f"{step}_c100x"
        assert _setup_flow(monkeypatch, {"model": "C300X"}).async_show_form(step_id=step)["step_id"] == step
    for flow, step in (
        (BticinoC300XConfigFlow(), "user_dashboard_alarm"), (BticinoC300XConfigFlow(), "reconfigure_dashboard_alarm"),
        (BticinoC300XOptionsFlow(C100X_ENTRY), "dashboard_alarm"),
    ):
        async def original_alarm(user_input, step=step):
            return (step, user_input)

        monkeypatch.setattr(flow, f"async_step_{step}", original_alarm)
        assert asyncio.run(getattr(flow, f"async_step_{step}_c100x")({"a": 1})) == (step, {"a": 1})
    menu_word = {"base": "main menu", "en": "main menu", "de": "Hauptmenü", "it": "menu principale", "fr": "menu principal"}
    old_words = ("Display patch", "Display-Patch", "patch display", "home page", "Startseite", "pagina iniziale",
                 "page d'accueil", "Alarm page", "Alarm-Seite", "pagina Allarme", "page Alarme", "Alarm button", "Button Alarm",
                 "Der Button", "pulsante Allarme", "bouton Alarme")
    for lang in LANGUAGES:
        data = _load(lang)
        for area, step in (("config", "user_dashboard_alarm"), ("config", "reconfigure_dashboard_alarm"),
                           ("options", "dashboard_alarm")):
            twin, original = data[area]["step"][f"{step}_c100x"], data[area]["step"][step]
            assert twin["title"] == "Alarmo" and twin["data"] == original["data"], (lang, step)
            assert set(twin["data_description"]) == set(original["data_description"])
            words = json.dumps(twin, ensure_ascii=False)
            assert menu_word[lang] in twin["description"] and menu_word[lang] in twin["data_description"]["alarm_entity_id"]
            assert "{model}" in twin["description"] and "C300X" not in words
            assert not [word for word in old_words if word in words], (lang, step)
        display = json.dumps(data["options"]["step"]["display_c100x"], ensure_ascii=False)
        assert data["options"]["step"]["display_c100x"]["menu_options"]["dashboard_alarm"] == "Alarmo"
        assert not [word for word in old_words[5:] if word in display], lang

    for entry, suffix in ((C100X_ENTRY, "_c100x"), (C300X_ENTRY, ""), (None, "")):
        for key in ("display_disabled", "gui_function_patch_required"):
            assert service_validation_error(key, entry=entry).translation_key == key + suffix
        assert service_validation_error("ring_capture_busy", entry=entry).translation_key == "ring_capture_busy"

    fields = {str(key) for key in dashboard_schema(home_buttons=False).schema}
    reboot = {"base": "reboot", "en": "reboot", "de": "Neustart", "it": "riavvio", "fr": "redémarrage"}
    button = {"base": "Activate display pages", "en": "Activate display pages", "de": "Displayseiten aktivieren",
              "it": "Attiva pagine del display", "fr": "Activer les pages de l'écran"}
    for lang in LANGUAGES:
        data = _load(lang)
        twins = (
            data["config"]["step"]["user_dashboard_c100x"], data["config"]["step"]["reconfigure_dashboard_c100x"],
            data["options"]["step"]["dashboard_c100x"],
        )
        for twin in twins:
            assert set(twin["data"]) == set(twin["data_description"]) == fields, lang
            for value in (twin["description"], twin["data_description"]["device_ui_enabled"]):
                assert "C100X" in value and "C300X" not in value and "60" not in value, (lang, value)
                assert reboot[lang] in value and button[lang] in value, (lang, value)
            assert "{qml_patch_status}" not in twin["description"]
        options = data["options"]["step"]
        assert "C300X" not in json.dumps(options["display_c100x"]) + json.dumps(options["init_c100x"])
        assert set(options["init_c100x"]["menu_options"]) == set(options["init"]["menu_options"])
        assert set(options["display_c100x"]["menu_options"]) == set(options["display"]["menu_options"])
        for key in ("display_disabled_c100x", "gui_function_patch_required_c100x"):
            message = data["exceptions"][key]["message"]
            assert "C100X" in message and button[lang] in message, (lang, key)
    assert _load("en")["options"]["step"]["init_c100x"]["title"] == "C100X settings"
    assert _load("de")["options"]["step"]["init_c100x"]["title"] == "C100X-Einstellungen"
    assert _load("en")["options"]["step"]["display_c100x"]["menu_option_descriptions"]["dashboard"] == (
        _load("en")["options"]["step"]["display"]["menu_option_descriptions"]["dashboard"]
    )


def test_global_texts_name_no_model():
    """Service names are the same for every station; only the integration name stays."""

    for lang in LANGUAGES:
        for service, value in _load(lang)["services"].items():
            for field in _leaves(value).values():
                assert "C300X" not in field.replace("BTicino C300X", "") and "C100X" not in field, (lang, service)
    assert _load("en")["services"]["capture_doorbell_call"]["name"] == "Capture doorbell video"
    assert _load("de")["services"]["capture_doorbell_call"]["name"] == "Türvideo aufnehmen"


def test_the_c100x_reads_how_its_pages_are_changed():
    """The C100X has no favourites bar: its pages follow one another and end in EXIT."""

    for lang in LANGUAGES:
        data = _load(lang)
        for area, step in (("config", "user_dashboard"), ("config", "reconfigure_dashboard"), ("options", "dashboard")):
            twin = data[area]["step"][f"{step}_c100x"]["data_description"]["dashboard_navigation"]
            original = data[area]["step"][step]["data_description"]["dashboard_navigation"]
            assert "EXIT" in twin and "{model}" in twin and "EXIT" not in original, (lang, step)
