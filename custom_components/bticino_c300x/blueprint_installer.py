"""Install bundled Home Assistant blueprints into the user config directory."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_SOURCE_DIR = Path(__file__).with_name("blueprints") / "automation" / DOMAIN
_TARGET_RELATIVE_DIR = ("blueprints", "automation", DOMAIN)
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
    removed: list[Path] = []
    for filename in _OBSOLETE_BLUEPRINT_FILES:
        target = target_dir / filename
        if target.exists():
            target.unlink()
            removed.append(target)
    installed: list[Path] = []
    updated: list[Path] = []
    for source in sorted(_SOURCE_DIR.glob("*.yaml")):
        target = target_dir / source.name
        if target.exists():
            if target.read_bytes() == source.read_bytes():
                continue
            shutil.copy2(source, target)
            updated.append(target)
        else:
            shutil.copy2(source, target)
            installed.append(target)
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
