from __future__ import annotations

import asyncio
import builtins
import json
import os
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from custom_components.bticino_c300x.const import DOMAIN
from custom_components.bticino_c300x.frontend import (
    DATA_FRONTEND_METADATA_URL,
    DATA_FRONTEND_MODULE_URL,
    DOORBELL_CALL_CARD_FILENAME,
    DOORBELL_CALL_CARD_METADATA_FILENAME,
    FRONTEND_DIR,
    FRONTEND_URL_PATH,
    _async_ensure_lovelace_resource,
    _frontend_asset_version,
    _register_frontend_module_url,
    async_setup_frontend,
)

CARD_SOURCE = FRONTEND_DIR / DOORBELL_CALL_CARD_FILENAME
CARD_METADATA_SOURCE = FRONTEND_DIR / DOORBELL_CALL_CARD_METADATA_FILENAME
CARD_RESOLVER_SOURCE = FRONTEND_DIR / "c300x-entity-resolver.js"
CARD_RINGBACK_SOURCE = FRONTEND_DIR / "c300x-ringback-tone.js"
CARD_STATE_SOURCE = FRONTEND_DIR / "c300x-state-model.js"
CARD_TRANSLATIONS_SOURCE = FRONTEND_DIR / "c300x-translations.js"
CARD_WEBRTC_SOURCE = FRONTEND_DIR / "c300x-webrtc-client.js"
MANIFEST_SOURCE = Path("custom_components/bticino_c300x/manifest.json")


@dataclass
class _StaticPathConfig:
    url_path: str
    path: str
    cache_headers: bool


class _FakeHttp:
    def __init__(self) -> None:
        self.static_paths: list[_StaticPathConfig] = []

    async def async_register_static_paths(
        self,
        configs: list[_StaticPathConfig],
    ) -> None:
        self.static_paths.extend(configs)


class _FakeHass:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.http = _FakeHttp()
        self.extra_module_urls: list[str] = []

    async def async_add_executor_job(self, func: Any, *args: Any) -> Any:
        return func(*args)


def test_async_setup_frontend_registers_bundled_card_once(monkeypatch: Any) -> None:
    http_module = types.ModuleType("homeassistant.components.http")
    http_module.StaticPathConfig = _StaticPathConfig
    frontend_module = types.ModuleType("homeassistant.components.frontend")

    def add_extra_js_url(hass: _FakeHass, url: str, es5: bool = False) -> None:
        assert es5 is False
        hass.extra_module_urls.append(url)

    def remove_extra_js_url(hass: _FakeHass, url: str, es5: bool = False) -> None:
        assert es5 is False
        hass.extra_module_urls.remove(url)

    frontend_module.add_extra_js_url = add_extra_js_url
    frontend_module.remove_extra_js_url = remove_extra_js_url
    monkeypatch.setitem(sys.modules, "homeassistant.components.http", http_module)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.frontend",
        frontend_module,
    )

    hass = _FakeHass()

    asyncio.run(async_setup_frontend(hass))
    asyncio.run(async_setup_frontend(hass))

    assert hass.http.static_paths == [
        _StaticPathConfig(FRONTEND_URL_PATH, str(FRONTEND_DIR), False)
    ]
    module_url = hass.data[DOMAIN][DATA_FRONTEND_MODULE_URL]
    assert module_url.startswith(
        f"{FRONTEND_URL_PATH}/{DOORBELL_CALL_CARD_FILENAME}?v="
    )
    metadata_url = hass.data[DOMAIN][DATA_FRONTEND_METADATA_URL]
    assert metadata_url.startswith(
        f"{FRONTEND_URL_PATH}/{DOORBELL_CALL_CARD_METADATA_FILENAME}?v="
    )
    assert hass.data[DOMAIN][DATA_FRONTEND_MODULE_URL] == module_url
    assert hass.extra_module_urls == [metadata_url]


def test_frontend_asset_version_tracks_content_not_mtime(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    import custom_components.bticino_c300x.frontend as frontend_module

    card_path = tmp_path / DOORBELL_CALL_CARD_FILENAME
    card_path.write_text("first", encoding="utf-8")
    os.utime(card_path, (1_700_000_000, 1_700_000_000))
    monkeypatch.setattr(frontend_module, "FRONTEND_DIR", tmp_path)
    first_version = _frontend_asset_version()

    card_path.write_text("second", encoding="utf-8")
    os.utime(card_path, (1_700_000_000, 1_700_000_000))

    assert _frontend_asset_version() != first_version


def test_frontend_asset_version_returns_zero_for_missing_asset(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    import custom_components.bticino_c300x.frontend as frontend_module

    monkeypatch.setattr(frontend_module, "FRONTEND_DIR", tmp_path)

    assert _frontend_asset_version() == "0"


def test_frontend_module_registration_handles_missing_frontend(
    monkeypatch: Any,
) -> None:
    real_import = builtins.__import__

    def fake_import(
        name: str,
        globals_: dict[str, Any] | None = None,
        locals_: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "homeassistant.components" and "frontend" in fromlist:
            raise ImportError
        return real_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    _register_frontend_module_url(_FakeHass(), "/metadata.js", ("/old.js",))


def test_frontend_module_registration_removes_old_urls_and_ignores_add_failure(
    monkeypatch: Any,
) -> None:
    import homeassistant.components as ha_components

    frontend_module = types.ModuleType("homeassistant.components.frontend")
    removed: list[str] = []

    def add_extra_js_url(_hass: _FakeHass, _url: str, es5: bool = False) -> None:
        assert es5 is False
        raise KeyError

    def remove_extra_js_url(_hass: _FakeHass, url: str, es5: bool = False) -> None:
        assert es5 is False
        removed.append(url)

    frontend_module.add_extra_js_url = add_extra_js_url
    frontend_module.remove_extra_js_url = remove_extra_js_url
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.frontend",
        frontend_module,
    )
    monkeypatch.setattr(ha_components, "frontend", frontend_module, raising=False)

    _register_frontend_module_url(
        _FakeHass(),
        "/metadata.js",
        ("/old.js", "/metadata.js", None),
    )

    assert removed == ["/old.js"]


def test_lovelace_is_a_hard_dependency_for_card_resource_registration() -> None:
    manifest = json.loads(MANIFEST_SOURCE.read_text(encoding="utf-8"))

    assert "lovelace" in manifest["dependencies"]
    assert "lovelace" not in manifest.get("after_dependencies", [])


def test_frontend_lovelace_resource_is_stable_and_idempotent(
    monkeypatch: Any,
) -> None:
    lovelace_const = types.ModuleType("homeassistant.components.lovelace.const")
    lovelace_const.LOVELACE_DATA = "lovelace"
    collection_module = types.ModuleType("homeassistant.helpers.collection")

    class ItemNotFound(Exception):
        pass

    class FakeResources:
        def __init__(self) -> None:
            self.loaded = False
            self.items = [
                {
                    "id": "old-c300x",
                    "url": f"{FRONTEND_URL_PATH}/{DOORBELL_CALL_CARD_FILENAME}?v=1",
                    "type": "module",
                },
                {
                    "id": "duplicate-c300x",
                    "url": f"{FRONTEND_URL_PATH}/{DOORBELL_CALL_CARD_FILENAME}?v=0",
                    "type": "module",
                },
                {
                    "id": "other",
                    "url": "/hacsfiles/example/example.js",
                    "type": "module",
                },
            ]
            self.created: list[dict[str, Any]] = []
            self.updated: list[tuple[str, dict[str, Any]]] = []
            self.deleted: list[str] = []

        async def async_get_info(self) -> dict[str, int]:
            self.loaded = True
            return {"resources": len(self.items)}

        def async_items(self) -> list[dict[str, Any]]:
            return self.items

        async def async_create_item(self, data: dict[str, Any]) -> dict[str, Any]:
            self.created.append(data)
            item = {"id": "created", "url": data["url"], "type": data["res_type"]}
            self.items.append(item)
            return item

        async def async_update_item(
            self,
            item_id: str,
            updates: dict[str, Any],
        ) -> dict[str, Any]:
            self.updated.append((item_id, updates))
            for item in self.items:
                if item["id"] == item_id:
                    item["url"] = updates["url"]
                    item["type"] = updates["res_type"]
                    return item
            raise ItemNotFound

        async def async_delete_item(self, item_id: str) -> None:
            self.deleted.append(item_id)
            self.items = [item for item in self.items if item["id"] != item_id]

    resources = FakeResources()
    collection_module.ItemNotFound = ItemNotFound
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.lovelace.const",
        lovelace_const,
    )
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.collection",
        collection_module,
    )

    module_url = f"{FRONTEND_URL_PATH}/{DOORBELL_CALL_CARD_FILENAME}?v=2"
    hass = _FakeHass()
    hass.data["lovelace"] = types.SimpleNamespace(resources=resources)

    asyncio.run(_async_ensure_lovelace_resource(hass, module_url))
    asyncio.run(_async_ensure_lovelace_resource(hass, module_url))

    assert resources.loaded is True
    assert resources.created == []
    assert resources.updated == [
        ("old-c300x", {"url": module_url, "res_type": "module"})
    ]
    assert resources.deleted == ["duplicate-c300x"]
    assert resources.items == [
        {
            "id": "old-c300x",
            "url": module_url,
            "type": "module",
        },
        {
            "id": "other",
            "url": "/hacsfiles/example/example.js",
            "type": "module",
        },
    ]


def test_frontend_lovelace_resource_creates_missing_resource(
    monkeypatch: Any,
) -> None:
    lovelace_const = types.ModuleType("homeassistant.components.lovelace.const")
    lovelace_const.LOVELACE_DATA = "lovelace"
    collection_module = types.ModuleType("homeassistant.helpers.collection")

    class ItemNotFound(Exception):
        pass

    class FakeResources:
        def __init__(self) -> None:
            self.items: list[dict[str, Any]] = []
            self.created: list[dict[str, Any]] = []

        def async_items(self) -> list[dict[str, Any]]:
            return self.items

        async def async_create_item(self, data: dict[str, Any]) -> dict[str, Any]:
            self.created.append(data)
            return data

    resources = FakeResources()
    collection_module.ItemNotFound = ItemNotFound
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.lovelace.const",
        lovelace_const,
    )
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.collection",
        collection_module,
    )

    module_url = f"{FRONTEND_URL_PATH}/{DOORBELL_CALL_CARD_FILENAME}?v=2"
    hass = _FakeHass()
    hass.data["lovelace"] = types.SimpleNamespace(resources=resources)

    asyncio.run(_async_ensure_lovelace_resource(hass, module_url))

    assert resources.created == [{"url": module_url, "res_type": "module"}]


def test_frontend_lovelace_resource_handles_missing_manager(
    monkeypatch: Any,
) -> None:
    lovelace_const = types.ModuleType("homeassistant.components.lovelace.const")
    lovelace_const.LOVELACE_DATA = "lovelace"
    collection_module = types.ModuleType("homeassistant.helpers.collection")
    collection_module.ItemNotFound = KeyError
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.lovelace.const",
        lovelace_const,
    )
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.collection",
        collection_module,
    )

    hass = _FakeHass()
    asyncio.run(_async_ensure_lovelace_resource(hass, "/module.js"))
    hass.data["lovelace"] = types.SimpleNamespace(resources=object())
    asyncio.run(_async_ensure_lovelace_resource(hass, "/module.js"))


def test_bundled_card_supports_editor_languages_and_multi_device_config() -> None:
    source = CARD_SOURCE.read_text(encoding="utf-8")
    resolver_source = CARD_RESOLVER_SOURCE.read_text(encoding="utf-8")
    translations_source = CARD_TRANSLATIONS_SOURCE.read_text(encoding="utf-8")
    webrtc_source = CARD_WEBRTC_SOURCE.read_text(encoding="utf-8")

    assert 'static getConfigElement()' in source
    assert "function c300xRegisterCustomElements()" not in source
    assert "window.setTimeout(c300xRegisterCustomElements, delay)" not in source
    assert "static getStubConfig(hass, entityId)" in source
    assert "type: C300X_CARD_TYPE" in source
    assert "return {\n      type: C300X_CARD_TYPE," not in source
    assert 'throw new Error("entity is required")' not in source
    assert 'entity: config.entity || c300xEntityId("camera", C300X_CAMERA_OBJECT_ID)' in source
    assert 'getGridOptions()' in source
    assert "rows: 5" in source
    assert "columns: 12" in source
    assert "min_rows: 5" in source
    assert "max_rows: 5" in source
    assert "min_columns: 6" in source
    assert "return this._isHomeCallMode() ? 1 : 7;" in source
    assert 'getEntitySuggestion: (hass, entityId)' in source
    assert 'documentationURL: C300X_DOCUMENTATION_URL' in source
    assert 'preview: true' in source
    assert "ll-rebuild" not in source
    assert 'formatEntityName' in source
    assert '<ha-form>' in source
    assert 'selector: { entity_name: {} }' in source
    assert 'context: { entity: "entity" }' in source
    assert 'config_entry_id' in resolver_source
    assert "function c300xAutoRelatedEntityId" not in resolver_source
    assert "function c300xFirstRelatedEntityId" not in resolver_source
    assert "translation_key" not in resolver_source
    assert "unique_id" not in resolver_source
    assert "C300X_DOORBELL_STATE_TRANSLATION_KEY" not in source
    assert "C300X_HOME_CALL_TRANSLATION_KEY" not in source
    assert ".filter((entityId)" not in source
    assert ".sort((left, right)" not in source
    assert 'name: "state_entity"' not in source
    assert 'name: "state_label"' not in source
    assert 'name: "doorbell_state_entity"' not in source
    assert 'name: "home_call_entity"' not in source
    assert 'selector: { entity: { domain: "sensor" } }' not in source
    assert 'selector: { entity: { domain: "binary_sensor" } }' not in source
    assert "doorbell_state_entity: entityId" not in source
    assert "home_call_entity: entityId" not in source
    assert 'customElements.define("c300x-doorbell-call-card-editor"' in source
    assert 'customElements.get(C300X_CARD_TAG)' in source
    for language in ("en", "de", "fr", "it"):
        assert f"  {language}: {{" in translations_source
    assert '"state_entity"' not in source
    assert "state_label" not in source
    assert "config.doorbell_state_entity" not in resolver_source
    assert "config.home_call_entity" not in resolver_source
    assert "bticino_c300x_doorbell_camera" in resolver_source
    assert "script.c300x_stop_doorbell_call_simulation" not in source
    assert "<ha-button" not in source
    assert "Answer / Talkback" not in source
    assert "Offer Audio" not in source
    assert "this._closing || !this._pc" in webrtc_source
    assert "unsub();" in webrtc_source


def test_picker_metadata_is_split_from_card_custom_element_module() -> None:
    source = CARD_SOURCE.read_text(encoding="utf-8")
    metadata_source = CARD_METADATA_SOURCE.read_text(encoding="utf-8")

    assert "window.customCards.push" in metadata_source
    assert "doorbell_state_entity: entityId" not in metadata_source
    assert "home_call_entity: entityId" not in metadata_source
    assert "c300xMetadataRegistryEntity" not in metadata_source
    assert "c300xMetadataRelatedCamera" not in metadata_source
    assert "translation_key" not in metadata_source
    assert "unique_id" not in metadata_source
    assert "getEntitySuggestion: c300xMetadataEntitySuggestion" in metadata_source
    assert "customElements.define" not in metadata_source
    assert "extends HTMLElement" not in metadata_source
    assert "window.customCards.push" in source
    assert 'customElements.define(C300X_CARD_TAG, C300XDoorbellCallCard)' in source


def test_bundled_card_handles_missing_microphone_without_breaking_stream() -> None:
    source = CARD_SOURCE.read_text(encoding="utf-8")
    webrtc_source = CARD_WEBRTC_SOURCE.read_text(encoding="utf-8")

    assert "async _prepareMicrophone()" in source
    assert 'this._label("microphone_required")' in source
    assert 'this._label("microphone_stream_only")' in source
    assert "this._notice" in source
    assert 'this._notice = this._label("microphone_required")' in source
    assert 'this._notice = this._label("microphone_stream_only")' in source
    assert 'throw new Error(this._label("microphone_required"))' not in source
    assert 'pc.addTransceiver("video", { direction: "recvonly" });' in webrtc_source
    assert 'pc.addTransceiver("audio", { direction: "recvonly" });' in webrtc_source
    assert "navigator.mediaDevices.getUserMedia" not in source
    assert 'typeof getUserMedia !== "function"' in source


def test_bundled_card_marks_external_doorstation_calls_not_controllable() -> None:
    source = CARD_SOURCE.read_text(encoding="utf-8")
    state_source = CARD_STATE_SOURCE.read_text(encoding="utf-8")
    translations_source = CARD_TRANSLATIONS_SOURCE.read_text(encoding="utf-8")

    assert 'external_call: "External Call"' in translations_source
    assert 'actionDisabled,\n    actionActive: active || action === "answer",' in state_source
    assert 'action === "external_call"' in state_source
    assert 'action === "busy"' in state_source
    assert 'action === "unavailable"' in state_source
    assert "this._actionButtonEl.disabled = view.actionDisabled;" in source
    assert 'if (action === "external_call") {' in source
    assert "return attributes.external_media_active === true" in state_source
    assert 'attributes.video_owner === "external_media"' in state_source
    assert 'attributes.external_owner === "external_media"' in state_source


def test_bundled_card_answers_ring_calls_from_camera_state_machine_only() -> None:
    state_source = CARD_STATE_SOURCE.read_text(encoding="utf-8")

    assert "function c300xIsRingCallPending(cameraEntity)" in state_source
    assert "function c300xIsRingCallAvailable(cameraEntity)" in state_source
    assert "c300xMediaState(cameraEntity)" in state_source
    assert "c300xMediaPrimaryAction(cameraEntity)" in state_source
    assert 'action === "answer_ring"' in state_source
    assert state_source.index("const stateMachineAction = c300xStateMachineDoorstationAction") < state_source.index(
        "c300xIsRingCallPending(cameraEntity)"
    )
    assert state_source.index("c300xIsRingCallPending(cameraEntity)") < state_source.index("if (active) {")
    assert 'state === "ringing" || state === "doorbell_pressed"' not in state_source
    assert "&& !c300xIsExternalDoorstationMedia(cameraEntity)" in state_source


def test_bundled_card_starts_ring_preview_without_answer_audio() -> None:
    source = CARD_SOURCE.read_text(encoding="utf-8")
    state_source = CARD_STATE_SOURCE.read_text(encoding="utf-8")
    webrtc_source = CARD_WEBRTC_SOURCE.read_text(encoding="utf-8")

    assert "async _ensureDoorbellPreview()" in source
    assert "if (view.shouldAutoPreview) {" in source
    assert 'shouldAutoPreview: action === "answer" && c300xIsRingPreviewAvailable(cameraEntity)' in state_source
    assert "c300xIsRingPreviewAvailable(cameraEntity)" in state_source
    assert 'c300xMediaState(cameraEntity) === "ring_preview_active"' in state_source
    assert "this._ringPreviewActive = true;" in source
    assert "this._startTalkback({ microphone: false, receiveAudio: false })" in source
    assert "} else if (receiveAudio) {" in webrtc_source


def test_bundled_card_mutes_only_local_microphone_tracks() -> None:
    source = CARD_SOURCE.read_text(encoding="utf-8")
    translations_source = CARD_TRANSLATIONS_SOURCE.read_text(encoding="utf-8")

    assert "this._micMuted = false;" in source
    assert 'class="mic-action hidden"' in source
    assert 'this._micButtonEl.addEventListener("click"' in source
    assert "this._toggleMicMuted();" in source
    assert "track.enabled = !this._micMuted;" in source
    assert "this._applyMicMuted();" in source
    assert "this._micMuted = false;" in source
    assert 'this._label(this._micMuted ? "unmute_microphone" : "mute_microphone")' in source
    assert 'this._micMuted ? "mdi:microphone-off" : "mdi:microphone"' in source
    assert 'callService("bticino_c300x", "mute' not in source
    assert 'mute_microphone: "Mute microphone"' in translations_source
    assert 'unmute_microphone: "Unmute microphone"' in translations_source


def test_bundled_card_transitions_answer_without_clearing_preview() -> None:
    source = CARD_SOURCE.read_text(encoding="utf-8")
    webrtc_source = CARD_WEBRTC_SOURCE.read_text(encoding="utf-8")

    assert "this._transitionWebrtc = null;" in source
    assert '<video class="transition-video" playsinline autoplay></video>' in source
    assert "async _startAnsweredDoorbellStream()" in source
    assert "this._transitionVideoEl.addEventListener(\"loadeddata\", promote)" in source
    assert "this._transitionVideoEl.addEventListener(\"playing\", promote)" in source
    assert "this._videoEl.srcObject = next.remoteStream;" in source
    assert "previous.close();" in source
    assert "await this._startAnsweredDoorbellStream();" in source
    assert "this._closePeer(true, { keepMediaElement: true });" not in source
    assert "attachOnFirstTrack = false" in webrtc_source
    assert "attachMedia();" in webrtc_source


def test_bundled_card_does_not_restart_preview_during_answer_transition() -> None:
    source = CARD_SOURCE.read_text(encoding="utf-8")
    webrtc_source = CARD_WEBRTC_SOURCE.read_text(encoding="utf-8")

    answer_block = source[
        source.index('if (action === "answer") {') : source.index(
            "await this._startTalkback();\n      return;"
        )
    ]
    preview_guard = source[
        source.index("async _ensureDoorbellPreview()") : source.index(
            "this._previewStarting = true;",
            source.index("async _ensureDoorbellPreview()"),
        )
    ]

    assert answer_block.index("await this._answerDoorbellCall();") < answer_block.index(
        "this._doorbellAnswered = true;"
    )
    assert answer_block.index("this._doorbellAnswered = true;") < answer_block.index(
        "await this._startAnsweredDoorbellStream();"
    )
    assert "|| this._transitionWebrtc" in preview_guard
    assert "|| this._doorbellAnswered" in preview_guard
    assert "|| this._ringPreviewStarted" in preview_guard
    assert "if (this._closing) {\n        return;\n      }\n      const state" in webrtc_source
    assert (
        'if (this._closing) {\n                return;\n              }\n'
        '              this._onClosed?.(message.reason || "closed");'
        in webrtc_source
    )


def test_bundled_card_uses_media_state_for_answered_ring_call() -> None:
    state_source = CARD_STATE_SOURCE.read_text(encoding="utf-8")

    assert 'action === "hangup" || action === "stop_stream"' in state_source
    assert 'mediaState === "ring_answering"' in state_source
    assert 'mediaState === "ring_active"' in state_source
    assert 'mediaState === "ring_hanging_up"' in state_source
    assert state_source.index("const stateMachineAction = c300xStateMachineDoorstationAction") < state_source.index(
        "c300xIsRingCallPending(cameraEntity)"
    )


def test_bundled_card_treats_media_primary_action_as_authoritative() -> None:
    state_source = CARD_STATE_SOURCE.read_text(encoding="utf-8")

    assert "if (!c300xHasMediaPrimaryAction(cameraEntity))" in state_source
    assert 'return "busy";' in state_source
    assert 'return active ? "hang_up" : "unavailable";' in state_source
    assert state_source.index("const stateMachineAction = c300xStateMachineDoorstationAction") < state_source.index(
        "c300xIsRingCallPending(cameraEntity)"
    )
    assert (
        'doorbellAnswered && (!stateMachineAction || stateMachineAction === "answer")'
        in state_source
    )


def test_bundled_state_model_maps_media_actions_to_buttons() -> None:
    state_source = CARD_STATE_SOURCE.read_text(encoding="utf-8")
    start = state_source.index("export function c300xStateMachineDoorstationAction")
    end = state_source.index("export function c300xHasMediaPrimaryAction")
    function_body = state_source[start:end]

    expected_mappings = {
        'if (action === "answer_ring")': 'return "answer";',
        'if (action === "hangup" || action === "stop_stream")': (
            'return "hang_up";'
        ),
        'if (action === "start_stream")': 'return active ? "hang_up" : "stream";',
        'if (action === "wait")': 'return "busy";',
    }
    for condition, button in expected_mappings.items():
        assert condition in function_body
        assert button in function_body
        assert function_body.index(condition) < function_body.index(button)


def test_bundled_card_uses_camera_state_machine_without_state_entity_overrides() -> None:
    source = CARD_SOURCE.read_text(encoding="utf-8")
    state_source = CARD_STATE_SOURCE.read_text(encoding="utf-8")

    assert "this._hass?.states?.[this._stateEntityId()]" not in source
    assert "c300xStateEntityId" not in source
    assert "c300xCardViewModel({" in source
    assert "c300xIsHomeCallActive(cameraEntity)" in state_source
    assert "c300xIsHomeCallConnected(cameraEntity)" in state_source
    assert "c300xHomeCallStatusKey(cameraEntity)" in state_source
    assert "stateEntity:" not in source
    assert 'mediaState === "home_call_active"' in state_source
    assert 'mediaState === "home_call_ringing"' in state_source
    assert 'return mediaState ? "busy" : cameraEntity.state;' in state_source
    assert "return false;" in state_source


def test_bundled_home_call_card_uses_local_ringback_tone_only_while_ringing() -> None:
    source = CARD_SOURCE.read_text(encoding="utf-8")
    resolver_source = CARD_RESOLVER_SOURCE.read_text(encoding="utf-8")
    ringback_source = CARD_RINGBACK_SOURCE.read_text(encoding="utf-8")
    state_source = CARD_STATE_SOURCE.read_text(encoding="utf-8")
    translations_source = CARD_TRANSLATIONS_SOURCE.read_text(encoding="utf-8")

    assert 'from "./c300x-ringback-tone.js"' in source
    assert "new C300XRingbackTone" in source
    assert "c300xIsHomeCallRinging(cameraEntity)" in state_source
    assert "this._syncRingbackTone(view.ringbackActive);" in source
    assert "this._stopRingbackTone();" in source
    assert 'mediaState === "home_call_starting"' in state_source
    assert 'mediaState === "home_call_ringing"' in state_source
    assert 'mediaState === "home_call_active"' not in state_source[
        state_source.index("export function c300xIsHomeCallRinging"):
        state_source.index("export function c300xDoorstationAction")
    ]
    assert "createOscillator" in ringback_source
    assert "440" in ringback_source
    assert "480" in ringback_source
    assert "C300X_RINGBACK_ON_MS" in ringback_source
    assert "ringback_tone: true" in resolver_source
    assert "ringback_volume: 12" in resolver_source
    assert 'ringback_tone: "Ringback tone"' in translations_source
    assert 'ringback_volume: "Ringback volume"' in translations_source
