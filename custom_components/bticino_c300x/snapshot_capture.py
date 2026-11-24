"""Event-driven reads of an already active doorbell framebuffer."""

from __future__ import annotations

import asyncio
import logging
from io import BytesIO
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from aiohttp import ClientConnectionError
from homeassistant.core import callback
from homeassistant.util import dt as dt_util
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from .api_errors import C300XAgentApiConnectionError, C300XAgentApiError
from .config_snapshots import snapshot_options
from .const import EVENT_AGENT_EVENT_RECEIVED
from .entity import entry_video_enabled, supports_capability
from .event_payload import agent_event_key
from .snapshot_store import MAX_SNAPSHOT_BYTES

if TYPE_CHECKING:
    from .snapshots import StreamSnapshots

_LOGGER = logging.getLogger(__name__)
# The agent returns at most the 800x480 display as a 24-bit BMP.
MAX_FRAMEBUFFER_PIXELS = 800 * 480
MAX_FRAMEBUFFER_BYTES = 54 + MAX_FRAMEBUFFER_PIXELS * 3
CAPTURE_TIMEOUT = 12
RETRY_DELAY = 1
MAX_ATTEMPTS = 3


def _draw_stamp(image: Image.Image, text: str) -> None:
    """Write the capture time into the lower right corner, readable on any picture."""

    draw = ImageDraw.Draw(image)
    size = max(10, image.height // 24)
    font: Any
    try:
        font = ImageFont.load_default(size)
    except (OSError, TypeError, ValueError):
        # Pillow without FreeType only has its small built-in bitmap font.
        font = ImageFont.load_default()
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    margin = max(2, size // 3)
    position = (
        max(0, image.width - right - margin),
        max(0, image.height - bottom - margin),
    )
    draw.text(
        position, text, font=font, fill=(255, 255, 255),
        stroke_width=max(1, size // 12), stroke_fill=(0, 0, 0),
    )


def framebuffer_jpeg(content: bytes, content_type: str, stamp: str | None = None) -> bytes:
    """Validate a bounded BMP and encode a metadata-free JPEG on the executor.

    The agent already delivered the configured size; the pixels are not rescaled.
    ``stamp`` is the capture time to write into the image, if that is switched on.
    """

    if (content_type.partition(";")[0].strip().lower() != "image/bmp"
            or not content or len(content) > MAX_FRAMEBUFFER_BYTES):
        raise ValueError("Expected a bounded BMP framebuffer")
    try:
        with Image.open(BytesIO(content)) as image:
            if image.format != "BMP" or image.width * image.height > MAX_FRAMEBUFFER_PIXELS:
                raise ValueError("Invalid framebuffer dimensions or format")
            image.load()
            rgb = image.convert("RGB")
            rgb.info.clear()
            if stamp:
                _draw_stamp(rgb, stamp)
            output = BytesIO()
            rgb.save(output, format="JPEG", quality=85)
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as err:
        raise ValueError("Invalid framebuffer") from err
    result = output.getvalue()
    if len(result) > MAX_SNAPSHOT_BYTES:
        raise ValueError("Converted framebuffer exceeds image limit")
    return result


class SnapshotCapture:
    """One delayed acquisition per physical ring/view/stream cycle, no polling."""

    def __init__(self, manager: StreamSnapshots) -> None:
        self.manager = manager
        self.blocked = False
        self.generation = 0
        self.task: asyncio.Task[None] | None = None
        self.pending: tuple[int, str] | None = None
        self.identity: str | None = None
        self.stream_key: str | None = None
        self.ring_seen = False
        self.last_ring: str | None = None
        self.visitor_id: str | None = None
        self.unsubscribe: Any = None
        # Why the last visitor image could not be taken; None after a success.
        self.last_failure: str | None = None
        self.warned: set[str] = set()

    def start(self) -> None:
        """Subscribe only after persisted settings and preview have loaded."""

        if not self._supported() or self.unsubscribe is not None:
            return
        bus = getattr(self.manager.hass, "bus", None)
        if bus is not None:
            self.unsubscribe = bus.async_listen(EVENT_AGENT_EVENT_RECEIVED, self._event)

    @callback
    def _event(self, event: Any) -> None:
        if event.data.get("entry_id") != self.manager.entry.entry_id:
            return
        key = agent_event_key(event.data)
        if key in {"doorbell_media_closed", "agent_restarted"}:
            self.cancel()
        elif key == "doorbell_pressed":
            stamp = event.data.get("source_event_id") or event.data.get("event_at")
            if stamp and stamp == self.last_ring:
                return
            self.last_ring = stamp
            if self.identity is not None and self.ring_seen:
                self.cancel()
            from .visitor_journal import visit_id

            visitor = visit_id(event.data)
            if self.identity is not None and self.visitor_id is None:
                # An image already requested for an open stream belongs to this ring.
                self.visitor_id = visitor
            self._request(visitor)
            self.ring_seen = True
        elif key == "doorbell_view_requested":
            self._request()

    @callback
    def capture_requested(self, session_key: str) -> None:
        """Join a ring cycle or request one image for an actual HA stream start."""

        if not session_key:
            return
        self._request()
        if self.identity is not None:
            self.stream_key = session_key

    @callback
    def capture_ended(self, session_key: str) -> None:
        """Ignore stale stream-close notifications for an older session."""

        if session_key == self.stream_key:
            self.cancel()

    def _request(self, visitor_id: str | None = None) -> None:
        if (self.blocked or self.manager.closed or not self.manager.enabled
                or not self._supported() or self.identity is not None):
            return
        self.identity = uuid4().hex
        self.visitor_id = visitor_id
        self.generation += 1
        if self.task is not None and not self.task.done():
            # Keep only the newest request while cancelled executor work drains.
            self.pending = (self.generation, self.identity)
        else:
            self._launch(self.generation, self.identity)

    def _launch(self, generation: int, identity: str) -> None:
        self.task = asyncio.create_task(self._capture(generation, identity))
        self.task.add_done_callback(self._completed)

    def _completed(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            _LOGGER.error("Unexpected snapshot acquisition failure: %s", error)
        if self.task is not task:
            return
        self.task = None
        pending, self.pending = self.pending, None
        if pending is not None and self._current(pending[0]):
            self._launch(*pending)

    def cancel(self) -> None:
        self.generation += 1
        self.identity = None
        self.stream_key = None
        self.ring_seen = False
        self.pending = None
        if self.task is not None and not self.task.done():
            self.task.cancel()

    def close(self) -> None:
        self.blocked = True
        self.cancel()
        if self.unsubscribe is not None:
            self.unsubscribe()
            self.unsubscribe = None

    def _current(self, generation: int) -> bool:
        return (generation == self.generation and not self.blocked
                and not self.manager.closed and self.manager.enabled and self._supported())

    def _supported(self) -> bool:
        entry = self.manager.entry
        return entry_video_enabled(entry) and supports_capability(entry, "doorbell_video")

    async def _capture(self, generation: int, identity: str) -> None:
        try:
            options = snapshot_options(self.manager.entry)
            await asyncio.sleep(options.delay_seconds)
            # The configurable settling delay is separate from the bounded
            # acquisition budget (including retries, conversion and save).
            async with asyncio.timeout(CAPTURE_TIMEOUT):
                for attempt in range(MAX_ATTEMPTS):
                    if not self._current(generation):
                        return
                    try:
                        content, content_type = await self.manager.entry.runtime_data.api.async_doorbell_snapshot(*options.size)
                        break
                    except (C300XAgentApiError, ClientConnectionError, OSError, TimeoutError) as err:
                        retry = isinstance(err, (C300XAgentApiConnectionError, ClientConnectionError, OSError, TimeoutError))
                        retry = retry or getattr(err, "status", None) in (409, 503)
                        if not retry or attempt == MAX_ATTEMPTS - 1:
                            raise
                        # Three attempts at t=0,1,2 allow the native two-second
                        # throttle to clear without an unbounded retry loop.
                        await asyncio.sleep(RETRY_DELAY)
                if not self._current(generation):
                    return
                stamp = (
                    dt_util.now().strftime("%Y-%m-%d %H:%M:%S")
                    if options.timestamp else None
                )
                image = await self.manager.disk_job(framebuffer_jpeg, content, content_type, stamp)
                if self._current(generation):
                    self._failed(None)
                    item = await self.manager.save(image, identity, is_current=lambda: self._current(generation))
                    if self._current(generation) and self.manager.journal is not None:
                        # Read now: a ring during the settling delay adopts this image.
                        await self.manager.journal.attach_snapshot(self.visitor_id, item.name, image)
        except asyncio.CancelledError:
            raise
        except (C300XAgentApiError, ClientConnectionError, OSError, TimeoutError, ValueError) as err:
            # Failed reads must never replace a previously useful preview.
            _LOGGER.debug("Could not acquire C300X framebuffer snapshot", exc_info=True)
            self._failed(snapshot_failure_cause(err))

    def _failed(self, cause: str | None) -> None:
        """Record the outcome; warn once per cause until an image succeeds again."""

        if cause is None:
            self.warned.clear()
        elif cause not in self.warned:
            self.warned.add(cause)
            _LOGGER.warning(
                "C300X visitor image could not be taken (%s); the last image is kept",
                cause,
            )
        if cause != self.last_failure:
            self.last_failure = cause
            self.manager.notify()


def snapshot_failure_cause(err: BaseException) -> str:
    """Name why a visitor image failed, from the agent's answer where it gives one."""

    text = str(err)
    for code in ("snapshot_unavailable", "snapshot_throttled", "invalid_snapshot_size"):
        if code in text:
            return code
    if isinstance(err, ValueError):
        return "invalid_image"
    if isinstance(err, (C300XAgentApiConnectionError, ClientConnectionError, OSError, TimeoutError)):
        return "agent_unreachable"
    return "agent_error"
