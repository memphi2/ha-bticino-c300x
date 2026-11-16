"""Bounded HA-only visit metadata; never acquire media or command the device."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections.abc import Mapping
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.storage import Store

from .config_snapshots import snapshot_options
from .const import DOMAIN, EVENT_AGENT_EVENT_RECEIVED
from .event_payload import agent_event_key

MAX_VISITS = 1000
MAX_JOURNAL_BYTES = 1024 * 1024
MAX_ACTIVE_SECONDS = 120
EVENT_JOURNAL_CHANGED = f"{DOMAIN}_visitor_journal_changed"
_ID = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_IMAGE = re.compile(r"c300x-[0-9]{13}-[0-9a-f]{32}\.jpg\Z", re.ASCII)
_LOGGER = logging.getLogger(__name__)


def visit_id(data: Mapping[str, Any]) -> str | None:
    """Use the native instance/sequence identity, not arrival-time proximity."""
    value = data.get("source_event_id")
    if (not isinstance(value, str) or not 1 <= len(value) <= 128
            or not value.isascii() or not value.isprintable()):
        return None
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def get_journal(hass: Any, entry_id: str) -> VisitorJournal | None:
    manager = getattr(hass, "data", {}).get(DOMAIN, {}).get("stream_snapshots", {}).get(entry_id)
    return getattr(manager, "journal", None)


async def async_remove_journal(hass: Any, entry_id: str) -> None:
    """Remove only journal metadata, never somebody else's media artifacts."""
    journal = get_journal(hass, entry_id)
    if journal is not None:
        await journal.shutdown()
        journal.removed = True
        await journal.store.async_remove()
    else:
        await Store(hass, 1, f"{DOMAIN}.visitor_journal.{entry_id}").async_remove()


class VisitorJournal:
    """One metadata store per entry, with the snapshot manager's lifecycle/TTL."""

    def __init__(self, hass: Any, entry: Any) -> None:
        self.hass = hass
        self.entry = entry
        self.store = Store[dict[str, Any]](
            hass, 1, f"{DOMAIN}.visitor_journal.{entry.entry_id}",
            private=True, atomic_writes=True,
        )
        self.records: dict[str, dict[str, Any]] = {}
        self._active: str | None = None
        self._active_until = 0.0
        self.latest_source: str | None = None
        self.closed = False
        self.removed = False
        self._unsubscribe: Any = None

    @property
    def active(self) -> str | None:
        # A lost close event must not associate a later operation indefinitely.
        # Expiry removes correlation only; it never declares the call missed.
        if time.monotonic() >= self._active_until:
            self._active = None
        return self._active

    @active.setter
    def active(self, value: str | None) -> None:
        self._active = value
        self._active_until = time.monotonic() + MAX_ACTIVE_SECONDS if value else 0.0

    async def load(self) -> None:
        data = await self.store.async_load()
        if isinstance(data, dict) and isinstance(data.get("visits"), list):
            for raw in data["visits"][-MAX_VISITS:]:
                item = _validated_record(raw)
                if item is not None:
                    self.records[item["id"]] = item
        self.prune()

    def start(self) -> None:
        self._unsubscribe = self.hass.bus.async_listen(EVENT_AGENT_EVENT_RECEIVED, self.event)

    @callback
    def event(self, event: Any) -> None:
        data = event.data
        if self.closed or data.get("entry_id") != self.entry.entry_id:
            return
        kind = agent_event_key(data)
        active = self.active
        if kind == "doorbell_pressed":
            key = visit_id(data)
            if key is None:
                # Old/unidentified events must not attach media to a prior ring.
                self.active = None
                return
            if key in self.records:
                return
            source = data["source_event_id"]
            order = _source_order(source, self.latest_source)
            if order is not None and order <= 0:
                return
            self.latest_source = source
            self.prune()
            self.active = key
            self.records[key] = {
                "id": key, "at": time.time(), "source": source, "outcome": "unknown",
                "snapshot": None, "clip": None,
            }
            self.prune()
            self.changed()
        elif kind in {"doorbell_media_closed", "agent_restarted", "home_call_started", "call_ended"}:
            order = _source_order(data.get("source_event_id"), self.latest_source)
            if order is not None and order <= 0:
                return
            self.active = None
        elif kind == "doorbell_view_requested" and active is not None and active in self.records:
            payload = data.get("data")
            video = payload.get("video") if isinstance(payload, Mapping) else None
            bridge = video.get("bridge") if isinstance(video, Mapping) else None
            # A request/preview, browser state, or lack of an answer is not an outcome.
            if (isinstance(bridge, Mapping) and bridge.get("media_owner") == "ring"
                    and bridge.get("ring_answered") is True
                    and not video.get("external_media_active")
                    and (_source_order(data.get("source_event_id"), self.latest_source) or 0) > 0):
                item = self.records[active]
                if item["outcome"] != "answered":
                    item["outcome"] = "answered"
                    self.changed()

    def attach_snapshot(self, key: str | None, name: str) -> None:
        if not self.closed and key is not None and key == self.active and key in self.records and _IMAGE.fullmatch(name):
            self.records[key]["snapshot"] = name
            self.changed()

    async def attach_clip(self, key: str | None, metadata: Mapping[str, Any]) -> None:
        """Link only a completed default-path capture, never a mutable latest alias."""
        if self.closed or key is None or key != self.active or key not in self.records:
            return
        if metadata.get("entry_id") != self.entry.entry_id or metadata.get("capture_mode") != "ring":
            return
        from .visitor_journal_media import describe_clip

        try:
            clip = await self.hass.async_add_executor_job(describe_clip, self.hass, metadata)
        except (KeyError, OSError, TypeError, ValueError):
            return
        if clip and not self.closed and key == self.active and key in self.records:
            self.records[key]["clip"] = clip
            self.changed()

    def prune(self) -> None:
        cutoff = time.time() - snapshot_options(self.entry).retention_days * 86400
        kept = sorted(
            (item for item in self.records.values() if cutoff < item["at"] <= time.time()),
            key=lambda item: (item["at"], item["id"]),
        )[-MAX_VISITS:]
        records = {item["id"]: item for item in kept}
        while len(json.dumps({"visits": list(records.values())})) > MAX_JOURNAL_BYTES:
            records.pop(next(iter(records)))
        if records != self.records:
            self.records = records
            if self.active not in records:
                self.active = None
            self.changed()

    def items(self) -> list[dict[str, Any]]:
        self.prune()
        return sorted(self.records.values(), key=lambda item: (item["at"], item["id"]), reverse=True)

    def changed(self) -> None:
        if not self.closed:
            self.store.async_delay_save(self._payload, 1)
            # Only invalidation crosses the event bus, never visitor/media data.
            self.hass.bus.async_fire(EVENT_JOURNAL_CHANGED, {"entry_id": self.entry.entry_id})

    def _payload(self) -> dict[str, Any]:
        return {"visits": list(self.records.values())}

    def close(self) -> None:
        self.closed = True
        self.active = None
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    async def shutdown(self) -> None:
        self.close()
        if self.removed:
            return
        try:
            await self.store.async_save(self._payload())
        except OSError:
            _LOGGER.warning("Could not persist C300X visitor journal", exc_info=True)


def _validated_record(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not _ID.fullmatch(raw["id"]):
        return None
    at = raw.get("at")
    if type(at) not in (int, float) or not 0 < at <= time.time():
        return None
    source = raw.get("source")
    if visit_id({"source_event_id": source}) != raw["id"]:
        return None
    from .visitor_journal_media import valid_clip

    image = raw.get("snapshot")
    return {
        "id": raw["id"], "at": at, "source": source,
        "outcome": "answered" if raw.get("outcome") == "answered" else "unknown",
        "snapshot": image if isinstance(image, str) and _IMAGE.fullmatch(image) else None,
        "clip": valid_clip(raw.get("clip")),
    }


def _source_order(value: Any, previous: Any) -> int | None:
    """Compare native event sequence only within the same agent instance."""
    if not isinstance(value, str) or not isinstance(previous, str):
        return None
    prefix, _, sequence = value.rpartition("-")
    old_prefix, _, old_sequence = previous.rpartition("-")
    if (not prefix.startswith("native-") or prefix != old_prefix
            or not sequence.isascii() or not old_sequence.isascii()
            or not sequence.isdigit() or not old_sequence.isdigit()
            or len(sequence) > 20 or len(old_sequence) > 20):
        return None
    return int(sequence) - int(old_sequence)
