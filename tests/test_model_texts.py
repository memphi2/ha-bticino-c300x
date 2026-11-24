"""A C300X keeps every text it had; a C100X reads its own model name.

The texts name the model through ``{model}``. Rendered for a C300X, each area
must stay byte-identical to the texts before the change; the pinned digests
were taken from the translations of 04a99ea6.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from homeassistant import config_entries

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
        "base": "38771bea91f301392fd6a5013116e111f9c95564a7f059a39525cb3577749cc5",
        "en": "38771bea91f301392fd6a5013116e111f9c95564a7f059a39525cb3577749cc5",
        "de": "502d7b381e3abfe9edbb80ed3a9886be132704f2b0b04fc9ae5fbabcdc40a6e2",
        "it": "2c570e6a47606e5ce67f2eea249b06cd152652275334ad6bbf88559b18141956",
        "fr": "b7e855791009e532b07926124bd6a782567c087c6d6c3f9071e70d89ec9da503",
    },
    "reconfigure": {
        "base": "eb919185d61b32f7d46b3491e3338277a36b4ce309196ec8db83f307d1f14985",
        "en": "eb919185d61b32f7d46b3491e3338277a36b4ce309196ec8db83f307d1f14985",
        "de": "9a9f59087b53b0a2bfdc6801a53a98f8228e950dc98851d906b318a3709265e0",
        "it": "590bd5171cf24d8b0848bd9109bf37b2eae32a71afa19de1e340f2d1446bac7f",
        "fr": "15ba9bfbfdac812fedb6933627f0de149147a01290ffd48c5312d71b9424052f",
    },
    "repairs": {
        "base": "43b7ff850b321f32ebdc34fdbdff952449f708478fba878f11a112363779cfa0",
        "en": "43b7ff850b321f32ebdc34fdbdff952449f708478fba878f11a112363779cfa0",
        "de": "99de99c4b2b81b67dffe438c5985734cefe3b601dc6eccdf2168c2679f32d4db",
        "it": "b4bd8338d3d102247f744012ccb462cee2860480c4cc925437b1601042ad70ac",
        "fr": "ed1022d9229a880b0eb484f2c7a8523975b1cbbd1a67240941228203d53fb1df",
    },
    "exceptions": {
        "base": "8003e89ef3f7f28858b391bbfc9f5b4768b20765b2458b4fddae5fb3e377a9e3",
        "en": "8003e89ef3f7f28858b391bbfc9f5b4768b20765b2458b4fddae5fb3e377a9e3",
        "de": "469cb09d37bce546681efc6fb4405abccc4e8ff25ccf8bd150c97a679cb20193",
        "it": "0f56168d06507f02fd2c796b7e7dc228d94a005d1e5a54a3ca9e0c18507c1dcd",
        "fr": "de5f78e2d9d0273ad231b2bdf39ea0c08719af6dfba94e5feca870dc8b227575",
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
