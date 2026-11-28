"""A C300X keeps every text it had; a C100X reads its own model name.

The texts name the model through ``{model}``. Rendered for a C300X, every text
of release 2.10.0 must stay byte-identical; the pinned digests were taken from
the translations of f4f75ea3. What was added or changed since is listed here.
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


# Texts a C300X reads that 2.10.0 did not have. The C100X twins ("..._c100x")
# are not his and need no entry here.
ADDED_SINCE_2_10_0 = frozenset({
    "config/abort/model_mismatch",
    "config/abort/reauth_another_station",
    "config/abort/reinstall_entry_updated",
    "config/abort/station_entry_updated",
    "config/abort/unsupported_display",
    "config/error/c100x_confirmation_required",
    "config/error/c3x2_not_supported",
    "config/error/device_model_incompatible",
    "config/error/firewall_hook_changed",
    "config/error/installer_firewall_hook_unsupported",
    "config/error/invalid_ssh_key",
    "config/error/not_a_bticino_station",
    "config/error/ssh_password_login_disabled",
    "config/error/ssh_unreachable",
    "config/error/ssh_user_not_root",
    "config/step/agent_auth/data/reinstall_agent",
    "config/step/agent_auth/data_description/reinstall_agent",
    "config/step/bootstrap_install/data/bootstrap_ssh_key",
    "config/step/bootstrap_install/data/bootstrap_ssh_key_passphrase",
    "config/step/bootstrap_install/data_description/bootstrap_ssh_key",
    "config/step/c100x_experimental/data/c100x_experimental",
    "config/step/c100x_experimental/description",
    "config/step/c100x_experimental/title",
    "config/step/reauth_confirm/data/reinstall_agent",
    "config/step/reauth_confirm/data_description/reinstall_agent",
    "config/step/reauth_reinstall/data/bootstrap_ssh_key",
    "config/step/reauth_reinstall/data/bootstrap_ssh_key_passphrase",
    "config/step/reauth_reinstall/data/bootstrap_ssh_password",
    "config/step/reauth_reinstall/data/bootstrap_ssh_username",
    "config/step/reauth_reinstall/data_description/bootstrap_ssh_key",
    "config/step/reauth_reinstall/description",
    "config/step/reauth_reinstall/title",
    "device/outdoor_unit/name",
    "entity/button/activate_display_pages/name",
    "entity/button/door/name",
    "entity/button/restore_display_pages/name",
    "entity/camera/unit_camera/name",
    "entity/event/door/name",
    "entity/event/door/state_attributes/event_type/state/opened",
    "entity/event/ring/name",
    "entity/event/ring/state_attributes/event_type/state/ring",
    "entity/event/stair_light/name",
    "entity/event/stair_light/state_attributes/event_type/state/activated",
    "entity/image/last_visitor/name",
    "entity/sensor/call/name",
    "entity/sensor/call/state/answered",
    "entity/sensor/call/state/idle",
    "entity/sensor/call/state/ringing",
    "entity/sensor/call/state/viewing",
    "entity/switch/maintenance_ssh/state_attributes/managed_by/name",
    "entity/switch/maintenance_ssh/state_attributes/ssh_state/name",
    "entity/switch/maintenance_ssh/state_attributes/ssh_state/state/managed_externally",
    "entity/switch/maintenance_ssh/state_attributes/ssh_state/state/running",
    "entity/switch/maintenance_ssh/state_attributes/ssh_state/state/stopped",
    "exceptions/call_not_current/message",
    "exceptions/call_unit_pending/message",
    "exceptions/ssh_managed_externally/message",
    "exceptions/target_ambiguous/message",
    "exceptions/target_unsupported/message",
    "exceptions/unit_video_unsupported/message",
    "exceptions/unknown_unit/message",
    "issues/c100x_display_boot_check_failed/description",
    "issues/c100x_display_boot_check_failed/title",
    "issues/c100x_display_rolled_back/description",
    "issues/c100x_display_rolled_back/title",
    "issues/device_agent_update_required/fix_flow/error/firewall_hook_changed",
    "issues/device_agent_update_required/fix_flow/error/invalid_ssh_key",
    "issues/device_agent_update_required/fix_flow/error/c3x2_not_supported",
    "issues/device_agent_update_required/fix_flow/error/not_a_bticino_station",
    "issues/device_agent_update_required/fix_flow/error/ssh_password_login_disabled",
    "issues/device_agent_update_required/fix_flow/error/ssh_unreachable",
    "issues/device_agent_update_required/fix_flow/error/ssh_user_not_root",
    "issues/device_agent_update_required/fix_flow/error/wrong_device",
    "issues/device_agent_update_required/fix_flow/step/ssh_install/data/bootstrap_ssh_key",
    "issues/device_agent_update_required/fix_flow/step/ssh_install/data/bootstrap_ssh_key_passphrase",
    "issues/outdoor_units_breaking_change/description",
    "issues/outdoor_units_breaking_change/title",
    "options/abort/unsupported_display",
    "options/step/init/menu_option_descriptions/dashboard_alarm",
    "options/step/init/menu_options/dashboard_alarm",
    # Door level and fine adjustment replace the two audio gains.
    "config/error/invalid_audio_level",
    "config/step/reconfigure_features/data/audio_fine_gain_db",
    "config/step/reconfigure_features/data/door_audio_level_db",
    "config/step/reconfigure_features/data_description/audio_fine_gain_db",
    "config/step/reconfigure_features/data_description/door_audio_level_db",
    "config/step/user_features/data/audio_fine_gain_db",
    "config/step/user_features/data/door_audio_level_db",
    "config/step/user_features/data_description/audio_fine_gain_db",
    "config/step/user_features/data_description/door_audio_level_db",
    "options/error/invalid_audio_level",
    "options/step/features/data/audio_fine_gain_db",
    "options/step/features/data/door_audio_level_db",
    "options/step/features/data_description/audio_fine_gain_db",
    "options/step/features/data_description/door_audio_level_db",
    "selector/door_audio_level/options/0",
    "selector/door_audio_level/options/12",
    "selector/door_audio_level/options/3",
    "selector/door_audio_level/options/6",
    "selector/door_audio_level/options/9",
    # The activation type "light" is now "actuator" (3.1.0).
    "selector/device_activation_item_type/options/actuator",
    # The door contact of an outdoor unit (3.1.0).
    "entity/binary_sensor/door_contact/name",
    # The station's own call state (3.1.0).
    "entity/sensor/station_call_state/name",
    "entity/sensor/station_call_state/state/answering_machine",
    "entity/sensor/station_call_state/state/conversation",
    "entity/sensor/station_call_state/state/greeting",
    "entity/sensor/station_call_state/state/idle",
    "entity/sensor/station_call_state/state/recording",
    "entity/sensor/station_call_state/state/ringing",
    "entity/sensor/station_call_state/state/setup",
    "entity/sensor/station_call_state/state/viewing",
    "entity/sensor/station_call_state/state/waiting",
    # A new installation on firmware 1.7.x/2.0.2 restarts once for PCMU (3.1.0).
    "config/create_entry/pcmu_restart",
    # Home Assistant has no leg of a ring only the station rings (3.1.0).
    "exceptions/ring_call_not_active/message",
})
# Texts of 2.10.0 that read differently now: the SSH package message names the
# package and the way out, the service name lost the model (neutral names), the
# SSH forms name the optional private key, the unfinished display write
# points to the documentation section where the step now is, the callback
# URL error reads as in English in every language (no model), and the
# services ask for a target instead of an entry id (3.1.0).
CHANGED_SINCE_2_10_0 = frozenset({
    # The integration is called BTicino C300X/C100X since 3.0.0.
    "config/abort/already_configured",
    "config/step/user/title",
    "exceptions/entry_id_required/message",
    "exceptions/entry_not_loaded/message",
    "exceptions/unknown_entry/message",
    "issues/device_agent_update_required/fix_flow/abort/entry_not_loaded",
    "issues/device_core_qml_hook_required/fix_flow/abort/entry_not_loaded",
    "issues/device_display_followup_pending/fix_flow/abort/entry_not_loaded",
    "issues/device_user_required/fix_flow/abort/entry_not_loaded",
    "issues/frontend_card_setup_hint/fix_flow/abort/entry_not_loaded",
    "issues/media_setup_repair_required/fix_flow/abort/entry_not_loaded",
    "issues/unsupported_callback_url/fix_flow/abort/entry_not_loaded",
    "config/error/installer_dependency_missing",
    "config/error/invalid_callback_base_url",
    "config/step/bootstrap_install/description",
    "issues/device_agent_update_required/fix_flow/step/ssh_install/description",
    "issues/device_qml_transaction_stuck/description",
    "issues/unsupported_callback_url/fix_flow/error/invalid_callback_base_url",
    "options/error/invalid_callback_base_url",
    "services/capture_doorbell_call/name",
    # The activation type "light" is now "actuator" (3.1.0).
    "config/step/reconfigure_device_activation_item/data_description/device_activation_item_type",
    "config/step/reconfigure_device_activations/description",
    "config/step/user_device_activation_item/data_description/device_activation_item_type",
    "config/step/user_device_activations/description",
    "options/step/device_activation_item/data_description/device_activation_item_type",
    "options/step/device_activations/description",
    "options/step/device_activations/title",
    "options/step/init/menu_option_descriptions/device_activations",
    "options/step/init/menu_options/device_activations",
    "options/step/init_c100x/menu_option_descriptions/device_activations",
    "options/step/init_c100x/menu_options/device_activations",
    # The stair light is at the station's own address unless the user sets one (3.1.0).
    "config/step/reconfigure_device_activations/data_description/device_activation_mode",
    "config/step/user_device_activations/data_description/device_activation_mode",
    "options/step/device_activations/data_description/device_activation_mode",
})
# Texts of 2.10.0 that are gone: 3.1.0 removed the agent event entity, the
# doorbell state sensor, the station's door button (each unit has its own) and
# the entry id of the services, which take a target now
# (docs/dev/multi-outdoor-units.md); the two audio gains became the door level
# and the fine adjustment.
REMOVED_SINCE_2_10_0 = frozenset({
    "config/error/invalid_audio_gain",
    "config/step/reconfigure_features/data/doorstation_audio_gain_db",
    "config/step/reconfigure_features/data/ring_capture_audio_gain_db",
    "config/step/reconfigure_features/data_description/doorstation_audio_gain_db",
    "config/step/reconfigure_features/data_description/ring_capture_audio_gain_db",
    "config/step/user_features/data/doorstation_audio_gain_db",
    "config/step/user_features/data/ring_capture_audio_gain_db",
    "config/step/user_features/data_description/doorstation_audio_gain_db",
    "config/step/user_features/data_description/ring_capture_audio_gain_db",
    "entity/button/door_unlock/name",
    "entity/event/agent_event/name",
    "entity/event/agent_event/state_attributes/event_type/state/activation_executed",
    "entity/event/agent_event/state_attributes/event_type/state/agent_diagnostics_changed",
    "entity/event/agent_event/state_attributes/event_type/state/agent_restarted",
    "entity/event/agent_event/state_attributes/event_type/state/answering_machine_messages_changed",
    "entity/event/agent_event/state_attributes/event_type/state/call_ended",
    "entity/event/agent_event/state_attributes/event_type/state/call_started",
    "entity/event/agent_event/state_attributes/event_type/state/display_touch_tone_changed",
    "entity/event/agent_event/state_attributes/event_type/state/door_unlock_ended",
    "entity/event/agent_event/state_attributes/event_type/state/door_unlock_started",
    "entity/event/agent_event/state_attributes/event_type/state/doorbell_media_closed",
    "entity/event/agent_event/state_attributes/event_type/state/doorbell_pressed",
    "entity/event/agent_event/state_attributes/event_type/state/doorbell_view_requested",
    "entity/event/agent_event/state_attributes/event_type/state/home_call_answered",
    "entity/event/agent_event/state_attributes/event_type/state/home_call_ended",
    "entity/event/agent_event/state_attributes/event_type/state/home_call_started",
    "entity/event/agent_event/state_attributes/event_type/state/memos_changed",
    "entity/event/agent_event/state_attributes/event_type/state/ringer_muted",
    "entity/event/agent_event/state_attributes/event_type/state/ringer_unmuted",
    "entity/event/agent_event/state_attributes/event_type/state/ringer_volume_changed",
    "entity/event/agent_event/state_attributes/event_type/state/smartphone_forwarding_changed",
    "entity/event/agent_event/state_attributes/event_type/state/stair_light_activated",
    "entity/event/agent_event/state_attributes/event_type/state/stair_light_released",
    "entity/event/agent_event/state_attributes/event_type/state/system_metrics_changed",
    "entity/sensor/doorbell_state/name",
    "entity/sensor/doorbell_state/state/idle",
    "entity/sensor/doorbell_state/state/ringing",
    "entity/sensor/doorbell_state/state/view_requested",
    "options/error/invalid_audio_gain",
    "options/step/features/data/doorstation_audio_gain_db",
    "options/step/features/data/ring_capture_audio_gain_db",
    "options/step/features/data_description/doorstation_audio_gain_db",
    "options/step/features/data_description/ring_capture_audio_gain_db",
    "services/camera_picture/fields/entry_id/name",
    # The activation type "light" is now "actuator" (3.1.0).
    "selector/device_activation_item_type/options/light",
})
# sha256 over every text of 2.10.0 (f4f75ea3) but the changed and the removed
# ones, per file:
#   json.dumps({"a/b/c": text}, sort_keys=True, ensure_ascii=False)
DIGESTS_2_10_0 = {
    "base": "9bccfff6f48563de5a785644c2ebc17bce2dbe8ab98b54dd3f5574ce80f4534a",
    "en": "9bccfff6f48563de5a785644c2ebc17bce2dbe8ab98b54dd3f5574ce80f4534a",
    "de": "8215fa8ddccdb3d208a1e663b598e02e4e883cb7796272a97687b2a0698fdec0",
    "it": "f3b46cfda0b3639afaf8d12823f9f830a0550c5b6929ce57fd19926f0a051a22",
    "fr": "88a38f379623e679009128685d8af0f4a2720d452fef46f1d6868e2e2d4dbc7b",
}


def c300x_digest(lang: str) -> str:
    """Every text a C300X reads that 2.10.0 had, as he reads it now."""

    texts = {
        "/".join(path): value.replace("{model}", "C300X")
        for path, value in _leaves(_load(lang)).items()
        if not any(key.endswith("_c100x") for key in path)
        and "/".join(path) not in ADDED_SINCE_2_10_0 | CHANGED_SINCE_2_10_0
    }
    return hashlib.sha256(json.dumps(texts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def assert_c300x_unchanged(area: str = "") -> None:
    for lang in LANGUAGES:
        assert c300x_digest(lang) == DIGESTS_2_10_0[lang], (area, lang)


def test_a_c300x_reads_the_texts_of_2_10_0():
    assert_c300x_unchanged()
    for lang in LANGUAGES:
        paths = {"/".join(path) for path in _leaves(_load(lang))}
        # The declared additions and changes exist; nothing is listed for nothing.
        assert paths >= ADDED_SINCE_2_10_0 | CHANGED_SINCE_2_10_0, lang
        assert not paths & REMOVED_SINCE_2_10_0, lang


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
    assert text("en", "exceptions", "entry_not_loaded", "message", model="C100X").startswith("The BTicino C300X/C100X entry")


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
                assert "C300X" not in field.replace("BTicino C300X/C100X", "") and "C100X" not in field, (lang, service)
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
