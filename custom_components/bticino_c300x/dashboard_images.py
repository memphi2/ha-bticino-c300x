"""Camera and image entities as picture tiles on the display.

The display draws a picture tile from an address it loads itself. For a
camera or image entity that address is a view of this integration: it reads
the entity's current picture and scales it down to the tile before it is
sent, so the display never receives or decodes a full camera frame.

The view needs no login, because the display has none. Its address carries a
signature made with the entry's shared secret, and only entities that are on
the display pages are served.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlsplit

from aiohttp import web

from .const import CONF_SHARED_SECRET, DOMAIN

if TYPE_CHECKING:
    class HomeAssistantView:
        """Typing stand-in for Home Assistant's HTTP view."""

        url: str
        name: str
        requires_auth: bool
else:
    from homeassistant.components.http import HomeAssistantView

IMAGE_TILE_DOMAINS = ("camera", "image")
# The tile spans the page: 800 px less the 36 px margins.
IMAGE_TILE_WIDTH = 728
IMAGE_TILE_HEIGHT = 200
IMAGE_TILE_HEIGHTS = {"half": 120, "full": 290}
_ALLOWED_HEIGHTS = frozenset((IMAGE_TILE_HEIGHT, *IMAGE_TILE_HEIGHTS.values()))
_SOURCE_LIMIT_BYTES = 16 * 1024 * 1024
_FETCH_TIMEOUT = 10
_JPEG_QUALITY = 80
# Two pictures at a time: scaling runs in the executor and a camera read can
# take seconds; a display page holds a handful of tiles at most.
_SLOTS = asyncio.Semaphore(2)


class TileImageUnavailable(Exception):
    """The entity has no picture to show right now."""


def image_tile_base_url(callback_url: str) -> str:
    """Return scheme and host of the address the device reaches Home Assistant at."""

    parts = urlsplit(str(callback_url or ""))
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}"


def image_tile_height(layout: dict[str, Any]) -> int:
    return IMAGE_TILE_HEIGHTS.get(str(layout.get("height", "")), IMAGE_TILE_HEIGHT)


def image_tile_revision(entity_id: str, state: Any) -> str:
    """Return a short value that changes when the entity has a new picture.

    An image entity's state is the time of its last picture. A camera has no
    such state; its access token is renewed every few minutes, which makes the
    display fetch a fresh picture at that pace without any timer of its own.
    The token itself never leaves Home Assistant, only a digest of it.
    """

    if state is None:
        return "0"
    if entity_id.startswith("camera."):
        value = str(state.attributes.get("access_token") or state.state)
    else:
        value = str(state.state)
    return hashlib.sha256(value.encode()).hexdigest()[:10]


def _signature(entry: Any, entity_id: str, height: int) -> str:
    secret = str(entry.data.get(CONF_SHARED_SECRET) or "")
    if not secret:
        return ""
    message = f"tile-image\n{entry.entry_id}\n{entity_id}\n{height}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()[:32]


def image_tile_source(entry: Any, entity_id: str, state: Any, layout: dict[str, Any]) -> dict[str, Any] | None:
    """Return address and size of the picture tile, or None when it cannot be served."""

    base = str(getattr(getattr(entry, "runtime_data", None), "display_image_base_url", "") or "")
    height = image_tile_height(layout)
    signature = _signature(entry, entity_id, height)
    if not base or not signature:
        return None
    return {
        "source": (
            f"{base}/api/{DOMAIN}/tile_image/{quote(entry.entry_id, safe='')}/{entity_id}"
            f"?h={height}&rev={image_tile_revision(entity_id, state)}&sig={signature}"
        ),
        "width": IMAGE_TILE_WIDTH,
        "height": height,
    }


def scaled_jpeg(content: bytes, width: int, height: int) -> bytes:
    """Scale a picture down to fit the tile and return it as JPEG. Never scales up."""

    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(content)) as image:
            image.draft("RGB", (width, height))
            picture = image.convert("RGB")
        picture.thumbnail((width, height))
        buffer = io.BytesIO()
        picture.save(buffer, "JPEG", quality=_JPEG_QUALITY)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as err:
        raise ValueError("not a usable picture") from err
    return buffer.getvalue()


async def _async_source_image(hass: Any, entity_id: str, width: int, height: int) -> bytes:
    """Read the entity's current picture from Home Assistant."""

    from homeassistant.exceptions import HomeAssistantError

    try:
        if entity_id.startswith("camera."):
            from homeassistant.components.camera import async_get_image

            image = await async_get_image(hass, entity_id, timeout=_FETCH_TIMEOUT, width=width, height=height)
            return bytes(image.content)
        component = hass.data.get("image")
        entity = component.get_entity(entity_id) if component is not None else None
        if entity is None:
            raise TileImageUnavailable(entity_id)
        async with asyncio.timeout(_FETCH_TIMEOUT):
            content = await entity.async_image()
    except (HomeAssistantError, TimeoutError, OSError) as err:
        raise TileImageUnavailable(entity_id) from err
    if not content:
        raise TileImageUnavailable(entity_id)
    return bytes(content)


class C300XTileImageView(HomeAssistantView):
    """Scaled pictures of camera and image entities for the display's picture tiles."""

    url = f"/api/{DOMAIN}/tile_image/{{entry_id}}/{{entity_id}}"
    name = f"api:{DOMAIN}:tile_image"
    requires_auth = False

    async def get(self, request: web.Request, entry_id: str, entity_id: str) -> web.Response:
        from .dashboard_config import configured_dashboard_entities

        hass = request.app["hass"]
        entry = hass.config_entries.async_get_entry(entry_id)
        try:
            height = int(request.query.get("h", ""))
        except ValueError:
            raise web.HTTPNotFound() from None
        supplied = str(request.query.get("sig", ""))
        # One answer for every refusal: the address either works or does not exist.
        if (
            entry is None
            or getattr(entry, "domain", DOMAIN) != DOMAIN
            or height not in _ALLOWED_HEIGHTS
            or entity_id.split(".", 1)[0] not in IMAGE_TILE_DOMAINS
            or entity_id not in configured_dashboard_entities(entry)
        ):
            raise web.HTTPNotFound()
        expected = _signature(entry, entity_id, height)
        if not expected or not hmac.compare_digest(expected, supplied):
            raise web.HTTPNotFound()
        async with _SLOTS:
            try:
                content = await _async_source_image(hass, entity_id, IMAGE_TILE_WIDTH, height)
                if len(content) > _SOURCE_LIMIT_BYTES:
                    raise ValueError("picture too large")
                body = await hass.async_add_executor_job(scaled_jpeg, content, IMAGE_TILE_WIDTH, height)
            except (TileImageUnavailable, ValueError) as err:
                raise web.HTTPServiceUnavailable() from err
        return web.Response(body=body, content_type="image/jpeg", headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        })
