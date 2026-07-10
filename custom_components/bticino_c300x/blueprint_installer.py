"""Install bundled Home Assistant blueprints into the user config directory."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_SOURCE_DIR = Path(__file__).with_name("blueprints") / "automation" / DOMAIN
_TARGET_RELATIVE_DIR = ("blueprints", "automation", DOMAIN)
_MANIFEST_FILENAME = ".bticino_c300x_blueprints.json"
_OBSOLETE_BLUEPRINT_FILES = frozenset(
    {
        "doorbell_call_mobile_dashboard.yaml",
        "doorbell_call_notification.yaml",
    }
)


@dataclass(frozen=True, slots=True)
class BlueprintInstallResult:
    """Result of syncing bundled blueprint files into the HA config directory."""

    installed: list[Path]
    updated: list[Path]
    removed: list[Path]

    @property
    def changed(self) -> bool:
        """Return whether any target file changed."""

        return bool(self.installed or self.updated or self.removed)


async def async_install_bundled_blueprints(hass: HomeAssistant) -> None:
    """Install bundled C300X automation blueprints."""

    result = await hass.async_add_executor_job(
        install_bundled_blueprints,
        Path(hass.config.path(*_TARGET_RELATIVE_DIR)),
    )
    if result.installed or result.updated:
        _async_schedule_automation_reload(hass)


def install_bundled_blueprints(target_dir: Path) -> BlueprintInstallResult:
    """Synchronize bundled blueprint files and return changed targets."""

    if not _SOURCE_DIR.is_dir():
        _LOGGER.debug("C300X bundled blueprint directory is missing: %s", _SOURCE_DIR)
        return BlueprintInstallResult(installed=[], updated=[], removed=[])
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest(target_dir)
    manifest_changed = False
    removed: list[Path] = []
    for filename in _OBSOLETE_BLUEPRINT_FILES:
        target = target_dir / filename
        if target.exists():
            target.unlink()
            removed.append(target)
        if filename in manifest:
            manifest.pop(filename)
            manifest_changed = True
    installed: list[Path] = []
    updated: list[Path] = []
    for source in sorted(_SOURCE_DIR.glob("*.yaml")):
        target = target_dir / source.name
        source_bytes = source.read_bytes()
        source_hash = _content_hash(source_bytes)
        if target.exists():
            target_bytes = target.read_bytes()
            target_hash = _content_hash(target_bytes)
            managed_hash = manifest.get(source.name)
            if target_bytes == source_bytes:
                if managed_hash != source_hash:
                    manifest[source.name] = source_hash
                    manifest_changed = True
                continue
            if managed_hash != target_hash:
                _LOGGER.debug(
                    "Preserving customized C300X automation blueprint: %s",
                    target,
                )
                continue
            shutil.copy2(source, target)
            manifest[source.name] = source_hash
            manifest_changed = True
            updated.append(target)
        else:
            shutil.copy2(source, target)
            manifest[source.name] = source_hash
            manifest_changed = True
            installed.append(target)
    if manifest_changed:
        _write_manifest(target_dir, manifest)
    if installed:
        _LOGGER.info(
            "Installed %d C300X automation blueprint(s) into %s",
            len(installed),
            target_dir,
        )
    if updated:
        _LOGGER.info(
            "Updated %d C300X automation blueprint(s) in %s",
            len(updated),
            target_dir,
        )
    if removed:
        _LOGGER.info(
            "Removed %d obsolete C300X automation blueprint(s) from %s",
            len(removed),
            target_dir,
        )
    return BlueprintInstallResult(installed=installed, updated=updated, removed=removed)


def _content_hash(content: bytes) -> str:
    """Return the stable content hash used by the managed-blueprint manifest."""

    return sha256(content).hexdigest()


def _load_manifest(target_dir: Path) -> dict[str, str]:
    """Load the managed-blueprint manifest, or return an empty manifest."""

    try:
        payload = json.loads(
            (target_dir / _MANIFEST_FILENAME).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    files = payload.get("files")
    if not isinstance(files, dict):
        return {}
    return {
        str(filename): digest
        for filename, digest in files.items()
        if isinstance(filename, str) and isinstance(digest, str)
    }


def _write_manifest(target_dir: Path, manifest: dict[str, str]) -> None:
    """Write the managed-blueprint manifest."""

    payload = {
        "version": 1,
        "files": dict(sorted(manifest.items())),
    }
    (target_dir / _MANIFEST_FILENAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _async_schedule_automation_reload(hass: HomeAssistant) -> None:
    """Reload automations after bundled blueprint files changed."""

    async def _async_reload_automations(_event: object | None = None) -> None:
        if not hass.services.has_service("automation", "reload"):
            _LOGGER.debug(
                "C300X bundled blueprints changed but automation.reload is unavailable"
            )
            return
        _LOGGER.info("Reloading automations after C300X blueprint update")
        await hass.services.async_call("automation", "reload", {}, blocking=False)

    if getattr(hass, "is_running", False):
        hass.async_create_task(_async_reload_automations())
        return

    async def _async_reload_once(event: object) -> None:
        await _async_reload_automations(event)

    hass.bus.async_listen_once(
        EVENT_HOMEASSISTANT_STARTED,
        _async_reload_once,
    )
