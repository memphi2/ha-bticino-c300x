from __future__ import annotations

import asyncio
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
    async_setup_frontend,
)

CARD_SOURCE = FRONTEND_DIR / DOORBELL_CALL_CARD_FILENAME
CARD_METADATA_SOURCE = FRONTEND_DIR / DOORBELL_CALL_CARD_METADATA_FILENAME
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
        _StaticPathConfig(FRONTEND_URL_PATH, str(FRONTEND_DIR), True)
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


def test_bundled_card_supports_editor_languages_and_multi_device_config() -> None:
    source = CARD_SOURCE.read_text(encoding="utf-8")

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
    assert 'config_entry_id' in source
    assert "_autoRelatedEntityId" in source
    assert "_firstRelatedEntityId" in source
    assert "translation_key" in source
    assert "unique_id" in source
    assert "C300X_DOORBELL_STATE_TRANSLATION_KEY" in source
    assert "C300X_HOME_CALL_TRANSLATION_KEY" in source
    assert ".filter((entityId)" not in source
    assert ".sort((left, right)" not in source
    assert 'name: "state_entity"' not in source
    assert 'name: "state_label"' not in source
    assert 'name: "doorbell_state_entity"' in source
    assert 'name: "home_call_entity"' in source
    assert 'selector: { entity: { domain: "sensor" } }' in source
    assert 'selector: { entity: { domain: "binary_sensor" } }' in source
    assert "doorbell_state_entity: entityId" in source
    assert "home_call_entity: entityId" in source
    assert 'customElements.define("c300x-doorbell-call-card-editor"' in source
    assert 'customElements.get(C300X_CARD_TAG)' in source
    for language in ("en", "de", "fr", "it"):
        assert f"  {language}: {{" in source
    assert '"state_entity"' not in source
    assert "state_label" not in source
    assert "_config.doorbell_state_entity" in source
    assert "_config.home_call_entity" in source
    assert "bticino_c300x_doorbell_camera" in source
    assert "script.c300x_stop_doorbell_call_simulation" not in source
    assert "<ha-button" not in source
    assert "Answer / Talkback" not in source
    assert "Offer Audio" not in source


def test_picker_metadata_is_split_from_card_custom_element_module() -> None:
    source = CARD_SOURCE.read_text(encoding="utf-8")
    metadata_source = CARD_METADATA_SOURCE.read_text(encoding="utf-8")

    assert "window.customCards.push" in metadata_source
    assert "doorbell_state_entity: entityId" in metadata_source
    assert "home_call_entity: entityId" in metadata_source
    assert "c300xMetadataRegistryEntity" in metadata_source
    assert "c300xMetadataRelatedCamera" in metadata_source
    assert "translation_key" in metadata_source
    assert "unique_id" in metadata_source
    assert "getEntitySuggestion: c300xMetadataEntitySuggestion" in metadata_source
    assert "customElements.define" not in metadata_source
    assert "extends HTMLElement" not in metadata_source
    assert "window.customCards.push" in source
    assert 'customElements.define(C300X_CARD_TAG, C300XDoorbellCallCard)' in source


def test_bundled_card_handles_missing_microphone_without_breaking_stream() -> None:
    source = CARD_SOURCE.read_text(encoding="utf-8")

    assert "async _prepareMicrophone()" in source
    assert 'this._label("microphone_required")' in source
    assert 'this._label("microphone_stream_only")' in source
    assert "this._notice" in source
    assert 'this._notice = this._label("microphone_required")' in source
    assert 'this._notice = this._label("microphone_stream_only")' in source
    assert 'throw new Error(this._label("microphone_required"))' not in source
    assert 'pc.addTransceiver("video", { direction: "recvonly" });' in source
    assert 'pc.addTransceiver("audio", { direction: "recvonly" });' in source
    assert "navigator.mediaDevices.getUserMedia" not in source
    assert 'typeof getUserMedia !== "function"' in source


def test_bundled_card_marks_external_doorstation_calls_not_controllable() -> None:
    source = CARD_SOURCE.read_text(encoding="utf-8")

    assert 'external_call: "External Call"' in source
    assert 'action === "external_call" ? "mdi:phone-off"' in source
    assert 'this._actionButtonEl.disabled = action === "external_call";' in source
    assert 'if (action === "external_call") {' in source
    assert "return attributes.external_media_active === true" in source
    assert 'attributes.video_owner === "external_media"' in source
    assert 'attributes.external_owner === "external_media"' in source


def test_bundled_card_answers_pending_doorbell_state_without_camera_owner() -> None:
    source = CARD_SOURCE.read_text(encoding="utf-8")

    assert "_isRingCallPending(entity, cameraEntity)" in source
    assert "_isRingCallAvailable(entity, cameraEntity)" in source
    assert source.index("this._isRingCallPending(entity, cameraEntity)") < source.index("if (active) {")
    assert 'attributes.video_owner === "ring"' in source
    assert 'state === "ringing" || state === "doorbell_pressed"' in source
    assert "&& !this._isExternalDoorstationMedia(cameraEntity)" in source


def test_bundled_card_starts_ring_preview_without_answer_audio() -> None:
    source = CARD_SOURCE.read_text(encoding="utf-8")

    assert "async _ensureDoorbellPreview()" in source
    assert 'doorstationAction === "answer"' in source
    assert "_isRingPreviewAvailable(cameraEntity)" in source
    assert 'attributes.video_owner === "ring"' in source
    assert "this._ringPreviewActive = true;" in source
    assert "this._startTalkback({ microphone: false, receiveAudio: false })" in source
    assert "} else if (receiveAudio) {" in source
