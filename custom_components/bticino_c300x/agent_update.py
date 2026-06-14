"""Device-agent bundle metadata and update comparison helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .const import DOMAIN

COMPONENT_DIR = Path(__file__).resolve().parent
BUNDLE_MANIFEST = COMPONENT_DIR / "device_agent" / "bundle.json"
UPLOAD_CHUNK_SIZE = 2048

UPDATE_STATE_UP_TO_DATE = "up_to_date"
UPDATE_STATE_UPDATE_AVAILABLE = "update_available"
UPDATE_STATE_INCOMPATIBLE = "incompatible"
UPDATE_STATE_UNKNOWN = "unknown"
_UNKNOWN_REPAIR_VALUE = "unknown"


@dataclass(frozen=True, slots=True)
class AgentUpdateState:
    """Comparison between installed native agent and packaged device bundle."""

    state: str
    installed_version: str | None = None
    available_version: str | None = None
    installed_api_version: str | None = None
    available_api_version: str | None = None
    installed_bundle_hash: str | None = None
    available_bundle_hash: str | None = None
    self_update_supported: bool = False
    reason: str | None = None

    @property
    def update_required(self) -> bool:
        """Return true when the user should run the agent update repair."""

        return self.state in {UPDATE_STATE_UPDATE_AVAILABLE, UPDATE_STATE_INCOMPATIBLE}

    @property
    def repair_fixable(self) -> bool:
        """Return true when HA can guide the user through a local repair."""

        return self.update_required

    @property
    def self_update_repair_supported(self) -> bool:
        """Return true when the installed agent can update itself."""

        return self.update_required and self.self_update_supported and self.reason in {
            "bundle_hash_mismatch",
            "installed_bundle_manifest_missing",
            "version_mismatch",
        }

    @property
    def repair_placeholders(self) -> dict[str, str]:
        """Return safe Repairs placeholders without private connection details."""

        return {
            "installed_version": self.installed_version or _UNKNOWN_REPAIR_VALUE,
            "available_version": self.available_version or _UNKNOWN_REPAIR_VALUE,
            "installed_api_version": self.installed_api_version or _UNKNOWN_REPAIR_VALUE,
            "available_api_version": self.available_api_version or _UNKNOWN_REPAIR_VALUE,
            "installed_bundle_hash": _short_hash(self.installed_bundle_hash),
            "available_bundle_hash": _short_hash(self.available_bundle_hash),
            "reason": self.reason or self.state,
            "update_path": _update_path_label(self),
        }


def load_packaged_bundle_metadata(path: Path | None = None) -> dict[str, Any] | None:
    """Load packaged native-agent bundle metadata if this install includes it."""

    manifest_path = path or BUNDLE_MANIFEST
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


async def async_load_packaged_bundle_metadata(
    hass: Any,
    path: Path | None = None,
) -> dict[str, Any] | None:
    """Load packaged native-agent metadata outside the event loop."""

    return await hass.async_add_executor_job(load_packaged_bundle_metadata, path)


def compare_agent_bundle(
    setup_data: dict[str, Any],
    bundle: dict[str, Any] | None,
) -> AgentUpdateState:
    """Compare the installed agent metadata with the packaged bundle metadata."""

    if not bundle:
        return AgentUpdateState(state=UPDATE_STATE_UNKNOWN, reason="bundle_missing")

    agent = setup_data.get("agent") if isinstance(setup_data.get("agent"), dict) else {}
    installed_version = str(setup_data.get("version") or agent.get("version") or "")
    installed_api_version = str(setup_data.get("api_version") or "")
    installed_bundle_hash = str(agent.get("bundle_hash") or "")
    self_update_supported = bool(agent.get("self_update_supported"))
    available_version = str(bundle.get("agent_version") or bundle.get("version") or "")
    available_api_version = str(bundle.get("api_version") or "")
    available_bundle_hash = str(bundle.get("bundle_hash") or "")

    common = {
        "installed_version": installed_version or None,
        "available_version": available_version or None,
        "installed_api_version": installed_api_version or None,
        "available_api_version": available_api_version or None,
        "installed_bundle_hash": installed_bundle_hash or None,
        "available_bundle_hash": available_bundle_hash or None,
        "self_update_supported": self_update_supported,
    }
    if not installed_version or not available_version:
        return AgentUpdateState(state=UPDATE_STATE_UNKNOWN, reason="version_missing", **common)
    if installed_api_version and available_api_version and installed_api_version != available_api_version:
        return AgentUpdateState(
            state=UPDATE_STATE_INCOMPATIBLE,
            reason="api_version_mismatch",
            **common,
        )
    if (
        installed_version == available_version
        and (
            not available_bundle_hash
            or (
                installed_bundle_hash
                and installed_bundle_hash == available_bundle_hash
            )
        )
    ):
        return AgentUpdateState(state=UPDATE_STATE_UP_TO_DATE, reason=DOMAIN, **common)
    if not self_update_supported:
        return AgentUpdateState(
            state=UPDATE_STATE_INCOMPATIBLE,
            reason="self_update_not_supported",
            **common,
        )
    if installed_version != available_version:
        return AgentUpdateState(
            state=UPDATE_STATE_UPDATE_AVAILABLE,
            reason="version_mismatch",
            **common,
        )
    if available_bundle_hash and not installed_bundle_hash:
        return AgentUpdateState(
            state=UPDATE_STATE_UPDATE_AVAILABLE,
            reason="installed_bundle_manifest_missing",
            **common,
        )
    if installed_bundle_hash and available_bundle_hash and installed_bundle_hash != available_bundle_hash:
        return AgentUpdateState(
            state=UPDATE_STATE_UPDATE_AVAILABLE,
            reason="bundle_hash_mismatch",
            **common,
        )
    return AgentUpdateState(state=UPDATE_STATE_UP_TO_DATE, reason=DOMAIN, **common)


def agent_update_repair_placeholders(
    update_state: AgentUpdateState | None,
    runtime_data: Any | None = None,
) -> dict[str, str]:
    """Return repair placeholders with safe runtime context."""

    if update_state is None:
        placeholders = {
            "installed_version": _UNKNOWN_REPAIR_VALUE,
            "available_version": _UNKNOWN_REPAIR_VALUE,
            "installed_api_version": _UNKNOWN_REPAIR_VALUE,
            "available_api_version": _UNKNOWN_REPAIR_VALUE,
            "installed_bundle_hash": _UNKNOWN_REPAIR_VALUE,
            "available_bundle_hash": _UNKNOWN_REPAIR_VALUE,
            "reason": _UNKNOWN_REPAIR_VALUE,
            "update_path": _UNKNOWN_REPAIR_VALUE,
        }
    else:
        placeholders = update_state.repair_placeholders
    placeholders["qml_patch_status"] = _runtime_qml_patch_status(runtime_data)
    return placeholders


async def async_apply_packaged_agent_update(hass: Any, api: Any) -> dict[str, Any]:
    """Upload and apply the packaged native-agent bundle through maintenance API."""

    bundle = await async_load_packaged_bundle_metadata(hass)
    if not bundle:
        raise RuntimeError("packaged native-agent bundle is missing")
    bundle_hash = str(bundle.get("bundle_hash") or "")
    agent_version = str(bundle.get("agent_version") or bundle.get("version") or "")
    files = bundle.get("files")
    if not bundle_hash or not agent_version or not isinstance(files, list):
        raise RuntimeError("packaged native-agent bundle metadata is incomplete")

    await api.async_prepare_agent_update(
        bundle_hash=bundle_hash,
        agent_version=agent_version,
    )
    for entry in files:
        if not isinstance(entry, dict):
            raise RuntimeError("packaged native-agent bundle file entry is invalid")
        await _async_upload_bundle_file(hass, api, entry)
    manifest_data = await _async_read_file_bytes(hass, BUNDLE_MANIFEST)
    await _async_upload_bundle_file(
        hass,
        api,
        {
            "path": "device_agent/bundle.json",
            "sha256": sha256(manifest_data).hexdigest(),
            "mode": "600",
        },
    )
    return await api.async_apply_agent_update(bundle_hash=bundle_hash)


async def _async_upload_bundle_file(hass: Any, api: Any, entry: dict[str, Any]) -> None:
    relative_path = str(entry.get("path") or "")
    sha256 = str(entry.get("sha256") or "")
    mode = str(entry.get("mode") or "600")
    source = (COMPONENT_DIR / relative_path).resolve()
    if (
        not relative_path
        or relative_path.startswith("../")
        or source.parent == source
        or COMPONENT_DIR not in source.parents
    ):
        raise RuntimeError("packaged native-agent bundle file path is invalid")
    try:
        data = await _async_read_file_bytes(hass, source)
    except OSError as err:
        raise RuntimeError("packaged native-agent bundle file path is invalid") from err
    if not data:
        await api.async_upload_agent_update_chunk(
            path=relative_path,
            sha256=sha256,
            mode=mode,
            offset=0,
            data=b"",
            final=True,
        )
        return
    for offset in range(0, len(data), UPLOAD_CHUNK_SIZE):
        chunk = data[offset : offset + UPLOAD_CHUNK_SIZE]
        await api.async_upload_agent_update_chunk(
            path=relative_path,
            sha256=sha256,
            mode=mode,
            offset=offset,
            data=chunk,
            final=offset + len(chunk) >= len(data),
        )


async def _async_read_file_bytes(hass: Any, path: Path) -> bytes:
    """Read a packaged file outside the event loop."""

    return await hass.async_add_executor_job(path.read_bytes)


def _short_hash(value: str | None) -> str:
    if not value:
        return _UNKNOWN_REPAIR_VALUE
    return value[:12]


def _update_path_label(update_state: AgentUpdateState) -> str:
    if not update_state.update_required:
        return "none"
    if update_state.self_update_repair_supported:
        return "self-update"
    return "SSH reinstall"


def _runtime_qml_patch_status(runtime_data: Any | None) -> str:
    status = getattr(runtime_data, "qml_patch_status", None)
    if not isinstance(status, dict):
        return _UNKNOWN_REPAIR_VALUE
    state = status.get("state")
    if isinstance(state, str) and state:
        return state
    patched = status.get("patched")
    if patched is True:
        return "patched"
    if patched is False:
        return "original"
    return _UNKNOWN_REPAIR_VALUE
