from __future__ import annotations

import asyncio
import json
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from custom_components.bticino_c300x import agent_update
from custom_components.bticino_c300x.agent_update import (
    UPDATE_STATE_INCOMPATIBLE,
    UPDATE_STATE_UNKNOWN,
    UPDATE_STATE_UP_TO_DATE,
    UPDATE_STATE_UPDATE_AVAILABLE,
    AgentUpdateState,
    agent_update_repair_placeholders,
    async_apply_packaged_agent_update,
    compare_agent_bundle,
    load_packaged_bundle_metadata,
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


def test_load_packaged_bundle_metadata_rejects_missing_invalid_and_non_object(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.json"
    invalid = tmp_path / "invalid.json"
    non_object = tmp_path / "non-object.json"
    invalid.write_text("{", encoding="utf-8")
    non_object.write_text("[]", encoding="utf-8")

    assert load_packaged_bundle_metadata(missing) is None
    assert load_packaged_bundle_metadata(invalid) is None
    assert load_packaged_bundle_metadata(non_object) is None


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


def test_compare_agent_bundle_detects_version_and_api_metadata_problems() -> None:
    missing_version = compare_agent_bundle(
        {"api_version": "1", "agent": {"self_update_supported": True}},
        {"api_version": "1", "bundle_hash": "sha256:abc"},
    )
    api_mismatch = compare_agent_bundle(
        {
            "version": "0.3.1",
            "api_version": "1",
            "agent": {"self_update_supported": True},
        },
        {"agent_version": "0.3.1", "api_version": "2", "bundle_hash": "sha256:abc"},
    )
    hash_mismatch = compare_agent_bundle(
        {
            "version": "0.3.1",
            "api_version": "1",
            "agent": {
                "bundle_hash": "sha256:installed",
                "self_update_supported": True,
            },
        },
        {
            "agent_version": "0.3.1",
            "api_version": "1",
            "bundle_hash": "sha256:available",
        },
    )

    assert missing_version.state == UPDATE_STATE_UNKNOWN
    assert missing_version.reason == "version_missing"
    assert api_mismatch.state == UPDATE_STATE_INCOMPATIBLE
    assert api_mismatch.reason == "api_version_mismatch"
    assert hash_mismatch.state == UPDATE_STATE_UPDATE_AVAILABLE
    assert hash_mismatch.reason == "bundle_hash_mismatch"


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


def test_agent_update_repair_placeholders_include_hashes_path_and_patch_status() -> None:
    placeholders = agent_update_repair_placeholders(
        AgentUpdateState(
            state=UPDATE_STATE_UPDATE_AVAILABLE,
            installed_version="0.4.0",
            available_version="0.5.0",
            installed_api_version="1",
            available_api_version="1",
            installed_bundle_hash="sha256:installed-bundle",
            available_bundle_hash="sha256:available-bundle",
            self_update_supported=True,
            reason="bundle_hash_mismatch",
        ),
        type("Runtime", (), {"qml_patch_status": {"state": "patched"}})(),
    )

    assert placeholders["installed_bundle_hash"] == "sha256:insta"
    assert placeholders["available_bundle_hash"] == "sha256:avail"
    assert placeholders["update_path"] == "self-update"
    assert placeholders["qml_patch_status"] == "patched"


def test_agent_update_repair_placeholders_report_no_update_path() -> None:
    placeholders = agent_update_repair_placeholders(
        AgentUpdateState(
            state=UPDATE_STATE_UP_TO_DATE,
            installed_version="1.1.0",
            available_version="1.1.0",
        )
    )

    assert placeholders["update_path"] == "none"


def test_agent_update_repair_placeholders_cover_unknown_and_patch_boolean_states() -> None:
    unknown = agent_update_repair_placeholders(None, object())
    patched = agent_update_repair_placeholders(
        None,
        type("Runtime", (), {"qml_patch_status": {"patched": True}})(),
    )
    original = agent_update_repair_placeholders(
        None,
        type("Runtime", (), {"qml_patch_status": {"patched": False}})(),
    )

    assert unknown["installed_version"] == "unknown"
    assert unknown["update_path"] == "unknown"
    assert unknown["qml_patch_status"] == "unknown"
    assert patched["qml_patch_status"] == "patched"
    assert original["qml_patch_status"] == "original"


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


def test_apply_packaged_agent_update_uses_legacy_safe_upload_chunks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    component = tmp_path / "bticino_c300x"
    payload = component / "device_agent" / "armhf" / "c300x-agent-native"
    manifest = component / "device_agent" / "bundle.json"
    payload.parent.mkdir(parents=True)
    payload.write_bytes(b"x" * 5000)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest_data = {
        "agent_version": "1.1.0",
        "api_version": "1",
        "bundle_hash": "sha256:bundle",
        "files": [
            {
                "path": "device_agent/armhf/c300x-agent-native",
                "sha256": sha256(payload.read_bytes()).hexdigest(),
                "mode": "700",
            }
        ],
    }
    manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
    api = FakeUpdateApi()

    monkeypatch.setattr(agent_update, "COMPONENT_DIR", component)
    monkeypatch.setattr(agent_update, "BUNDLE_MANIFEST", manifest)

    assert asyncio.run(async_apply_packaged_agent_update(FakeHass(), api)) == {"ok": True}

    payload_uploads = [
        payload
        for name, payload in api.calls
        if name == "upload"
        and payload["path"] == "device_agent/armhf/c300x-agent-native"
    ]
    assert len(payload_uploads) == 3
    assert all(len(upload["data"]) <= 2048 for upload in payload_uploads)
    assert [upload["offset"] for upload in payload_uploads] == [0, 2048, 4096]
    assert payload_uploads[-1]["final"] is True


def test_apply_packaged_agent_update_rejects_missing_or_incomplete_bundle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manifest = tmp_path / "bticino_c300x" / "device_agent" / "bundle.json"
    manifest.parent.mkdir(parents=True)
    monkeypatch.setattr(agent_update, "BUNDLE_MANIFEST", manifest)

    with pytest.raises(RuntimeError, match="bundle is missing"):
        asyncio.run(async_apply_packaged_agent_update(FakeHass(), FakeUpdateApi()))

    manifest.write_text(
        json.dumps({"agent_version": "1.1.0", "bundle_hash": "sha256:bundle"}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="metadata is incomplete"):
        asyncio.run(async_apply_packaged_agent_update(FakeHass(), FakeUpdateApi()))


def test_apply_packaged_agent_update_rejects_invalid_file_entries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    component = tmp_path / "bticino_c300x"
    manifest = component / "device_agent" / "bundle.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "agent_version": "1.1.0",
                "api_version": "1",
                "bundle_hash": "sha256:bundle",
                "files": [None],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(agent_update, "COMPONENT_DIR", component)
    monkeypatch.setattr(agent_update, "BUNDLE_MANIFEST", manifest)

    with pytest.raises(RuntimeError, match="file entry is invalid"):
        asyncio.run(async_apply_packaged_agent_update(FakeHass(), FakeUpdateApi()))


def test_apply_packaged_agent_update_rejects_invalid_bundle_file_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    component = tmp_path / "bticino_c300x"
    manifest = component / "device_agent" / "bundle.json"
    manifest.parent.mkdir(parents=True)
    monkeypatch.setattr(agent_update, "COMPONENT_DIR", component)
    monkeypatch.setattr(agent_update, "BUNDLE_MANIFEST", manifest)

    manifest.write_text(
        json.dumps(
            {
                "agent_version": "1.1.0",
                "api_version": "1",
                "bundle_hash": "sha256:bundle",
                "files": [
                    {"path": "../bad", "sha256": "sha256:bad", "mode": "700"}
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="file path is invalid"):
        asyncio.run(async_apply_packaged_agent_update(FakeHass(), FakeUpdateApi()))

    manifest.write_text(
        json.dumps(
            {
                "agent_version": "1.1.0",
                "api_version": "1",
                "bundle_hash": "sha256:bundle",
                "files": [
                    {
                        "path": "device_agent/scripts/missing.sh",
                        "sha256": "sha256:missing",
                        "mode": "700",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="file path is invalid"):
        asyncio.run(async_apply_packaged_agent_update(FakeHass(), FakeUpdateApi()))


def test_apply_packaged_agent_update_uploads_empty_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    component = tmp_path / "bticino_c300x"
    payload = component / "device_agent" / "scripts" / "empty.sh"
    manifest = component / "device_agent" / "bundle.json"
    payload.parent.mkdir(parents=True)
    payload.write_bytes(b"")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "agent_version": "1.1.0",
                "api_version": "1",
                "bundle_hash": "sha256:bundle",
                "files": [
                    {
                        "path": "device_agent/scripts/empty.sh",
                        "sha256": sha256(b"").hexdigest(),
                        "mode": "700",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    api = FakeUpdateApi()

    monkeypatch.setattr(agent_update, "COMPONENT_DIR", component)
    monkeypatch.setattr(agent_update, "BUNDLE_MANIFEST", manifest)

    asyncio.run(async_apply_packaged_agent_update(FakeHass(), api))

    empty_upload = next(
        payload
        for name, payload in api.calls
        if name == "upload" and payload["path"] == "device_agent/scripts/empty.sh"
    )
    assert empty_upload["data"] == b""
    assert empty_upload["offset"] == 0
    assert empty_upload["final"] is True
