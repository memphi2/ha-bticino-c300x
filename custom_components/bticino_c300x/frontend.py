"""Frontend assets for the BTicino C300X integration."""

from __future__ import annotations

from contextlib import suppress
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

FRONTEND_DIR = Path(__file__).with_name("frontend")
FRONTEND_URL_PATH = f"/{DOMAIN}/frontend"
DOORBELL_CALL_CARD_FILENAME = "c300x-doorbell-call-card.js"
DOORBELL_CALL_CARD_METADATA_FILENAME = "c300x-doorbell-call-card-metadata.js"
DATA_FRONTEND_MODULE_URL = "frontend_module_url"
DATA_FRONTEND_METADATA_URL = "frontend_metadata_url"


async def async_setup_frontend(hass: HomeAssistant) -> None:
    """Register the bundled Lovelace card frontend module."""

    domain_data: dict[str, Any] = hass.data.setdefault(DOMAIN, {})
    module_version = await _async_frontend_asset_version(
        hass,
        DOORBELL_CALL_CARD_FILENAME,
    )
    metadata_version = await _async_frontend_asset_version(
        hass,
        DOORBELL_CALL_CARD_METADATA_FILENAME,
    )
    module_url = (
        f"{FRONTEND_URL_PATH}/{DOORBELL_CALL_CARD_FILENAME}"
        f"?v={module_version}"
    )
    metadata_url = (
        f"{FRONTEND_URL_PATH}/{DOORBELL_CALL_CARD_METADATA_FILENAME}"
        f"?v={metadata_version}"
    )
    previous_module_url = domain_data.get(DATA_FRONTEND_MODULE_URL)
    previous_metadata_url = domain_data.get(DATA_FRONTEND_METADATA_URL)
    if previous_module_url != module_url or previous_metadata_url != metadata_url:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(FRONTEND_URL_PATH, str(FRONTEND_DIR), True)]
        )
        _register_frontend_module_url(
            hass,
            metadata_url,
            (previous_metadata_url, previous_module_url),
        )
        domain_data[DATA_FRONTEND_MODULE_URL] = module_url
        domain_data[DATA_FRONTEND_METADATA_URL] = metadata_url
    await _async_ensure_lovelace_resource(hass, module_url)


def _register_frontend_module_url(
    hass: HomeAssistant,
    metadata_url: str,
    previous_urls: tuple[Any, ...],
) -> None:
    """Make Home Assistant load card metadata for the add-card picker."""

    try:
        from homeassistant.components import frontend as ha_frontend  # noqa: PLC0415
    except (ImportError, ModuleNotFoundError):
        return

    for previous_url in previous_urls:
        if previous_url == metadata_url or not isinstance(previous_url, str):
            continue
        with suppress(KeyError):
            ha_frontend.remove_extra_js_url(hass, previous_url)
    try:
        ha_frontend.add_extra_js_url(hass, metadata_url)
    except KeyError:
        # The frontend dependency owns this manager. If HA is still starting it,
        # the Lovelace resource registration below remains the fallback path.
        return


async def _async_ensure_lovelace_resource(
    hass: HomeAssistant,
    module_url: str,
) -> None:
    """Register the bundled card as a Lovelace module resource."""

    try:
        from homeassistant.components.lovelace.const import (
            LOVELACE_DATA,  # noqa: PLC0415
        )
        from homeassistant.helpers import collection  # noqa: PLC0415
    except (ImportError, ModuleNotFoundError):
        return

    lovelace_data = hass.data.get(LOVELACE_DATA)
    resources = getattr(lovelace_data, "resources", None)
    if resources is None or not hasattr(resources, "async_items"):
        return

    async_get_info = getattr(resources, "async_get_info", None)
    if async_get_info is not None:
        with suppress(Exception):
            await async_get_info()

    resource_url = f"{FRONTEND_URL_PATH}/{DOORBELL_CALL_CARD_FILENAME}"

    matching_items = [
        item
        for item in resources.async_items()
        if isinstance(item, dict)
        and str(item.get("url", "")).split("?", maxsplit=1)[0] == resource_url
    ]
    if not matching_items:
        async_create_item = getattr(resources, "async_create_item", None)
        if async_create_item is not None:
            await async_create_item({"url": module_url, "res_type": "module"})
        return

    keeper = matching_items[0]
    keeper_id = keeper.get("id")
    async_update_item = getattr(resources, "async_update_item", None)
    if (
        isinstance(keeper_id, str)
        and async_update_item is not None
        and (keeper.get("url") != module_url or keeper.get("type") != "module")
    ):
        await async_update_item(keeper_id, {"url": module_url, "res_type": "module"})

    async_delete_item = getattr(resources, "async_delete_item", None)
    if async_delete_item is None:
        return
    for duplicate in matching_items[1:]:
        duplicate_id = duplicate.get("id")
        if isinstance(duplicate_id, str):
            with suppress(collection.ItemNotFound):
                await async_delete_item(duplicate_id)


async def _async_frontend_asset_version(
    hass: HomeAssistant,
    filename: str = DOORBELL_CALL_CARD_FILENAME,
) -> str:
    """Return the frontend asset hash without blocking the event loop."""

    return await hass.async_add_executor_job(_frontend_asset_version, filename)


def _frontend_asset_version(filename: str = DOORBELL_CALL_CARD_FILENAME) -> str:
    """Return a cache-busting version for the bundled frontend module."""

    try:
        return sha256((FRONTEND_DIR / filename).read_bytes()).hexdigest()[:16]
    except OSError:
        return "0"
