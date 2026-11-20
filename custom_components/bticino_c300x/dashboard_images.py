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
import time
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
# A full tile spans the page: 800 px less the 36 px margins. Two half tiles
# share it with the 10 px gap of the tile grid between them.
IMAGE_TILE_WIDTH = 728
IMAGE_TILE_HALF_WIDTH = 359
IMAGE_TILE_HEIGHT = 200
IMAGE_TILE_HEIGHTS = {"half": 120, "full": 290}
_ALLOWED_HEIGHTS = frozenset((IMAGE_TILE_HEIGHT, *IMAGE_TILE_HEIGHTS.values()))
_ALLOWED_WIDTHS = frozenset((IMAGE_TILE_WIDTH, IMAGE_TILE_HALF_WIDTH))
_SOURCE_LIMIT_BYTES = 16 * 1024 * 1024
# Decoding costs memory by pixel count, not by file size: a small file can
# hold a picture far larger than any camera frame.
_SOURCE_LIMIT_PIXELS = 12_000_000
_SOURCE_FORMATS = ("JPEG", "PNG", "GIF", "WEBP", "BMP")
_FETCH_TIMEOUT = 10
_JPEG_QUALITY = 80
# Two pictures at a time: scaling runs in the executor and a camera read can
# take seconds; a display page holds a handful of tiles at most.
_SLOTS = asyncio.Semaphore(2)
# A scaled picture is kept this long, so repeated requests for one address
# read the camera once.
_CACHE_SECONDS = 5.0
_CACHE_ENTRIES = 16
_CACHE_KEY = f"{DOMAIN}_tile_images"


class TileImageUnavailable(Exception):
    """The entity has no picture to show right now."""


def image_tile_base_url(callback_url: str) -> str:
    """Return scheme and host of the address the display can load pictures from.

    Only plain HTTP: the Qt of the device is built without SSL, so its display
    cannot open an https address. (The agent can, but pictures do not pass
    through it.) With an https callback there are no picture tiles.
    """

    parts = urlsplit(str(callback_url or ""))
    if parts.scheme != "http" or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}"


def image_tile_width(layout: dict[str, Any]) -> int:
    return IMAGE_TILE_HALF_WIDTH if layout.get("width") == "half" else IMAGE_TILE_WIDTH


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
    if state.state == "unavailable":
        return "1"
    if entity_id.startswith("camera."):
        value = str(state.attributes.get("access_token") or state.state)
    else:
        value = str(state.state)
    return hashlib.sha256(value.encode()).hexdigest()[:10]


def _signature(entry: Any, entity_id: str, width: int, height: int, revision: str) -> str:
    secret = str(entry.data.get(CONF_SHARED_SECRET) or "")
    if not secret:
        return ""
    message = f"tile-image\n{entry.entry_id}\n{entity_id}\n{width}\n{height}\n{revision}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()[:32]


def image_tile_source(entry: Any, entity_id: str, state: Any, layout: dict[str, Any]) -> dict[str, Any] | None:
    """Return address and size of the picture tile, or None when it cannot be served."""

    # An entity that is gone or unavailable has no picture. The display does
    # not retry a failed load, so the tile is left out until the entity is back.
    if state is None or state.state == "unavailable":
        return None
    base = str(getattr(getattr(entry, "runtime_data", None), "display_image_base_url", "") or "")
    width = image_tile_width(layout)
    height = image_tile_height(layout)
    revision = image_tile_revision(entity_id, state)
    signature = _signature(entry, entity_id, width, height, revision)
    if not base or not signature:
        return None
    return {
        "source": (
            f"{base}/api/{DOMAIN}/tile_image/{quote(entry.entry_id, safe='')}/{entity_id}"
            f"?w={width}&h={height}&rev={revision}&sig={signature}"
        ),
        "width": width,
        "height": height,
    }


def scaled_jpeg(content: bytes, width: int, height: int) -> bytes:
    """Scale a picture down to fit the tile and return it as JPEG. Never scales up."""

    from PIL import Image, ImageOps

    try:
        with Image.open(io.BytesIO(content), formats=_SOURCE_FORMATS) as image:
            if image.width * image.height > _SOURCE_LIMIT_PIXELS:
                raise ValueError("picture has too many pixels")
            image.draft("RGB", (width, height))
            # Shrink first, inside a square that still covers the tile after a
            # rotation: turning and converting then copy a small picture.
            # Palette and 1-bit pictures are converted first: shrinking them
            # as they are drops pixels instead of averaging them.
            if image.mode in ("P", "1"):
                image = image.convert("RGB")
            side = max(width, height)
            image.thumbnail((side, side))
            picture = ImageOps.exif_transpose(image).convert("RGB")
        picture.thumbnail((width, height))
        buffer = io.BytesIO()
        picture.save(buffer, "JPEG", quality=_JPEG_QUALITY)
    except Exception as err:  # noqa: BLE001 - decoders raise many types on damaged files
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
    except TileImageUnavailable:
        raise
    except (HomeAssistantError, TimeoutError, OSError) as err:
        raise TileImageUnavailable(entity_id) from err
    except Exception as err:  # noqa: BLE001 - any camera integration may raise anything
        raise TileImageUnavailable(entity_id) from err
    if not content:
        raise TileImageUnavailable(entity_id)
    return bytes(content)


class C300XTileImageView(HomeAssistantView):
    """Scaled pictures of camera and image entities for the display's picture tiles."""

    url = f"/api/{DOMAIN}/tile_image/{{entry_id}}/{{entity_id}}"
    name = f"api:{DOMAIN}:tile_image"
    requires_auth = False

    @staticmethod
    async def _async_picture(hass: Any, entity_id: str, width: int, height: int) -> bytes:
        async with _SLOTS:
            try:
                content = await _async_source_image(hass, entity_id, width, height)
                if len(content) > _SOURCE_LIMIT_BYTES:
                    raise ValueError("picture too large")
                return bytes(await hass.async_add_executor_job(scaled_jpeg, content, width, height))
            except (TileImageUnavailable, ValueError) as err:
                raise web.HTTPServiceUnavailable() from err

    async def get(self, request: web.Request, entry_id: str, entity_id: str) -> web.Response:
        from homeassistant.config_entries import ConfigEntryState

        from .capabilities import entry_device_ui_enabled_or_patch_active
        from .dashboard_config import configured_dashboard_entities

        hass = request.app["hass"]
        entry = hass.config_entries.async_get_entry(entry_id)
        try:
            width = int(request.query.get("w", ""))
            height = int(request.query.get("h", ""))
        except ValueError:
            raise web.HTTPNotFound() from None
        supplied = str(request.query.get("sig", ""))
        # One answer for every refusal: the address either works or does not exist.
        if (
            entry is None
            or entry.domain != DOMAIN
            or entry.state is not ConfigEntryState.LOADED
            or not entry_device_ui_enabled_or_patch_active(entry)
            or width not in _ALLOWED_WIDTHS
            or height not in _ALLOWED_HEIGHTS
            or entity_id.split(".", 1)[0] not in IMAGE_TILE_DOMAINS
            or entity_id not in configured_dashboard_entities(entry)
        ):
            raise web.HTTPNotFound()
        revision = str(request.query.get("rev", ""))
        expected = _signature(entry, entity_id, width, height, revision) if revision.isascii() else ""
        if not expected or not hmac.compare_digest(expected.encode(), supplied.encode()):
            raise web.HTTPNotFound()
        store = hass.data.setdefault(_CACHE_KEY, {"pictures": {}, "locks": {}})
        cache, locks = store["pictures"], store["locks"]
        key = (entry_id, entity_id, width, height, revision)
        # One lock per address: requests that arrive together wait for the
        # first one and take its picture instead of reading the camera again.
        lock = locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                cached = cache.get(key)
                if cached is not None and time.monotonic() - cached[0] < _CACHE_SECONDS:
                    body = cached[1]
                else:
                    # A failed read is kept as well, so the requests waiting
                    # behind it do not each try the camera again.
                    try:
                        body = await self._async_picture(hass, entity_id, width, height)
                    except web.HTTPServiceUnavailable:
                        body = None
                    now = time.monotonic()
                    for old in [k for k, value in cache.items() if now - value[0] >= _CACHE_SECONDS]:
                        del cache[old]
                    if len(cache) >= _CACHE_ENTRIES:
                        cache.clear()
                    cache[key] = (now, body)
        finally:
            # The picture or the failure is in the cache by now, so a request
            # that still waits on this lock finds it without reading again.
            if not lock.locked() and locks.get(key) is lock:
                del locks[key]
        if body is None:
            raise web.HTTPServiceUnavailable()
        return web.Response(body=body, content_type="image/jpeg", headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        })
