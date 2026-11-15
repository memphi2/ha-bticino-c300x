"""HA-only calendar reads with bounded per-entry cache and unload cleanup."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, cast

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .dashboard_optional_config import configured_agenda_page
from .dashboard_optional_labels import optional_labels

CACHE_SECONDS = 300
FETCH_TIMEOUT = 12
MAX_PROVIDER_EVENTS = 4096
EVENT_BATCH_SIZE = 64
_DATA_KEY = "bticino_c300x_agenda"


@dataclass
class AgendaCache:
    """One bounded cache and one cancellable background read per loaded entry."""

    task: asyncio.Task[None] | None = None
    notify: Callable[[], None] | None = None
    calendars: tuple[str, ...] = ()
    events: list[dict[str, Any]] = field(default_factory=list)
    expires: datetime | None = None
    failed: bool = False
    closed: bool = False
    revision: int = 0


def _cache(hass: Any, entry: Any) -> AgendaCache:
    caches = hass.data.setdefault(_DATA_KEY, {})
    if entry.entry_id not in caches:
        cache = caches[entry.entry_id] = AgendaCache()

        @callback
        def unload() -> None:
            _close_cache(hass, entry, cache)

        entry.async_on_unload(unload)
    return cast(AgendaCache, caches[entry.entry_id])


def _close_cache(hass: Any, entry: Any, cache: AgendaCache) -> None:
    if cache.closed:
        return
    cache.closed = True
    cache.notify = None
    cache.events.clear()
    if cache.task is not None:
        cache.task.cancel()
    caches = hass.data.get(_DATA_KEY, {})
    if caches.get(entry.entry_id) is cache:
        caches.pop(entry.entry_id)
        if not caches:
            hass.data.pop(_DATA_KEY, None)


def _entry_active(entry: Any) -> bool:
    return getattr(entry, "state", None) in (None, ConfigEntryState.LOADED, ConfigEntryState.SETUP_IN_PROGRESS)


@callback
def async_setup_agenda_updates(hass: Any, entry: Any, request_update: Callable[[], None]) -> Callable[[], None] | None:
    """Invalidate on HA calendar changes/time; use the existing display push path."""
    settings = configured_agenda_page(entry)
    if not _entry_active(entry) or not settings["enabled"] or not settings["calendars"]:
        return None
    cache = _cache(hass, entry)
    cache.notify = request_update
    stopped = False

    @callback
    def changed(_event: Any) -> None:
        if stopped or cache.closed:
            return
        cache.revision += 1
        cache.expires = None
        _start_refresh(hass, entry, cache, tuple(settings["calendars"]))

    unsubscribers = [
        async_track_state_change_event(hass, settings["calendars"], changed),
        async_track_time_interval(hass, changed, timedelta(seconds=CACHE_SECONDS)),
    ]

    @callback
    def stop() -> None:
        nonlocal stopped
        stopped = True
        for unsubscribe in unsubscribers:
            unsubscribe()
        unsubscribers.clear()
        _close_cache(hass, entry, cache)

    entry.async_on_unload(stop)
    return stop


def _start_refresh(hass: Any, entry: Any, cache: AgendaCache, calendars: tuple[str, ...]) -> None:
    if cache.closed or cache.task is not None:
        return
    cache.task = entry.async_create_background_task(
        hass, _async_refresh(hass, entry, cache, calendars), "C300X agenda", eager_start=False,
    )


async def _async_refresh(hass: Any, entry: Any, cache: AgendaCache, calendars: tuple[str, ...]) -> None:
    now = dt_util.utcnow()
    end = now + timedelta(days=7)
    revision = cache.revision
    events: list[dict[str, Any]] = []
    failed = False
    completed = False
    try:
        try:
            async with asyncio.timeout(FETCH_TIMEOUT):
                for entity_id in calendars:
                    state = hass.states.get(entity_id)
                    if state is None or state.state in ("unavailable", "unknown"):
                        failed = True
                        continue
                    try:
                        response = await hass.services.async_call(
                            "calendar", "get_events",
                            {"start_date_time": now.isoformat(), "end_date_time": end.isoformat()},
                            target={"entity_id": entity_id}, blocking=True, return_response=True,
                        )
                        data = response.get(entity_id) if isinstance(response, dict) else None
                        if not isinstance(data, dict) or not isinstance(data.get("events"), list):
                            failed = True
                            continue
                        events.extend(await _events(data["events"], entity_id,
                                                    _text(state.attributes.get("friendly_name", entity_id), 60), now, end))
                    except Exception:
                        # Calendar providers may raise non-HA exceptions. Cache
                        # failure, but let CancelledError terminate the task.
                        failed = True
        except TimeoutError:
            failed = True
        if cache.closed or not _entry_active(entry):
            return
        cache.events, cache.failed, cache.calendars = events, failed, calendars
        cache.expires = dt_util.utcnow() + timedelta(seconds=CACHE_SECONDS) if revision == cache.revision else None
        completed = True
    finally:
        cache.task = None
        if completed and cache.notify is not None:
            cache.notify()


def _event_time(value: Any) -> tuple[datetime, bool] | None:
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        if len(value) == 10:
            day = dt_util.parse_date(value)
            if day is None:
                return None
            return datetime.combine(day, datetime.min.time(), dt_util.DEFAULT_TIME_ZONE), True
        stamp = dt_util.parse_datetime(value)
        if stamp is None:
            return None
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        return stamp, False
    except (ValueError, OverflowError):
        return None


def _text(value: Any, limit: int) -> str:
    return " ".join(value[:limit * 8].split())[:limit] if isinstance(value, str) else ""


async def _events(raw: Any, entity_id: str, name: str, now: datetime, end: datetime) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return result
    if len(raw) > MAX_PROVIDER_EVENTS:
        # Do not publish a misleading top five from a partially scanned list.
        raise ValueError("calendar response exceeds event processing budget")
    for index, event in enumerate(raw):
        if index % EVENT_BATCH_SIZE == 0:
            await asyncio.sleep(0)
        if not isinstance(event, dict):
            continue
        start = _event_time(event.get("start"))
        stop = _event_time(event.get("end"))
        if start is None or stop is None or stop[0] <= now or start[0] >= end or stop[0] <= start[0]:
            continue
        result.append({"start": start[0].isoformat(), "end": stop[0].isoformat(),
                       "all_day": start[1], "summary": _text(event.get("summary"), 100),
                       "calendar": name, "entity_id": entity_id})
        # Provider results may be unsorted; keep only the next five per calendar.
        result.sort(key=lambda item: (datetime.fromisoformat(item["start"]), item["summary"]))
        del result[5:]
    return result


async def async_agenda_dashboard_page(hass: Any, entry: Any, language: str = "en") -> dict[str, Any] | None:
    """Return the next five ongoing/upcoming events within seven days, or None."""
    settings = configured_agenda_page(entry)
    if not _entry_active(entry) or not settings["enabled"]:
        return None
    labels = optional_labels(language)
    if not settings["calendars"]:
        return {"title": labels["agenda"], "agenda": {
            "events": [], "empty_text": labels["empty"], "error": "",
        }}
    cache = _cache(hass, entry)
    calendars = tuple(settings["calendars"])
    now = dt_util.utcnow()
    if cache.calendars != calendars or cache.expires is None or cache.expires <= now:
        _start_refresh(hass, entry, cache, calendars)
    events = [dict(event) for event in cache.events if datetime.fromisoformat(event["end"]) > now]
    events.sort(key=lambda event: (datetime.fromisoformat(event["start"]), event["entity_id"], event["summary"]))
    events = events[:5]
    for event in events:
        start = dt_util.as_local(datetime.fromisoformat(event["start"]))
        event["when"] = start.strftime("%d.%m. ") + (labels["all_day"] if event["all_day"] else start.strftime("%H:%M"))
    loading = cache.task is not None
    return {"title": labels["agenda"], "agenda": {
        "events": events, "loading": loading,
        "empty_text": labels["loading"] if loading else labels["empty"],
        "error": labels["calendar_error"] if cache.failed else "",
    }}
