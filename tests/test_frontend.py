from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import dataclass
from typing import Any

from custom_components.bticino_c300x.const import DOMAIN
from custom_components.bticino_c300x.frontend import (
    DATA_FRONTEND_MODULE_URL,
    DOORBELL_CALL_CARD_FILENAME,
    FRONTEND_DIR,
    FRONTEND_URL_PATH,
    _async_ensure_lovelace_resource,
    async_setup_frontend,
)

CARD_SOURCE = FRONTEND_DIR / DOORBELL_CALL_CARD_FILENAME


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


def test_async_setup_frontend_registers_bundled_card_once(monkeypatch: Any) -> None:
    http_module = types.ModuleType("homeassistant.components.http")
    http_module.StaticPathConfig = _StaticPathConfig
    monkeypatch.setitem(sys.modules, "homeassistant.components.http", http_module)

    hass = _FakeHass()

    asyncio.run(async_setup_frontend(hass))
    asyncio.run(async_setup_frontend(hass))

    assert hass.http.static_paths == [
        _StaticPathConfig(FRONTEND_URL_PATH, str(FRONTEND_DIR), True)
    ]
    assert hass.extra_module_urls == []
    module_url = hass.data[DOMAIN][DATA_FRONTEND_MODULE_URL]
    assert module_url.startswith(
        f"{FRONTEND_URL_PATH}/{DOORBELL_CALL_CARD_FILENAME}?v="
    )
    assert hass.data[DOMAIN][DATA_FRONTEND_MODULE_URL] == module_url


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
    assert 'getGridOptions()' in source
    assert "rows: 4" in source
    assert "columns: 12" in source
    assert "min_rows: 4" in source
    assert "max_rows: 4" in source
    assert "min_columns: 6" in source
    assert "return this._isHomeCallMode() ? 1 : 6;" in source
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
    assert ".filter((entityId)" not in source
    assert ".sort((left, right)" not in source
    assert 'name: "state_entity"' not in source
    assert 'name: "state_label"' not in source
    assert 'customElements.define("c300x-doorbell-call-card-editor"' in source
    assert 'customElements.get(C300X_CARD_TAG)' in source
    for language in ("en", "de", "fr", "it"):
        assert f"  {language}: {{" in source
    assert "state_entity" not in source
    assert "state_label" not in source
    assert "bticino_c300x_doorbell_camera" in source
    assert "script.c300x_stop_doorbell_call_simulation" not in source
    assert "<ha-button" not in source
    assert "Answer / Talkback" not in source
    assert "Offer Audio" not in source


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


def test_bundled_card_answers_only_real_ring_media() -> None:
    source = CARD_SOURCE.read_text(encoding="utf-8")

    assert "_isRingCallPending(entity, cameraEntity)" in source
    assert "_isRingCallAvailable(entity, cameraEntity)" in source
    assert 'attributes.video_owner === "ring"' in source
    assert 'if (entity?.state === "ringing" || entity?.state === "doorbell_pressed")' not in source
    assert 'return "answer";\n    }\n    return "stream";' not in source
