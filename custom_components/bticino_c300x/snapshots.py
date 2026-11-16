"""Home Assistant lifecycle for retained images and event-driven acquisition."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any, cast
from urllib.parse import quote

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .config_snapshots import snapshot_options
from .const import DOMAIN
from .snapshot_capture import SnapshotCapture
from .snapshot_store import SnapshotStore, StoredSnapshot
from .visitor_journal import VisitorJournal

SIGNAL_SNAPSHOT_CHANGED = f"{DOMAIN}_snapshot_changed"
_LOGGER = logging.getLogger(__name__)


def snapshot_url(entry_id: str, name: str) -> str:
    """Return the authenticated local media endpoint."""

    return f"/api/{DOMAIN}/snapshots/{quote(entry_id, safe='')}/{quote(name, safe='')}"


class StreamSnapshots:
    """Serialize disk work and cache the latest JPEG for camera still requests."""

    def __init__(self, hass: Any, entry: Any) -> None:
        self.hass = hass
        self.entry = entry
        self.store = SnapshotStore(hass, entry.entry_id)
        self.lock = asyncio.Lock()
        self.enabled = True
        self.settings = Store[dict[str, bool]](
            hass, 1, f"{DOMAIN}.snapshots.{entry.entry_id}",
            private=True, atomic_writes=True,
        )
        self.latest: StoredSnapshot | None = None
        self.image: bytes | None = None
        self.closed = False
        self.journal: VisitorJournal | None = None
        self.capture = SnapshotCapture(self)
        self._jobs: set[asyncio.Future[Any]] = set()
        self._cancel_retention: Callable[[], None] | None = None

    def capture_requested(self, session_key: str) -> None:
        self.capture.capture_requested(session_key)

    def capture_ended(self, session_key: str) -> None:
        self.capture.capture_ended(session_key)

    async def disk_job(self, function: Any, *args: Any) -> Any:
        """Keep serialization intact until a cancelled executor job finishes."""

        if self.closed:
            raise ValueError("Snapshot manager is closed")
        return await self._finish_job(self.hass.async_add_executor_job(function, *args))

    async def _finish_job(self, work: Awaitable[Any], *, track: bool = True) -> Any:
        """Finish admitted work before cancellation can release its lock."""

        job = asyncio.ensure_future(work)
        if track:
            self._jobs.add(job)
            job.add_done_callback(self._jobs.discard)
        try:
            return await asyncio.shield(job)
        except asyncio.CancelledError:
            # Executor threads cannot be cancelled. Do not release the caller's
            # lock while that thread can still mutate the store.
            while not job.done():
                try:
                    await asyncio.shield(job)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not job.cancelled():
                job.exception()
            raise

    async def async_load_settings(self) -> None:
        """Restore entry-local state before publishing the manager or hooks."""

        async with self.lock:
            data = await self.settings.async_load()
            if data is not None:
                enabled = data.get("enabled") if isinstance(data, dict) else None
                # A corrupt saved preference must not enable capture unexpectedly.
                self.enabled = enabled if isinstance(enabled, bool) else False

    async def async_set_enabled(self, enabled: bool) -> None:
        """Persist and publish a switch update without reloading the entry."""

        if not isinstance(enabled, bool):
            raise ValueError("Snapshot enabled state must be a boolean")
        if not enabled:
            self.capture.blocked = True
            self.capture.cancel()
        try:
            async with self.lock:
                if self.closed:
                    raise ValueError("Stream images are closed")
                if enabled == self.enabled:
                    return

                async def persist() -> None:
                    await self.settings.async_save({"enabled": enabled})
                    self.enabled = enabled
                    self.notify()

                await self._finish_job(persist())
        finally:
            self.capture.blocked = self.closed or not self.enabled

    @property
    def preview(self) -> bytes | None:
        """Never return a disabled or expired image, even between cleanup ticks."""

        options = snapshot_options(self.entry)
        if (self.closed or not self.enabled or self.latest is None
                or self.latest.captured_at <= time.time() - options.retention_days * 86400):
            return None
        return self.image

    async def refresh(self, _now: Any = None) -> None:
        """Run retention even when saving and previews are switched off."""

        if self.journal is not None and not self.closed:
            self.journal.prune()
        async with self.lock:
            if self.closed:
                return
            try:
                items = await self.disk_job(
                    self.store.items, snapshot_options(self.entry).retention_days
                )
                if self.closed:
                    return
                latest = items[0] if items else None
                if latest != self.latest:
                    self.image = (
                        await self.disk_job(
                            self.store.read, latest.name, snapshot_options(self.entry).retention_days
                        ) if latest else None
                    )
                    if self.closed:
                        self.image = None
                        return
                    self.latest = latest
                    self.notify()
            except (OSError, ValueError):
                self.latest = None
                self.image = None
                _LOGGER.warning("Could not read C300X stream images", exc_info=True)

    async def save(
        self, content: bytes, session: str, *, is_current: Callable[[], bool] | None = None,
    ) -> StoredSnapshot:
        """Store one image per capture identity without device I/O."""

        async with self.lock:
            options = snapshot_options(self.entry)
            if self.closed or not self.enabled or (is_current is not None and not is_current()):
                raise ValueError("Stream images are disabled")
            def store_current() -> StoredSnapshot:
                # Executor jobs may wait behind unrelated HA work. Recheck at
                # execution time, not just when submitting the job.
                if self.closed or not self.enabled or (is_current is not None and not is_current()):
                    raise ValueError("Snapshot capture is no longer current")
                previous = (
                    {item.name for item in self.store.items(options.retention_days)}
                    if is_current is not None else set()
                )
                item = self.store.save(content, session, options.retention_days)
                if is_current is not None and not is_current():
                    # A worker already writing cannot be cancelled. Roll back
                    # only its new artifact, never a deduplicated older image.
                    if item.name not in previous:
                        (self.store.root / item.name).unlink(missing_ok=True)
                    raise ValueError("Snapshot capture became stale during storage")
                return item

            item = cast(StoredSnapshot, await self.disk_job(store_current))
            if not self.closed:
                image = await self.disk_job(
                    self.store.read, item.name, options.retention_days
                )
                if not self.closed and (is_current is None or is_current()):
                    self.latest = item
                    self.image = image
                    self.notify()
            return item

    def notify(self) -> None:
        if not self.closed:
            async_dispatcher_send(self.hass, SIGNAL_SNAPSHOT_CHANGED, self.entry.entry_id)

    def close(self) -> None:
        self.closed = True
        if self.journal is not None:
            self.journal.close()
        self.capture.close()
        self.image = None
        self.latest = None
        if self._cancel_retention is not None:
            self._cancel_retention()
            self._cancel_retention = None

    async def async_shutdown(self) -> None:
        """Drain admitted work before another manager can use this directory."""

        self.close()

        async def drain() -> None:
            jobs = list(self._jobs)
            if self.capture.task is not None:
                jobs.append(self.capture.task)
            if jobs:
                await asyncio.gather(*jobs, return_exceptions=True)
            # Wait for disk-job callers to unwind their critical sections too.
            async with self.lock:
                pass
            if self.journal is not None:
                await self.journal.shutdown()

        await self._finish_job(drain(), track=False)


def get_snapshots(hass: Any, entry_id: str) -> StreamSnapshots | None:
    return cast(
        StreamSnapshots | None,
        getattr(hass, "data", {}).get(DOMAIN, {}).get("stream_snapshots", {}).get(entry_id),
    )


async def async_setup_snapshots(hass: Any, entry: Any) -> None:
    """Own the retention timer at entry scope, independent of card connections."""

    managers = hass.data.setdefault(DOMAIN, {}).setdefault("stream_snapshots", {})
    await async_shutdown_snapshots(hass, entry.entry_id)
    manager = StreamSnapshots(hass, entry)
    await manager.async_load_settings()
    manager.journal = VisitorJournal(hass, entry)
    try:
        await manager.journal.load()
    except (HomeAssistantError, OSError, ValueError):
        _LOGGER.warning("Could not load C300X visitor journal", exc_info=True)
        manager.journal = None
    managers[entry.entry_id] = manager

    def unload() -> None:
        manager.close()

    entry.async_on_unload(unload)
    manager._cancel_retention = async_track_time_interval(hass, manager.refresh, timedelta(hours=1))
    await manager.refresh()
    if manager.journal is not None:
        manager.journal.start()
    manager.capture.start()


async def async_shutdown_snapshots(hass: Any, entry_id: str) -> None:
    """Keep the closed manager discoverable until its executor work is drained."""

    manager = get_snapshots(hass, entry_id)
    if manager is None:
        return
    try:
        await manager.async_shutdown()
    finally:
        managers = hass.data.get(DOMAIN, {}).get("stream_snapshots", {})
        if managers.get(entry_id) is manager:
            managers.pop(entry_id, None)
