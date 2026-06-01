from __future__ import annotations

import asyncio
import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from custom_components.bticino_c300x import agent_update
from custom_components.bticino_c300x.agent_update import (
    UPDATE_STATE_INCOMPATIBLE,
    UPDATE_STATE_UNKNOWN,
    UPDATE_STATE_UP_TO_DATE,
    UPDATE_STATE_UPDATE_AVAILABLE,
    async_apply_packaged_agent_update,
    compare_agent_bundle,
)


def test_compare_agent_bundle_detects_matching_bundle() -> None:
    state = compare_agent_bundle(
        {
            "version": "0.3.1",
            "api_version": "1",
            "agent": {
                "bundle_hash": "sha256:abc",
                "self_update_supported": True,
            },
        },
        {
            "agent_version": "0.3.1",
            "api_version": "1",
            "bundle_hash": "sha256:abc",
        },
    )

    assert state.state == UPDATE_STATE_UP_TO_DATE
    assert not state.update_required


def test_compare_agent_bundle_detects_missing_bundle() -> None:
    state = compare_agent_bundle(
        {"version": "0.3.1", "api_version": "1", "agent": {}},
        None,
    )

    assert state.state == UPDATE_STATE_UNKNOWN
    assert state.reason == "bundle_missing"


def test_compare_agent_bundle_requires_self_update_support() -> None:
    state = compare_agent_bundle(
        {
            "version": "0.3.1",
            "api_version": "1",
            "agent": {"self_update_supported": False},
        },
        {"agent_version": "0.3.1", "api_version": "1", "bundle_hash": "sha256:abc"},
    )

    assert state.state == UPDATE_STATE_INCOMPATIBLE
    assert state.update_required
    assert state.reason == "self_update_not_supported"
    assert state.repair_fixable
    assert not state.self_update_repair_supported


def test_compare_agent_bundle_accepts_matching_bundle_without_maintenance() -> None:
    state = compare_agent_bundle(
        {
            "version": "0.3.1",
            "api_version": "1",
            "agent": {
                "bundle_hash": "sha256:abc",
                "self_update_supported": False,
            },
        },
        {
            "agent_version": "0.3.1",
            "api_version": "1",
            "bundle_hash": "sha256:abc",
        },
    )

    assert state.state == UPDATE_STATE_UP_TO_DATE
    assert not state.update_required
    assert state.reason == "bticino_c300x"


def test_compare_agent_bundle_detects_version_mismatch() -> None:
    state = compare_agent_bundle(
        {
            "version": "0.2.0",
            "api_version": "1",
            "agent": {"self_update_supported": True},
        },
        {"agent_version": "0.3.1", "api_version": "1", "bundle_hash": "sha256:abc"},
    )

    assert state.state == UPDATE_STATE_UPDATE_AVAILABLE
    assert state.reason == "version_mismatch"
    assert state.repair_fixable
    assert state.self_update_repair_supported


def test_compare_agent_bundle_repairs_missing_installed_manifest() -> None:
    state = compare_agent_bundle(
        {
            "version": "0.3.1",
            "api_version": "1",
            "agent": {"self_update_supported": True},
        },
        {"agent_version": "0.3.1", "api_version": "1", "bundle_hash": "sha256:abc"},
    )

    assert state.state == UPDATE_STATE_UPDATE_AVAILABLE
    assert state.update_required
    assert state.repair_fixable
    assert state.self_update_repair_supported
    assert state.reason == "installed_bundle_manifest_missing"


class FakeUpdateApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def async_prepare_agent_update(
        self,
        *,
        bundle_hash: str,
        agent_version: str,
    ) -> dict[str, Any]:
        self.calls.append(
            ("prepare", {"bundle_hash": bundle_hash, "agent_version": agent_version})
        )
        return {"ok": True}

    async def async_upload_agent_update_chunk(
        self,
        *,
        path: str,
        sha256: str,
        mode: str,
        offset: int,
        data: bytes,
        final: bool,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "upload",
                {
                    "path": path,
                    "sha256": sha256,
                    "mode": mode,
                    "offset": offset,
                    "data": data,
                    "final": final,
                },
            )
        )
        return {"ok": True}

    async def async_apply_agent_update(self, *, bundle_hash: str) -> dict[str, Any]:
        self.calls.append(("apply", {"bundle_hash": bundle_hash}))
        return {"ok": True}


class FakeHass:
    def __init__(self) -> None:
        self.executor_jobs = 0

    async def async_add_executor_job(self, target, *args):  # noqa: ANN001
        self.executor_jobs += 1
        return target(*args)


def test_apply_packaged_agent_update_uploads_files_and_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    component = tmp_path / "bticino_c300x"
    payload = component / "device_agent" / "scripts" / "qml_patch.sh"
    manifest = component / "device_agent" / "bundle.json"
    payload.parent.mkdir(parents=True)
    payload.write_text("payload", encoding="utf-8")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest_data = {
        "agent_version": "0.3.1",
        "api_version": "1",
        "bundle_hash": "sha256:bundle",
        "files": [
            {
                "path": "device_agent/scripts/qml_patch.sh",
                "sha256": sha256(payload.read_bytes()).hexdigest(),
                "mode": "700",
            }
        ],
    }
    manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
    api = FakeUpdateApi()

    monkeypatch.setattr(agent_update, "COMPONENT_DIR", component)
    monkeypatch.setattr(agent_update, "BUNDLE_MANIFEST", manifest)
    hass = FakeHass()

    assert asyncio.run(async_apply_packaged_agent_update(hass, api)) == {"ok": True}

    assert hass.executor_jobs == 4
    assert api.calls[0] == (
        "prepare",
        {"bundle_hash": "sha256:bundle", "agent_version": "0.3.1"},
    )
    uploads = [payload for name, payload in api.calls if name == "upload"]
    assert [entry["path"] for entry in uploads] == [
        "device_agent/scripts/qml_patch.sh",
        "device_agent/bundle.json",
    ]
    assert uploads[0]["data"] == b"payload"
    assert uploads[0]["final"] is True
    assert uploads[1]["sha256"] == sha256(manifest.read_bytes()).hexdigest()
    assert api.calls[-1] == ("apply", {"bundle_hash": "sha256:bundle"})
