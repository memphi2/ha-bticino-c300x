"""Frontend assets for the BTicino C300X integration."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

FRONTEND_DIR = Path(__file__).with_name("frontend")
FRONTEND_URL_PATH = f"/{DOMAIN}/frontend"
DOORBELL_CALL_CARD_FILENAME = "c300x-doorbell-call-card.js"
DATA_FRONTEND_MODULE_URL = "frontend_module_url"


async def async_setup_frontend(hass: HomeAssistant) -> None:
    """Register the bundled Lovelace card frontend module."""

    domain_data: dict[str, Any] = hass.data.setdefault(DOMAIN, {})
    module_url = (
        f"{FRONTEND_URL_PATH}/{DOORBELL_CALL_CARD_FILENAME}"
        f"?v={_frontend_asset_version()}"
    )
    if domain_data.get(DATA_FRONTEND_MODULE_URL) != module_url:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(FRONTEND_URL_PATH, str(FRONTEND_DIR), True)]
        )
        domain_data[DATA_FRONTEND_MODULE_URL] = module_url
    await _async_ensure_lovelace_resource(hass, module_url)


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


def _frontend_asset_version() -> int:
    """Return a cache-busting version for the bundled frontend module."""

    try:
        return (FRONTEND_DIR / DOORBELL_CALL_CARD_FILENAME).stat().st_mtime_ns
    except OSError:
        return 0
