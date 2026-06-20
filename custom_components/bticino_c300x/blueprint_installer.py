"""Install bundled Home Assistant blueprints into the user config directory."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_SOURCE_DIR = Path(__file__).with_name("blueprints") / "automation" / DOMAIN
_TARGET_RELATIVE_DIR = ("blueprints", "automation", DOMAIN)


async def async_install_bundled_blueprints(hass: HomeAssistant) -> None:
    """Install bundled C300X automation blueprints when they are missing."""

    await hass.async_add_executor_job(
        install_bundled_blueprints,
        Path(hass.config.path(*_TARGET_RELATIVE_DIR)),
    )


def install_bundled_blueprints(target_dir: Path) -> list[Path]:
    """Copy missing bundled blueprint files and return installed targets."""

    if not _SOURCE_DIR.is_dir():
        _LOGGER.debug("C300X bundled blueprint directory is missing: %s", _SOURCE_DIR)
        return []
    target_dir.mkdir(parents=True, exist_ok=True)
    installed: list[Path] = []
    for source in sorted(_SOURCE_DIR.glob("*.yaml")):
        target = target_dir / source.name
        if target.exists():
            continue
        shutil.copy2(source, target)
        installed.append(target)
    if installed:
        _LOGGER.info(
            "Installed %d C300X automation blueprint(s) into %s",
            len(installed),
            target_dir,
        )
    return installed
